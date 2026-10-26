"""Loads a small, fictional demo dataset: 5 of everything. Development only (needs DJANGO_DEBUG=true).

    python manage.py seed_sample_data

Run `python manage.py seed` first (it creates the main office and the Super Admin). Everything is created through
the app's own services, so stock, balances, document numbers and the audit log are exactly what real use would make.
The main-office work (purchases, approvals, dispatches) is done as the first active Super Admin.
To start again, run `python manage.py clear_all_data`.

Optional: SAMPLE_USER_PASSWORD in the environment chooses the demo users' password.
"""
import os
from datetime import timedelta
from decimal import Decimal as D
from types import SimpleNamespace

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from accounts.models import Branch, User
from accounts.roles import ensure_default_roles
from branchops.models import Request
from branchops.services import dispatches, requests
from catalog.models import Category, Item, Supplier
from core.constants import BRANCH_TYPES, ROLES
from core.models import Setting
from inventory.services import issues, purchases
from pettycash import services as petty

MARKER_ITEM = 'PAP-A4-80'


def as_user(user):
    """What the services need from a web request."""
    return SimpleNamespace(user=user, META={'REMOTE_ADDR': '127.0.0.1'})


class Command(BaseCommand):
    help = 'Load 5 sample records of every kind (development only).'

    def handle(self, *args, **options):
        if not settings.DEBUG:
            raise CommandError('Sample data is disabled unless DJANGO_DEBUG is on (it is off in production).')
        self.password = os.environ.get('SAMPLE_USER_PASSWORD', 'HeritageDemo!2026')
        if len(self.password) < 8:
            raise CommandError('SAMPLE_USER_PASSWORD must be at least 8 characters.')
        if Item.objects.filter(code=MARKER_ITEM).exists():
            raise CommandError('Sample data is already loaded. Run "python manage.py clear_all_data" first to start again.')
        self.admin = User.objects.filter(role=ROLES.SUPER_ADMIN, active=True).order_by('pk').first()
        if not self.admin:
            raise CommandError('There is no Super Admin yet. Run "python manage.py seed" first.')
        self.main = Branch.objects.filter(type=BRANCH_TYPES.MAIN).first()
        if not self.main:
            raise CommandError('There is no main office yet. Run "python manage.py seed" first.')
        with transaction.atomic():
            self.build()

    # ------------------------------------------------------------------ the dataset
    def build(self):
        s = Setting.get()
        s.branch_module_enabled = True
        if s.company_name in ('', 'Our Company'):
            s.company_name = 'Heritage Supplies Demo'
        s.save()
        ensure_default_roles()
        admin = as_user(self.admin)
        today = timezone.localdate()

        # 5 branches, each with 1 user (5 users)
        specs = [('KDY', 'Kandy Branch', 'Peradeniya Road, Kandy', '+94 81 555 0101', 'Dinuka Fernando', 'dinuka.kandy'),
                 ('GAL', 'Galle Branch', 'Wakwella Road, Galle', '+94 91 555 0102', 'Tharushi Silva', 'tharushi.galle'),
                 ('JAF', 'Jaffna Branch', 'Hospital Road, Jaffna', '+94 21 555 0103', 'Kajan Rajaratnam', 'kajan.jaffna'),
                 ('MTR', 'Matara Branch', 'Anagarika Dharmapala Mw, Matara', '+94 41 555 0104', 'Sanduni Wickramasinghe', 'sanduni.matara'),
                 ('KUR', 'Kurunegala Branch', 'Dambulla Road, Kurunegala', '+94 37 555 0105', 'Ishan Bandara', 'ishan.kurunegala')]
        perms = ['items.view', 'stock.view', 'reports.view', 'issues.view', 'issues.manage',
                 'requests.create', 'dispatches.receive', 'petty_cash.request']
        self.br, self.u = {}, {}
        for code, name, address, phone, person, mail in specs:
            self.br[code] = Branch.objects.create(code=code, name=name, address=address, phone=phone, type=BRANCH_TYPES.BRANCH)
            self.u[code] = User.objects.create_user(email=f'{mail}@example.test', password=self.password, name=person,
                                                    role=ROLES.BRANCH_USER, branch=self.br[code], permissions=perms)

        # 5 categories, 5 suppliers, 5 items
        cats = {n: Category.objects.get_or_create(name=n)[0] for n in
                ['Paper', 'Pens and Pencils', 'Printer Ink and Toner', 'Stationery', 'Cleaning Supplies']}
        sup = {n: Supplier.objects.create(name=n, contact=c, phone=p) for n, c, p in [
            ('Lanka Office Mart (Demo)', 'Nadeesha Perera', '+94 11 555 0201'),
            ('Island Stationers (Demo)', 'Ruwan Silva', '+94 81 555 0202'),
            ('Metro Print Supplies (Demo)', 'Ishara De Mel', '+94 11 555 0203'),
            ('Paper Hub Lanka (Demo)', 'Chamari Gunawardena', '+94 11 555 0204'),
            ('CleanCo Wholesale (Demo)', 'Asela Jayawardena', '+94 11 555 0205')]}
        it = {code: Item.objects.create(code=code, name=name, category=cats[cat], unit=unit, min_stock=minimum, last_unit_cost=cost)
              for code, name, cat, unit, minimum, cost in [
                  (MARKER_ITEM, 'A4 Copy Paper, 80 gsm', 'Paper', 'ream', 25, 1180),
                  ('PEN-BLU-01', 'Blue Ballpoint Pens', 'Pens and Pencils', 'box', 10, 950),
                  ('TON-HP-107', 'Laser Toner Cartridge 107A', 'Printer Ink and Toner', 'piece', 4, 6200),
                  ('FILE-A4-01', 'A4 Document Folders', 'Stationery', 'piece', 15, 180),
                  ('CLN-SAN-01', 'Surface Sanitizer, 500 ml', 'Cleaning Supplies', 'bottle', 8, 640)]}
        paper, pen, toner, files, san = (it[c] for c in (MARKER_ITEM, 'PEN-BLU-01', 'TON-HP-107', 'FILE-A4-01', 'CLN-SAN-01'))
        sup_mart, sup_island, sup_metro, sup_hub, sup_clean = sup.values()

        # 5 purchases: received, partly received, waiting, received, cancelled
        def buy(supplier, ago, invoice, notes, lines, receive=None):
            p = purchases.create_purchase(admin, {'supplier': supplier, 'purchase_date': today - timedelta(days=ago), 'invoice_ref': invoice,
                                                  'notes': notes, 'lines': [{'item': i, 'quantity_ordered': q, 'unit_cost': c} for i, q, c in lines]})
            if receive is not None:
                got = [{'line_id': l.pk, 'quantity': receive.get(l.item_id, l.quantity_ordered)} for l in p.lines.all()]
                purchases.receive_purchase(admin, p.pk, [g for g in got if g['quantity'] > 0])
            return p
        buy(sup_mart, 35, 'INV-LM-2408', 'Monthly stationery replenishment.',
            [(paper, 200, 1180), (pen, 120, 950), (toner, 12, 6200), (files, 80, 180), (san, 40, 640)], receive={})
        buy(sup_metro, 9, 'INV-MP-2411', 'Second toner delivery is still outstanding.', [(toner, 10, 6100)], receive={toner.pk: 6})
        buy(sup_island, 2, 'PO-IS-8821', 'Waiting for the paper delivery.', [(paper, 100, 1170)])
        buy(sup_hub, 14, 'INV-PH-3307', 'Paper and folders for the main office.', [(paper, 60, 1190), (files, 40, 175)], receive={})
        cancelled = buy(sup_clean, 6, 'PO-CC-0119', 'Ordered twice by mistake.', [(san, 30, 630)])
        purchases.cancel_purchase(admin, cancelled.pk)

        # 5 branch requests: completed, approved (sent), waiting, partly approved, rejected
        def ask(code, notes, lines):
            return requests.create_request(as_user(self.u[code]), notes, [{'item': i, 'quantity': q} for i, q in lines])

        def decide(req, quantities, reason=''):
            decisions = [{'line_id': l.pk, 'quantity_approved': quantities[l.item_id], 'reason': reason if quantities[l.item_id] < l.quantity_requested else ''}
                         for l in req.lines.all()]
            return requests.review_request(admin, req.pk, decisions)
        r_kdy = ask('KDY', 'Monthly paper and pen replenishment.', [(paper, 30), (pen, 20)])
        r_gal = ask('GAL', 'Pens and folders for the service counter.', [(pen, 24), (files, 10)])
        ask('JAF', 'Please send paper and toner with the next delivery.', [(paper, 20), (toner, 2)])
        r_mtr = ask('MTR', 'Paper and sanitizer for the new floor.', [(paper, 40), (san, 10)])
        r_kur = ask('KUR', 'Toner for the front-desk printer.', [(toner, 5)])
        decide(r_kdy, {paper.pk: 30, pen.pk: 20})
        decide(r_gal, {pen.pk: 24, files.pk: 10})
        decide(r_mtr, {paper.pk: 25, san.pk: 10}, 'Paper is limited this month')
        decide(r_kur, {toner.pk: 0}, 'No toner budget until next month')

        # 5 dispatches: received, on the way, received with damage, received, on the way
        def send(code, lines, req=None):
            return dispatches.create_dispatch(admin, request_obj_id=req.pk if req else None, destination_id=None if req else self.br[code].pk,
                                              dispatch_date=today, lines=[{'item': i, 'quantity': q} for i, q in lines])

        def receive(code, dsp, damaged=None):
            damaged = damaged or {}
            got = [{'item': l.item_id, 'received': l.quantity_sent - damaged.get(l.item_id, 0), 'damaged': damaged.get(l.item_id, 0)}
                   for l in dsp.lines.all()]
            return dispatches.receive_dispatch(as_user(self.u[code]), dsp.pk, got)
        d1 = send('KDY', [(paper, 30), (pen, 20)], req=r_kdy)
        send('GAL', [(pen, 24), (files, 10)], req=r_gal)
        d3 = send('JAF', [(paper, 20)])
        d4 = send('MTR', [(files, 15), (san, 6)])
        send('KUR', [(pen, 12)])
        receive('KDY', d1)
        receive('JAF', d3, damaged={paper.pk: 2})
        receive('MTR', d4)

        # 5 office issues: three at the main office (one cancelled), two at branches
        def give(user, person, dept, purpose, lines):
            return issues.create_issue(as_user(user), {'recipient': person, 'department': dept, 'issue_date': today, 'purpose': purpose,
                                                       'lines': [{'item': i, 'quantity': q} for i, q in lines]})
        give(self.admin, 'Facilities Team', 'Administration', 'Routine office use', [(paper, 12), (toner, 2)])
        give(self.admin, 'Cafeteria Staff', 'Administration', 'Cleaning of shared areas', [(san, 8)])
        wrong = give(self.admin, 'Reception Desk', 'Administration', 'Entered by mistake', [(files, 5)])
        issues.cancel_issue(admin, wrong.pk, 'Duplicate entry; returned to stock.')
        give(self.u['KDY'], 'Customer Service Team', 'Customer Service', 'Counter stationery', [(paper, 5), (pen, 2)])
        give(self.u['MTR'], 'Records Office', 'Records', 'Filing and record keeping', [(files, 3)])

        # 5 petty cash requests: approved in full, approved in full, approved for less, waiting, rejected
        def cash(user, amount, purpose):
            return petty.create_request(as_user(user), D(amount), purpose)

        def approve(req, amount, note=''):
            return petty.review_request(admin, req.pk, approve=True, amount=D(amount), note=note)
        c_main = cash(self.admin, '5000', 'Tea, snacks and small purchases for the main office')
        c_kdy = cash(self.u['KDY'], '4000', 'Printer cables and batteries')
        c_gal = cash(self.u['GAL'], '3000', 'Courier charges and cleaning cloths')
        cash(self.u['JAF'], '2500', 'Local purchase of folders')
        c_mtr = cash(self.u['MTR'], '1500', 'Extra stationery')
        approve(c_main, '5000')
        approve(c_kdy, '4000')
        approve(c_gal, '2000', 'Budget for this month')
        petty.review_request(admin, c_mtr.pk, approve=False, amount=None, note='Spend the current balance first')
        petty.record_expense(as_user(self.admin), D('1500'), 'Tea, sugar and cleaning cloths', today)
        petty.record_expense(as_user(self.u['KDY']), D('2500'), 'Printer cable and batteries', today)
        petty.record_expense(as_user(self.u['GAL']), D('400'), 'Courier charges', today)

        w = self.stdout.write
        w(self.style.SUCCESS('Sample data loaded: 5 branches, 5 users, 5 suppliers, 5 items, 5 purchases, 5 requests, '
                             f'5 dispatches, 5 office issues, 5 petty cash requests, {Category.objects.count()} categories '
                             '(the 5 starter ones plus Cleaning Supplies).'))
        w('Demo sign-ins (all @example.test): ' + ', '.join(f'{u.email.split("@")[0]}' for u in self.u.values()))
        w(f'Password for the demo users: {self.password}')
        w('Main-office work was recorded as the Super Admin, so sign in as that account to approve, send and manage.')
        w('To remove it all again: python manage.py clear_all_data')
