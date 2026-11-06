from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import Branch, User
from core.constants import BRANCH_TYPES
from core.models import AuditLog, Setting
from vouchers.models import ExpenseCategory, Voucher, VoucherEvent, VoucherSchedule
from vouchers.services import generate_due_schedules


class VoucherWorkflowTests(TestCase):
    def setUp(self):
        self.branch = Branch.objects.create(name='Main Office', code='MHO', type=BRANCH_TYPES.MAIN)
        self.manager = User.objects.create_user(
            'manager@example.test', 'Strong-Passw0rd!', name='Accounts Manager',
            role='manager', branch=self.branch, permissions=['vouchers.view', 'vouchers.approve', 'vouchers.print'],
        )
        self.recommender = User.objects.create_user(
            'recommender@example.test', 'Strong-Passw0rd!', name='Voucher Recommender',
            role='recommender', branch=self.branch,
            permissions=['vouchers.view', 'vouchers.recommend'],
        )
        self.creator = User.objects.create_user(
            'assistant@example.test', 'Strong-Passw0rd!', name='Accounts Assistant',
            role='assistant', branch=self.branch,
            permissions=['vouchers.view', 'vouchers.create', 'vouchers.print', 'vouchers.schedule'],
        )
        self.category = ExpenseCategory.objects.create(name='Office supplies')
        settings = Setting.get()
        settings.payment_voucher_module_enabled = True
        settings.save()

    def voucher_data(self, **overrides):
        data = {
            'amount': '125.00',
            'date': timezone.localdate().isoformat(),
            'method_of_payment': Voucher.PaymentMethod.BANK_TRANSFER,
            'to': 'Office supplier',
            'account_details': 'Operating account',
            'being': 'Stationery',
            'payee': 'Office supplier',
            'category': str(self.category.pk),
            'branch': str(self.branch.pk),
            'approver': str(self.manager.pk),
        }
        data.update(overrides)
        return data

    def test_manager_approval_unlocks_print_and_records_audit_history(self):
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='submit'))
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(prepared_by=self.creator)
        self.assertEqual(voucher.status, Voucher.Status.PENDING)
        self.assertEqual(voucher.approver, self.manager)
        self.assertIsNotNone(voucher.approval_requested_at)
        self.assertEqual(self.client.get(reverse('vouchers:voucher_print', args=[voucher.pk])).status_code, 403)

        self.client.force_login(self.manager)
        queue = self.client.get(reverse('vouchers:approval_queue'))
        self.assertContains(queue, voucher.number)
        response = self.client.post(reverse('vouchers:voucher_action', args=[voucher.pk, 'approve']))
        self.assertEqual(response.status_code, 302)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.APPROVED)
        self.assertEqual(voucher.approved_by, self.manager)
        self.assertIsNotNone(voucher.approved_at)
        self.assertEqual(VoucherEvent.objects.filter(voucher=voucher).count(), 3)

        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(reverse('vouchers:voucher_print', args=[voucher.pk])).status_code, 200)

    def test_rejection_reason_is_recorded_and_voucher_remains_unprintable(self):
        self.client.force_login(self.creator)
        self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='submit'))
        voucher = Voucher.objects.get(prepared_by=self.creator)
        self.client.force_login(self.manager)
        response = self.client.post(
            reverse('vouchers:voucher_action', args=[voucher.pk, 'reject']),
            {'reason': 'Invoice is missing'},
        )
        self.assertEqual(response.status_code, 302)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.REJECTED)
        self.assertEqual(voucher.rejection_reason, 'Invoice is missing')
        self.assertEqual(voucher.events.get(action='rejected').actor, self.manager)
        self.client.force_login(self.creator)
        self.assertEqual(self.client.get(reverse('vouchers:voucher_print', args=[voucher.pk])).status_code, 403)

    def test_recommendation_precedes_approval_and_records_each_action(self):
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(
            action='submit', recommender=str(self.recommender.pk),
        ))
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(prepared_by=self.creator)
        self.assertEqual(voucher.status, Voucher.Status.RECOMMENDING)
        self.assertEqual(voucher.recommender, self.recommender)
        self.assertEqual(self.client.get(reverse('vouchers:voucher_print', args=[voucher.pk])).status_code, 403)

        self.client.force_login(self.recommender)
        self.assertContains(self.client.get(reverse('vouchers:recommendation_queue')), voucher.number)
        self.client.post(reverse('vouchers:voucher_action', args=[voucher.pk, 'recommend']))
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.PENDING)
        self.assertEqual(voucher.recommended_by, self.recommender)
        self.assertIsNotNone(voucher.recommended_at)
        self.assertTrue(voucher.events.filter(action='recommended', actor=self.recommender).exists())
        self.assertEqual(self.client.get(reverse('vouchers:approval_queue')).status_code, 403)

        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse('vouchers:approval_queue')), voucher.number)
        self.client.post(reverse('vouchers:voucher_action', args=[voucher.pk, 'approve']))
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.APPROVED)
        self.assertEqual(voucher.events.count(), 4)
        self.client.force_login(self.creator)
        printed = self.client.get(reverse('vouchers:voucher_print', args=[voucher.pk]))
        self.assertEqual(printed.status_code, 200)
        self.assertContains(printed, '@page { size: A4 landscape;')
        self.assertContains(printed, 'Recommended By')
        self.assertContains(printed, self.recommender.name)
        self.assertContains(printed, 'Recommendation Date')
        self.assertContains(printed, timezone.localtime(voucher.recommended_at).strftime('%d-%m-%Y %H:%M'))
        self.assertContains(printed, '<div class="voucher-signature">Payee Signature</div>', html=True)
        self.assertContains(printed, '<div class="voucher-signature">Authorized Signature</div>', html=True)

    def test_recommendation_rejection_returns_to_creator_for_resubmission(self):
        self.client.force_login(self.creator)
        self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(
            action='submit', recommender=str(self.recommender.pk),
        ))
        voucher = Voucher.objects.get(prepared_by=self.creator)
        self.client.force_login(self.recommender)
        self.client.post(
            reverse('vouchers:voucher_action', args=[voucher.pk, 'reject']),
            {'reason': 'Please attach supporting documentation'},
        )
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.REJECTED)
        self.assertEqual(voucher.rejection_reason, 'Please attach supporting documentation')
        self.assertTrue(voucher.events.filter(action='recommendation_rejected').exists())

        self.client.force_login(self.creator)
        response = self.client.post(
            reverse('vouchers:voucher_update', args=[voucher.pk]),
            self.voucher_data(action='submit', recommender=str(self.recommender.pk)),
        )
        self.assertEqual(response.status_code, 302)
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.RECOMMENDING)
        self.assertIsNone(voucher.rejection_reason or None)
        self.assertEqual(voucher.events.filter(action='submitted').count(), 2)

    def test_recommender_and_approver_must_be_different(self):
        dual_role = User.objects.create_user(
            'dual@example.test', 'Strong-Passw0rd!', name='Dual Reviewer',
            role='reviewer', branch=self.branch,
            permissions=['vouchers.view', 'vouchers.recommend', 'vouchers.approve'],
        )
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(
            action='submit', recommender=str(dual_role.pk), approver=str(dual_role.pk),
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'must be different users')
        self.assertFalse(Voucher.objects.exists())

    def test_only_super_admin_can_permanently_delete_after_matching_id_confirmation(self):
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='draft'))
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(prepared_by=self.creator)
        delete_url = reverse('vouchers:voucher_delete', args=[voucher.pk])

        self.client.force_login(self.manager)
        detail = self.client.get(reverse('vouchers:voucher_detail', args=[voucher.pk]))
        self.assertNotContains(detail, 'Delete voucher')
        self.assertEqual(self.client.get(delete_url).status_code, 403)
        self.assertEqual(self.client.post(delete_url, {'voucher_id': voucher.number}).status_code, 403)
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='payment_voucher.delete').exists())

        admin = User.objects.create_user(
            'super-admin@example.test', 'Strong-Passw0rd!', name='Super Admin',
            role='super_admin', branch=self.branch,
        )
        self.client.force_login(admin)
        self.assertContains(self.client.get(reverse('vouchers:voucher_detail', args=[voucher.pk])), 'Delete voucher')
        confirmation = self.client.get(delete_url)
        self.assertEqual(confirmation.status_code, 200)
        self.assertContains(confirmation, 'permanently deletes the voucher')
        self.assertContains(confirmation, voucher.number)

        mismatch = self.client.post(delete_url, {'voucher_id': 'PV-WRONG'})
        self.assertEqual(mismatch.status_code, 200)
        self.assertContains(mismatch, 'does not match the selected voucher')
        self.assertTrue(Voucher.objects.filter(pk=voucher.pk).exists())
        self.assertFalse(AuditLog.objects.filter(action='payment_voucher.delete').exists())

        response = self.client.post(delete_url, {'voucher_id': voucher.number})
        self.assertRedirects(response, reverse('vouchers:voucher_list'))
        self.assertFalse(Voucher.objects.filter(pk=voucher.pk).exists())

        audit = AuditLog.objects.get(action='payment_voucher.delete', record_id=str(voucher.pk))
        self.assertEqual(audit.user, admin)
        self.assertEqual(audit.old_value['number'], voucher.number)
        self.assertEqual(audit.new_value['deleted_voucher_id'], voucher.pk)
        self.assertEqual(audit.new_value['deleted_by_id'], admin.pk)
        self.assertEqual(audit.new_value['deleted_by'], admin.get_username())
        self.assertTrue(audit.new_value['deleted_at'])
        event = VoucherEvent.objects.get(voucher_number=voucher.number, action='created')
        self.assertIsNone(event.voucher_id)

    def test_self_approval_cannot_bypass_an_assigned_recommender(self):
        self.creator.permissions = [
            'vouchers.view', 'vouchers.create', 'vouchers.print', 'vouchers.self_approve',
        ]
        self.creator.save(update_fields=['permissions'])
        settings = Setting.get()
        settings.payment_voucher_self_approval_enabled = True
        settings.save()
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(
            action='self_approve', recommender=str(self.recommender.pk),
        ))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'must be submitted for recommendation')
        self.assertFalse(Voucher.objects.exists())

    def test_self_approval_requires_global_setting_and_user_permission(self):
        self.creator.permissions = ['vouchers.view', 'vouchers.create', 'vouchers.print', 'vouchers.self_approve']
        self.creator.save(update_fields=['permissions'])
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='self_approve'))
        self.assertEqual(response.status_code, 403)
        self.assertFalse(Voucher.objects.exists())

        settings = Setting.get()
        settings.payment_voucher_self_approval_enabled = True
        settings.save()
        response = self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='self_approve'))
        self.assertEqual(response.status_code, 302)
        voucher = Voucher.objects.get(prepared_by=self.creator)
        self.assertEqual(voucher.status, Voucher.Status.APPROVED)
        self.assertEqual(voucher.approved_by, self.creator)
        self.assertEqual(voucher.events.order_by('-created_at').first().action, 'self_approved')

    def test_scheduled_voucher_is_generated_once_and_uses_manager_queue(self):
        self.client.force_login(self.creator)
        today = timezone.localdate()
        due_date = today + timedelta(days=1)
        data = {
            'title': 'Monthly stationery',
            'category': str(self.category.pk),
            'amount': '75.00',
            'frequency': 'monthly',
            'next_run': due_date.isoformat(),
            'method_of_payment': Voucher.PaymentMethod.BANK_TRANSFER,
            'to': 'Office supplier',
            'account_details': 'Operating account',
            'being': 'Monthly stationery',
            'payee': 'Office supplier',
            'branch': str(self.branch.pk),
            'approver': str(self.manager.pk),
            'is_active': 'on',
        }
        response = self.client.post(reverse('vouchers:schedule_create'), data)
        self.assertEqual(response.status_code, 302)
        generated, errors = generate_due_schedules(today=due_date)
        self.assertEqual((generated, errors), (1, []))
        voucher = Voucher.objects.get(schedule__title='Monthly stationery')
        self.assertEqual(voucher.status, Voucher.Status.PENDING)
        self.assertEqual(voucher.date, due_date)
        generated, errors = generate_due_schedules(today=due_date)
        self.assertEqual((generated, errors), (0, []))

        self.client.force_login(self.manager)
        self.assertContains(self.client.get(reverse('vouchers:approval_queue')), voucher.number)

    def test_scheduled_voucher_with_recommender_enters_recommendation_queue(self):
        today = timezone.localdate()
        due_date = today + timedelta(days=1)
        data = {
            'title': 'Recommended monthly stationery',
            'category': str(self.category.pk),
            'amount': '75.00',
            'frequency': 'monthly',
            'next_run': due_date.isoformat(),
            'method_of_payment': Voucher.PaymentMethod.BANK_TRANSFER,
            'to': 'Office supplier',
            'account_details': 'Operating account',
            'being': 'Monthly stationery',
            'payee': 'Office supplier',
            'branch': str(self.branch.pk),
            'recommender': str(self.recommender.pk),
            'approver': str(self.manager.pk),
            'is_active': 'on',
        }
        self.client.force_login(self.creator)
        response = self.client.post(reverse('vouchers:schedule_create'), data)
        self.assertEqual(response.status_code, 302)
        generated, errors = generate_due_schedules(today=due_date)
        self.assertEqual((generated, errors), (1, []))
        voucher = Voucher.objects.get(schedule__title='Recommended monthly stationery')
        self.assertEqual(voucher.status, Voucher.Status.RECOMMENDING)
        self.assertEqual(voucher.recommender, self.recommender)
        self.client.force_login(self.recommender)
        self.assertContains(self.client.get(reverse('vouchers:recommendation_queue')), voucher.number)

    def test_scheduled_voucher_can_self_approve_only_when_globally_enabled(self):
        creator = User.objects.create_user(
            'scheduler@example.test', 'Strong-Passw0rd!', name='Scheduler',
            role='assistant', branch=self.branch,
            permissions=['vouchers.view', 'vouchers.create', 'vouchers.schedule', 'vouchers.self_approve'],
        )
        today = timezone.localdate()
        due_date = today + timedelta(days=1)
        data = {
            'title': 'Self-approved monthly service',
            'category': str(self.category.pk),
            'amount': '50.00',
            'frequency': 'monthly',
            'next_run': due_date.isoformat(),
            'method_of_payment': Voucher.PaymentMethod.CASH,
            'cash': 'on',
            'to': 'Service provider',
            'being': 'Monthly service',
            'payee': 'Service provider',
            'branch': str(self.branch.pk),
            'is_active': 'on',
        }
        self.client.force_login(creator)
        response = self.client.post(reverse('vouchers:schedule_create'), data)
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Choose an authorized manager')
        self.assertFalse(VoucherSchedule.objects.filter(created_by=creator).exists())

        settings = Setting.get()
        settings.payment_voucher_self_approval_enabled = True
        settings.save()
        response = self.client.post(reverse('vouchers:schedule_create'), data)
        self.assertEqual(response.status_code, 302)
        generated, errors = generate_due_schedules(today=due_date)
        self.assertEqual((generated, errors), (1, []))
        voucher = Voucher.objects.get(schedule__title='Self-approved monthly service')
        self.assertEqual(voucher.status, Voucher.Status.APPROVED)
        self.assertEqual(voucher.approved_by, creator)

    def test_only_the_assigned_manager_can_approve(self):
        self.client.force_login(self.creator)
        self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='submit'))
        voucher = Voucher.objects.get(prepared_by=self.creator)
        other_manager = User.objects.create_user(
            'other-manager@example.test', 'Strong-Passw0rd!', name='Other Manager',
            role='manager', branch=self.branch, permissions=['vouchers.view', 'vouchers.approve'],
        )
        self.client.force_login(other_manager)
        self.client.post(reverse('vouchers:voucher_action', args=[voucher.pk, 'approve']))
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.PENDING)
        self.assertIsNone(voucher.approved_by)

    def test_super_admin_can_toggle_module_and_self_approval_from_existing_settings(self):
        admin = User.objects.create_user(
            'admin@example.test', 'Strong-Passw0rd!', name='Admin',
            role='super_admin', branch=self.branch,
        )
        self.client.force_login(admin)
        response = self.client.get(reverse('core:settings'))
        self.assertContains(response, 'Voucher self-approval')
        self.client.post(reverse('core:settings'), {'action': 'payment_voucher_self_approval_toggle'})
        settings = Setting.get()
        self.assertTrue(settings.payment_voucher_self_approval_enabled)
        self.client.post(reverse('core:settings'), {'action': 'payment_voucher_module_toggle'})
        settings.refresh_from_db()
        self.assertFalse(settings.payment_voucher_module_enabled)

    def test_module_and_permission_are_enforced_on_routes(self):
        unprivileged = User.objects.create_user(
            'viewer@example.test', 'Strong-Passw0rd!', name='Viewer',
            role='viewer', branch=self.branch, permissions=[],
        )
        self.client.force_login(unprivileged)
        self.assertEqual(self.client.get(reverse('vouchers:voucher_list')).status_code, 403)
        self.client.force_login(self.creator)
        settings = Setting.get()
        settings.payment_voucher_module_enabled = False
        settings.save()
        self.assertEqual(self.client.get(reverse('vouchers:voucher_list')).status_code, 403)

    def test_budget_limit_blocks_approval_without_changing_pending_status(self):
        self.category.monthly_budget_limit = Decimal('100.00')
        self.category.save(update_fields=['monthly_budget_limit'])
        self.client.force_login(self.creator)
        self.client.post(reverse('vouchers:voucher_create'), self.voucher_data(action='submit'))
        voucher = Voucher.objects.get(prepared_by=self.creator)
        self.client.force_login(self.manager)
        self.client.post(reverse('vouchers:voucher_action', args=[voucher.pk, 'approve']))
        voucher.refresh_from_db()
        self.assertEqual(voucher.status, Voucher.Status.PENDING)
        self.assertIsNone(voucher.approved_at)
