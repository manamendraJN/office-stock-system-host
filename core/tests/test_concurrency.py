"""Real multi-connection tests. These need PostgreSQL: SQLite ignores row locks, so they prove nothing there.

They model several PCs acting at the same instant against one shared database.
"""
import threading
from datetime import date
from unittest import skipUnless

from django.db import close_old_connections, connection
from django.test import TransactionTestCase

from core.errors import Conflict
from core.tests.helpers import fake_request, make_world, receive_stock


def run_parallel(n, fn):
    """Runs fn(i) on n threads released together; each thread has its own database connection."""
    start = threading.Barrier(n)
    results = [None] * n

    def worker(i):
        try:
            start.wait(timeout=15)
            results[i] = ('ok', fn(i))
        except Exception as exc:  # noqa: BLE001
            results[i] = ('err', exc)
        finally:
            close_old_connections()
            connection.close()

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=60)
    return results


@skipUnless(connection.vendor == 'postgresql', 'needs PostgreSQL for real row locking')
class ConcurrentUseTests(TransactionTestCase):
    def setUp(self):
        self.w = make_world()

    def _issue(self, quantity=1):
        from inventory.services import issues

        def go(_i):
            return issues.create_issue(fake_request(self.w.officer), {
                'recipient': 'Desk', 'department': 'Ops', 'issue_date': date.today(), 'purpose': '',
                'lines': [{'item': self.w.paper, 'quantity': quantity}]})
        return go

    def test_last_units_cannot_be_spent_twice(self):
        from inventory.services.stock import get_balance
        receive_stock(self.w, self.w.paper, 5)
        results = run_parallel(12, self._issue())  # twelve PCs each try to issue 1 of 5
        ok = [r for r in results if r[0] == 'ok']
        refused = [r for r in results if r[0] == 'err']
        self.assertEqual(len(ok), 5, results)
        self.assertEqual(len(refused), 7)
        self.assertTrue(all(isinstance(r[1], Conflict) for r in refused), [r[1] for r in refused])
        self.assertEqual(get_balance(self.w.main.pk, self.w.paper.pk), 0)  # never negative

    def test_document_numbers_are_unique_under_contention(self):
        from inventory.models import OfficeIssue
        receive_stock(self.w, self.w.paper, 40)
        results = run_parallel(20, self._issue())
        self.assertTrue(all(r[0] == 'ok' for r in results), [r for r in results if r[0] == 'err'])
        numbers = list(OfficeIssue.objects.values_list('number', flat=True))
        self.assertEqual(len(numbers), 20)
        self.assertEqual(len(set(numbers)), 20, 'duplicate document numbers')

    def test_cancelling_the_same_issue_twice_only_reverses_once(self):
        from inventory.services import issues
        from inventory.services.stock import get_balance
        receive_stock(self.w, self.w.paper, 10)
        issue = self._issue(3)(0)
        self.assertEqual(get_balance(self.w.main.pk, self.w.paper.pk), 7)
        results = run_parallel(6, lambda _i: issues.cancel_issue(fake_request(self.w.officer), issue.pk, 'dup click'))
        self.assertEqual(len([r for r in results if r[0] == 'ok']), 1, results)
        self.assertEqual(get_balance(self.w.main.pk, self.w.paper.pk), 10)  # restored exactly once
