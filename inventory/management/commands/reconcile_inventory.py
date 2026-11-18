"""
Audit (and optionally repair) the stock ledger.

    python manage.py reconcile_inventory          # report only
    python manage.py reconcile_inventory --apply  # book-keeping repair

The repair never changes how many pieces any store holds.
"""
import json

from django.core.management.base import BaseCommand
from django.db import transaction

from inventory.stock_service import integrity_report, repair


class Command(BaseCommand):
    help = 'Audit the pharmacy stock ledger; --apply realigns lots, Central mirror and ledger to the shelf.'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Apply the book-keeping repair.')

    def handle(self, *args, **opts):
        before = integrity_report(limit=10)
        self.stdout.write('BEFORE: ' + json.dumps(before['summary']))
        if not opts['apply']:
            for k, rows in before['issues'].items():
                for r in rows[:10]:
                    self.stdout.write(f'  {k}: {r}')
            self.stdout.write('Report only. Re-run with --apply to repair.')
            return
        with transaction.atomic():
            fixed = repair()
        self.stdout.write('FIXED: ' + json.dumps(fixed))
        self.stdout.write('AFTER: ' + json.dumps(integrity_report(limit=0)['summary']))
