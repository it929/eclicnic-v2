"""
Delete old notifications so the table does not grow forever.

    python manage.py purge_notifications                 # read > 90 days, unread > 365 days
    python manage.py purge_notifications --dry-run       # only report what would be deleted
    python manage.py purge_notifications --read-days 60 --unread-days 180

Read notifications have done their job; unread ones are kept much longer in case a staff
member was away. Deletes in batches so a large first run does not lock the table.
Scheduled daily by deploy/cron/clinic365-notifications.
"""
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from notifications.models import Notification

BATCH = 5000


class Command(BaseCommand):
    help = 'Delete read notifications older than --read-days and unread ones older than --unread-days.'

    def add_arguments(self, parser):
        parser.add_argument('--read-days', type=int, default=90, help='Delete READ notifications older than this (default 90).')
        parser.add_argument('--unread-days', type=int, default=365, help='Delete UNREAD notifications older than this (default 365).')
        parser.add_argument('--dry-run', action='store_true', help='Report counts without deleting anything.')

    def handle(self, *args, **opts):
        read_days, unread_days = opts['read_days'], opts['unread_days']
        if read_days < 1 or unread_days < 1:
            raise CommandError('--read-days and --unread-days must be at least 1.')
        if unread_days < read_days:
            raise CommandError('--unread-days must not be shorter than --read-days.')

        now = timezone.now()
        cond = (Q(read_at__isnull=False, created_at__lt=now - timedelta(days=read_days))
                | Q(read_at__isnull=True, created_at__lt=now - timedelta(days=unread_days)))
        qs = Notification.objects.filter(cond)
        total = qs.count()
        stamp = timezone.localtime(now).strftime('%Y-%m-%d %H:%M')

        if opts['dry_run']:
            self.stdout.write(f'[{stamp}] dry run: {total} notification(s) would be deleted '
                              f'(read > {read_days} days, unread > {unread_days} days).')
            return

        deleted = 0
        while True:
            ids = list(Notification.objects.filter(cond).values_list('pk', flat=True)[:BATCH])
            if not ids:
                break
            n, _ = Notification.objects.filter(pk__in=ids).delete()
            deleted += n
        left = Notification.objects.count()
        self.stdout.write(self.style.SUCCESS(
            f'[{stamp}] deleted {deleted} notification(s) (read > {read_days} days, unread > {unread_days} days); '
            f'{left} kept.'))
