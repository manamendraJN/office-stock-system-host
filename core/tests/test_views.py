"""Page-level checks through the Django test client."""
from django.test import Client, TestCase, override_settings
from django.urls import reverse

from core.models import Setting
from core.tests.helpers import PASSWORD, make_world, receive_stock


class AccessTests(TestCase):
    def setUp(self):
        self.w = make_world()

    def login(self, email):
        r = self.client.post(reverse('accounts:login'), {'email': email, 'password': PASSWORD})
        self.assertIn(r.status_code, (302, 200))

    def test_pages_need_sign_in(self):
        for name in ['core:dashboard', 'catalog:item_list', 'inventory:purchase_list', 'inventory:stock', 'reports:index']:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 302, name)
            self.assertIn('login', r['Location'])

    def test_wrong_password_is_refused(self):
        r = self.client.post(reverse('accounts:login'), {'email': 'admin@example.test', 'password': 'nope-nope-nope'})
        self.assertEqual(r.status_code, 200)
        self.assertNotIn('_auth_user_id', self.client.session)

    def test_login_post_requires_csrf_token(self):
        client = Client(enforce_csrf_checks=True)
        response = client.post(reverse('accounts:login'), {
            'email': 'admin@example.test', 'password': PASSWORD,
        })
        self.assertEqual(response.status_code, 403)

    def test_login_rejects_external_next_redirect(self):
        response = self.client.post(reverse('accounts:login'), {
            'email': 'admin@example.test', 'password': PASSWORD, 'next': 'https://attacker.example/',
        })
        self.assertRedirects(response, reverse('core:dashboard'), fetch_redirect_response=False)

    def test_security_headers_and_external_motion_bootstrap(self):
        response = self.client.get(reverse('accounts:login'))
        self.assertIn('Content-Security-Policy', response)
        self.assertIn("script-src 'self'", response['Content-Security-Policy'])
        self.assertNotIn('<script>', response.content.decode())

    @override_settings(CRON_SECRET='audit-test-cron-secret')
    def test_stock_retention_endpoint_requires_post_and_bearer_secret(self):
        url = reverse('core:stock_retention')
        self.assertEqual(self.client.get(url).status_code, 405)
        self.assertEqual(self.client.post(url).status_code, 401)

    def test_admin_can_open_every_main_page(self):
        receive_stock(self.w, self.w.paper, 5)
        self.login('admin@example.test')
        names = ['core:dashboard', 'core:settings', 'core:audit', 'accounts:user_list', 'accounts:role_list', 'accounts:branch_list',
                 'catalog:item_list', 'catalog:category_list', 'catalog:supplier_list', 'inventory:purchase_list', 'inventory:purchase_create',
                 'inventory:issue_list', 'inventory:issue_create', 'inventory:stock', 'inventory:stock_correct', 'reports:index']
        for name in names:
            r = self.client.get(reverse(name))
            self.assertEqual(r.status_code, 200, name)

    def test_branch_pages_follow_the_module_switch(self):
        self.login('officer@example.test')
        self.assertEqual(self.client.get(reverse('branchops:request_list')).status_code, 403)
        s = Setting.get()
        s.branch_module_enabled = True
        s.save()
        self.assertEqual(self.client.get(reverse('branchops:request_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('branchops:dispatch_list')).status_code, 200)
        self.assertEqual(self.client.get(reverse('branchops:dispatch_create')).status_code, 200)

    def test_branch_user_cannot_open_main_office_admin_pages(self):
        s = Setting.get()
        s.branch_module_enabled = True
        s.save()
        self.login('kandy@example.test')
        self.assertEqual(self.client.get(reverse('accounts:user_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('inventory:purchase_list')).status_code, 403)
        self.assertEqual(self.client.get(reverse('branchops:request_create')).status_code, 200)

    def test_report_csv_has_bom_and_is_attachment(self):
        receive_stock(self.w, self.w.paper, 5)
        self.login('admin@example.test')
        r = self.client.get(reverse('reports:index') + '?type=balances&format=csv')
        self.assertEqual(r.status_code, 200)
        self.assertIn('attachment', r['Content-Disposition'])
        self.assertTrue(r.content.decode('utf-8').startswith('﻿'))

    def test_issue_flow_through_the_form(self):
        receive_stock(self.w, self.w.paper, 5)
        self.login('officer@example.test')
        r = self.client.post(reverse('inventory:issue_create'), {
            'recipient': 'Front desk', 'department': 'Admin', 'issue_date': '2026-01-15', 'purpose': '',
            'line_item': [str(self.w.paper.pk)], 'line_quantity': ['2'], 'line_unit_cost': ['']})
        self.assertEqual(r.status_code, 302)
        r = self.client.post(reverse('inventory:issue_create'), {
            'recipient': 'Front desk', 'department': 'Admin', 'issue_date': '2026-01-15', 'purpose': '',
            'line_item': [str(self.w.paper.pk)], 'line_quantity': ['9'], 'line_unit_cost': ['']})
        self.assertEqual(r.status_code, 200)  # not enough stock: form shown again with the error
