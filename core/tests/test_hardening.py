"""Proxy-aware client address, health endpoint contract, and the Supabase Data API lockdown."""
from types import SimpleNamespace
from unittest import skipUnless
from unittest.mock import patch

from django.core.cache import cache
from django.db import connection
from django.test import SimpleTestCase, TestCase, override_settings

from core.services.audit import client_ip
from core.supabase_lockdown import API_ROLES, _our_tables, lockdown_data_api


def req(remote='10.0.0.9', xff=None):
    meta = {'REMOTE_ADDR': remote}
    if xff is not None:
        meta['HTTP_X_FORWARDED_FOR'] = xff
    return SimpleNamespace(META=meta)


class ClientIpTests(SimpleTestCase):
    def test_direct_connection_ignores_forwarded_header(self):
        # No trusted proxy configured: a client-supplied header must never be believed.
        with override_settings(TRUSTED_PROXY_COUNT=0):
            self.assertEqual(client_ip(req('203.0.113.5', '1.2.3.4')), '203.0.113.5')

    def test_one_proxy_uses_the_address_the_proxy_appended(self):
        with override_settings(TRUSTED_PROXY_COUNT=1):
            self.assertEqual(client_ip(req('10.0.0.9', '198.51.100.7')), '198.51.100.7')

    def test_spoofed_left_entries_are_ignored(self):
        # The attacker sends "X-Forwarded-For: 1.1.1.1"; the proxy appends the real address on the right.
        with override_settings(TRUSTED_PROXY_COUNT=1):
            self.assertEqual(client_ip(req('10.0.0.9', '1.1.1.1, 198.51.100.7')), '198.51.100.7')

    def test_two_proxies(self):
        with override_settings(TRUSTED_PROXY_COUNT=2):
            self.assertEqual(client_ip(req('10.0.0.9', '9.9.9.9, 198.51.100.7, 10.1.1.1')), '198.51.100.7')

    def test_missing_short_or_malformed_header_falls_back_to_remote_addr(self):
        with override_settings(TRUSTED_PROXY_COUNT=2):
            self.assertEqual(client_ip(req('10.0.0.9')), '10.0.0.9')
            self.assertEqual(client_ip(req('10.0.0.9', '198.51.100.7')), '10.0.0.9')
        with override_settings(TRUSTED_PROXY_COUNT=1):
            self.assertEqual(client_ip(req('10.0.0.9', 'not-an-ip')), '10.0.0.9')

    def test_ipv6(self):
        with override_settings(TRUSTED_PROXY_COUNT=1):
            self.assertEqual(client_ip(req('10.0.0.9', '2001:db8::1')), '2001:db8::1')

    def test_no_request(self):
        self.assertEqual(client_ip(None), '')


class SignInThrottlePerUserTests(TestCase):
    """Behind the cloud proxy, one noisy address must not lock everybody else out."""

    def setUp(self):
        cache.clear()

    @override_settings(TRUSTED_PROXY_COUNT=1)
    def test_throttle_is_per_forwarded_address(self):
        for _ in range(31):  # LOGIN_LIMIT is 30 per 15 minutes
            self.client.post('/login/', {'email': 'x@example.test', 'password': 'nope'},
                             HTTP_X_FORWARDED_FOR='198.51.100.1', REMOTE_ADDR='10.0.0.9')
        noisy = self.client.post('/login/', {'email': 'x@example.test', 'password': 'nope'},
                                 HTTP_X_FORWARDED_FOR='198.51.100.1', REMOTE_ADDR='10.0.0.9')
        self.assertContains(noisy, 'Too many sign-in attempts')
        other = self.client.post('/login/', {'email': 'x@example.test', 'password': 'nope'},
                                 HTTP_X_FORWARDED_FOR='198.51.100.2', REMOTE_ADDR='10.0.0.9')
        self.assertNotContains(other, 'Too many sign-in attempts')


class HealthContractTests(TestCase):
    def test_reports_identity_and_status(self):
        r = self.client.get('/health/')
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertEqual(body['app'], 'office-stock')
        self.assertEqual(body['database'], 'connected')
        for key in ('time',):
            self.assertIn(key, body)

    def test_database_down_is_503_and_leaks_nothing(self):
        with patch('core.views.connection') as conn:
            conn.cursor.side_effect = RuntimeError('password authentication failed for user "postgres"')
            r = self.client.get('/health/')
        self.assertEqual(r.status_code, 503)
        self.assertEqual(r.json()['database'], 'disconnected')
        self.assertNotIn('password', r.content.decode().lower())


class LockdownOnNonPostgresTests(TestCase):
    @skipUnless(connection.vendor != 'postgresql', 'SQLite-only expectation')
    def test_is_a_no_op_elsewhere(self):
        self.assertEqual(lockdown_data_api(connection), {'tables': 0, 'rls_enabled': 0, 'revoked_roles': []})


def _api_roles_exist():
    if connection.vendor != 'postgresql':
        return False
    with connection.cursor() as cur:
        cur.execute('SELECT count(*) FROM pg_roles WHERE rolname = ANY(%s)', [list(API_ROLES)])
        return cur.fetchone()[0] == len(API_ROLES)


@skipUnless(connection.vendor == 'postgresql', 'needs PostgreSQL')
class SupabaseLockdownTests(TestCase):
    def _state(self, table):
        with connection.cursor() as cur:
            cur.execute('SELECT relrowsecurity FROM pg_class WHERE relname = %s AND relkind = %s', [table, 'r'])
            rls = cur.fetchone()[0]
            privs = {}
            for role in API_ROLES:
                cur.execute('SELECT EXISTS (SELECT 1 FROM pg_roles WHERE rolname=%s)', [role])
                if cur.fetchone()[0]:
                    cur.execute('SELECT has_table_privilege(%s, %s, %s)', [role, f'public.{table}', 'SELECT'])
                    privs[role] = cur.fetchone()[0]
        return rls, privs

    def test_every_app_table_ends_up_with_rls_and_no_api_grants(self):
        lockdown_data_api(connection)
        tables = _our_tables(connection)
        self.assertGreater(len(tables), 20)
        self.assertIn('accounts_user', tables)
        self.assertIn('django_migrations', tables)
        for table in tables:
            rls, privs = self._state(table)
            self.assertTrue(rls, f'{table} has no row level security')
            self.assertFalse(any(privs.values()), f'{table} is still readable by {privs}')

    def test_is_idempotent_and_repairs_a_regrant(self):
        lockdown_data_api(connection)
        again = lockdown_data_api(connection)
        self.assertEqual(again['rls_enabled'], 0)
        if _api_roles_exist():
            with connection.cursor() as cur:
                cur.execute('GRANT SELECT ON TABLE accounts_user TO anon')
            self.assertTrue(self._state('accounts_user')[1]['anon'])
            lockdown_data_api(connection)
            self.assertFalse(self._state('accounts_user')[1]['anon'])

    def test_the_connection_role_can_still_use_the_tables(self):
        lockdown_data_api(connection)
        from accounts.models import User
        self.assertEqual(User.objects.count(), 0)


@skipUnless(connection.vendor == 'postgresql', 'needs PostgreSQL')
class LockdownMissingAppRoleTests(TestCase):
    def test_unknown_app_role_is_skipped_not_fatal(self):
        # If app_role is specified but does not exist, migrate continues without error.
        out = lockdown_data_api(connection, app_role='no_such_login_yet')
        self.assertGreater(out['tables'], 20)

