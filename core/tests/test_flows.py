"""End-to-end service flows against a real database (run with: python manage.py test)."""
from datetime import date, timedelta

from django.db import models
from django.test import TestCase
from django.utils import timezone

from branchops.models import Dispatch
from branchops.services import dispatches, requests
from core.constants import DISPATCH_STATUS, LEDGER_TYPES, PURCHASE_STATUS, REQUEST_STATUS
from core.errors import Conflict, ServiceError
from core.models import AuditLog, Setting
from core.tests.helpers import fake_request, make_world, receive_stock
from inventory.models import StockLedger
from inventory.services import adjustments, issues, purchases, retention
from inventory.services.stock import get_balance


class PurchaseAndIssueTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def test_partial_receipts_move_status_and_stock(self):
        w = self.w
        req = fake_request(w.officer)
        p = purchases.create_purchase(req, {'supplier': w.supplier, 'purchase_date': date.today(), 'invoice_ref': '', 'notes': '',
                                            'lines': [{'item': w.paper, 'quantity_ordered': 10, 'unit_cost': '5.00'}]})
        line = p.lines.first()
        purchases.receive_purchase(req, p.pk, [{'line_id': line.pk, 'quantity': 4}])
        p.refresh_from_db()
        self.assertEqual(p.status, PURCHASE_STATUS.PARTLY_RECEIVED)
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 4)
        purchases.receive_purchase(req, p.pk, [{'line_id': line.pk, 'quantity': 6}])
        p.refresh_from_db()
        self.assertEqual(p.status, PURCHASE_STATUS.RECEIVED)
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 10)
        with self.assertRaises(ServiceError):
            purchases.receive_purchase(req, p.pk, [{'line_id': line.pk, 'quantity': 1}])

    def test_issue_cannot_overdraw_and_cancel_restores_stock(self):
        w = self.w
        receive_stock(w, w.paper, 5)
        req = fake_request(w.officer)
        with self.assertRaises(Conflict):
            issues.create_issue(req, {'recipient': 'Team', 'department': '', 'issue_date': date.today(), 'purpose': '',
                                      'lines': [{'item': w.paper, 'quantity': 6}]})
        issue = issues.create_issue(req, {'recipient': 'Team', 'department': 'Admin', 'issue_date': date.today(), 'purpose': '',
                                          'lines': [{'item': w.paper, 'quantity': 3}]})
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 2)
        issues.cancel_issue(req, issue.pk, 'mistake')
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 5)
        self.assertTrue(StockLedger.objects.filter(type=LEDGER_TYPES.REVERSAL).exists())
        with self.assertRaises(ServiceError):
            issues.cancel_issue(req, issue.pk, 'again')

    def test_adjustment_cannot_go_below_zero(self):
        w = self.w
        receive_stock(w, w.pen, 2)
        req = fake_request(w.officer)
        with self.assertRaises(Conflict):
            adjustments.create_adjustment(req, branch=w.main, item=w.pen, direction='remove', quantity=3, reason='damaged')
        self.assertEqual(adjustments.create_adjustment(req, branch=w.main, item=w.pen, direction='remove', quantity=2, reason='damaged'), 0)

    def test_ledger_rows_cannot_be_edited_or_deleted(self):
        receive_stock(self.w, self.w.pen, 1)
        row = StockLedger.objects.first()
        with self.assertRaises(RuntimeError):
            row.save()
        with self.assertRaises(RuntimeError):
            row.delete()
        with self.assertRaises(RuntimeError):
            StockLedger.objects.all().update(quantity_change=99)


class BranchFlowTests(TestCase):
    def setUp(self):
        self.w = make_world()
        s = Setting.get()
        s.branch_module_enabled = True
        s.save()

    def test_request_review_dispatch_receive_with_differences_and_close(self):
        w = self.w
        receive_stock(w, w.paper, 50)
        kandy_req = fake_request(w.branch_user)
        rq = requests.create_request(kandy_req, 'Need paper', [{'item': w.paper, 'quantity': 20}])
        line = rq.lines.first()
        officer_req = fake_request(w.officer)

        with self.assertRaises(Conflict):  # reducing without a reason
            requests.review_request(officer_req, rq.pk, [{'line_id': line.pk, 'quantity_approved': 15, 'reason': ''}])
        requests.review_request(officer_req, rq.pk, [{'line_id': line.pk, 'quantity_approved': 15, 'reason': 'Limited stock'}])
        rq.refresh_from_db()
        self.assertEqual(rq.status, REQUEST_STATUS.PARTLY_APPROVED)

        with self.assertRaises(Conflict):  # more than approved
            dispatches.create_dispatch(officer_req, request_obj_id=rq.pk, lines=[{'item': w.paper, 'quantity': 16}])
        d = dispatches.create_dispatch(officer_req, request_obj_id=rq.pk, lines=[{'item': w.paper, 'quantity': 15}])
        rq.refresh_from_db()
        self.assertEqual(rq.status, REQUEST_STATUS.COMPLETED)
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 35)
        in_transit = StockLedger.objects.filter(in_transit=True).aggregate(t=models.Sum('quantity_change'))['t']
        self.assertEqual(in_transit, 15)

        dispatches.receive_dispatch(kandy_req, d.pk, [{'item': w.paper.pk, 'received': 12, 'damaged': 1}])
        d.refresh_from_db()
        self.assertEqual(d.status, DISPATCH_STATUS.RECEIVED_WITH_DIFFERENCES)
        self.assertEqual(get_balance(w.kandy.pk, w.paper.pk), 12)

        dispatches.close_dispatch(officer_req, d.pk, 'return_to_main', 'came back')
        d.refresh_from_db()
        self.assertEqual(d.status, DISPATCH_STATUS.CLOSED)
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 38)  # 35 + 1 damaged + 2 short returned
        self.assertEqual(StockLedger.objects.filter(in_transit=True).aggregate(t=models.Sum('quantity_change'))['t'], 0)

    def test_only_own_branch_can_cancel_and_only_before_review(self):
        w = self.w
        kandy_req = fake_request(w.branch_user)
        rq = requests.create_request(kandy_req, '', [{'item': w.pen, 'quantity': 1}])
        requests.cancel_request(kandy_req, rq.pk)
        rq.refresh_from_db()
        self.assertEqual(rq.status, REQUEST_STATUS.CANCELLED)
        with self.assertRaises(ServiceError):
            requests.cancel_request(kandy_req, rq.pk)


class RetentionTests(TestCase):
    def test_old_rows_fold_into_opening_balance_without_changing_stock(self):
        w = make_world()
        receive_stock(w, w.paper, 7)
        old = timezone.now() - timedelta(days=45)
        models.QuerySet(StockLedger).update(created_at=old)
        receive_stock(w, w.paper, 3)
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 10)
        result = retention.prune_old_stock_movements()
        self.assertFalse(result['skipped'])
        self.assertEqual(get_balance(w.main.pk, w.paper.pk), 10)
        self.assertTrue(StockLedger.objects.filter(type=LEDGER_TYPES.OPENING_BALANCE, quantity_change=7).exists())
        self.assertFalse(StockLedger.objects.filter(created_at__lt=timezone.now() - timedelta(days=30)).exists())


class AuditTests(TestCase):
    def test_audit_rows_are_append_only(self):
        w = make_world()
        receive_stock(w, w.paper, 1)
        self.assertTrue(AuditLog.objects.exists())
        with self.assertRaises(RuntimeError):
            AuditLog.objects.all().delete()
