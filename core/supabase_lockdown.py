"""Keeps this app's tables out of reach of Supabase's public Data API (PostgREST / GraphQL).

Why this exists
---------------
This app talks to PostgreSQL directly (Django ORM) and never uses the Data API. But on a Supabase project the
Data API is enabled for the `public` schema, and on projects created before Supabase changed its defaults (and for
tables that already exist, whatever the project age) the `anon` and `authenticated` roles are GRANTed full
SELECT/INSERT/UPDATE/DELETE on every `public` table. Django does not enable Row Level Security. The project's
publishable key is *public by design* (it ships in web pages), so without this lockdown anyone holding it could read
the user table (password hashes) and change any row over plain HTTPS.

What it does (idempotent, safe to run after every migrate)
----------------------------------------------------------
For each table that belongs to this Django project (and Django's own bookkeeping tables) it:
  1. ENABLE ROW LEVEL SECURITY with no policies  -> deny-all for any role that does not bypass RLS;
  2. REVOKE ALL from `anon` and `authenticated`  -> belt and braces (the grant is gone as well as the row access).
The Django connection role (`postgres` on Supabase) owns the tables and has BYPASSRLS, so the app is unaffected.
Only tables Django knows about are touched, so other tables living in the same Supabase project are left alone.
`service_role` is not touched: it is a server-side secret that must never be on a PC and is not used by this app.

Turning the Data API off in the Supabase dashboard is still the strongest control; this is defence in depth.
"""
import logging

log = logging.getLogger(__name__)

API_ROLES = ('anon', 'authenticated')


def _our_tables(connection):
    from django.conf import settings
    names = set(connection.introspection.django_table_names(only_existing=True, include_views=False))
    existing = set(connection.introspection.table_names())
    names.add('django_migrations')
    for conf in getattr(settings, 'CACHES', {}).values():
        if conf.get('BACKEND', '').endswith('DatabaseCache'):
            names.add(conf.get('LOCATION', 'django_cache'))
    return sorted(n for n in names if n in existing)


def lockdown_data_api(connection, app_role=None):
    """Returns {'tables': n, 'rls_enabled': n, 'revoked_roles': [...]} (all zero/empty if not applicable).

    `app_role` (optional restricted role) gets an allow-everything policy on each table, because a
    role that does not own the table and lacks BYPASSRLS would otherwise be denied by the deny-all default."""
    result = {'tables': 0, 'rls_enabled': 0, 'revoked_roles': []}
    if connection.vendor != 'postgresql':
        return result
    q = connection.ops.quote_name
    with connection.cursor() as cur:
        cur.execute('SELECT rolname FROM pg_roles WHERE rolname = ANY(%s)', [list(API_ROLES)])
        roles = sorted(r[0] for r in cur.fetchall())
        if app_role:  # the login may not exist yet (first-ever migrate)
            cur.execute('SELECT 1 FROM pg_roles WHERE rolname = %s', [app_role])
            if cur.fetchone() is None:
                app_role = None
        # Only tables the connected role owns can be altered; on Supabase that is every table Django created.
        cur.execute(
            "SELECT c.relname, c.relrowsecurity FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND c.relkind IN ('r', 'p') AND pg_get_userbyid(c.relowner) = current_user")
        owned = {name: rls for name, rls in cur.fetchall()}
        for table in (t for t in _our_tables(connection) if t in owned):
            result['tables'] += 1
            if not owned[table]:
                cur.execute(f'ALTER TABLE {q(table)} ENABLE ROW LEVEL SECURITY')
                result['rls_enabled'] += 1
            if roles:
                cur.execute(f'REVOKE ALL ON TABLE {q(table)} FROM ' + ', '.join(q(r) for r in roles))
            if app_role:
                cur.execute(f'DROP POLICY IF EXISTS office_stock_app ON {q(table)}')
                cur.execute(f'CREATE POLICY office_stock_app ON {q(table)} FOR ALL TO {q(app_role)} USING (true) WITH CHECK (true)')
        result['revoked_roles'] = roles
    return result
