"""
Close antenatal (ANC) journeys that have passed the 52-week limit without an outcome.

    python manage.py end_expired_anc_journeys            # close them
    python manage.py end_expired_anc_journeys --dry-run  # only list what would be closed

A journey normally ends when staff record the outcome (delivery, miscarriage, transfer...). One left
open past 52 weeks is closed with the outcome left as "not recorded" (never guessed), so the
dashboard's active-ANC count and the ANC lists stay accurate. Staff can still record the real outcome.
Scheduled daily by deploy/cron/clinic365-notifications.
"""
from django.core.management.base import BaseCommand

from ANC.models import AntenatalVisit


class Command(BaseCommand):
    help = 'Close ANC journeys that reached 52 weeks without an outcome (outcome left "not recorded").'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='List the journeys that would be closed; change nothing.')

    def handle(self, *args, **opts):
        if opts['dry_run']:
            due = AntenatalVisit.auto_end_all_expired_journeys(dry_run=True)
            for v, weeks in due:
                p = v.patient
                name = f"{getattr(p, 'surname', '')} {getattr(p, 'first_name', '')}".strip()
                self.stdout.write(f"  journey #{v.pk} · {getattr(p, 'hospital_number', '')} {name} · {weeks} weeks")
            self.stdout.write(self.style.WARNING(f'Dry run: {len(due)} journey(s) would be closed.'))
            return
        n = AntenatalVisit.auto_end_all_expired_journeys()
        self.stdout.write(self.style.SUCCESS(f'Closed {n} ANC journey(s) past 52 weeks.'))
