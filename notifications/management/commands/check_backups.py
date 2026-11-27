"""
Daily: are backups running, copied off-site, and restorable? If not, tell Admin and CMD in the
notification bell (and by email when BACKUP_ALERT_EMAIL and EMAIL_HOST are set).

    manage.py check_backups            check and notify
    manage.py check_backups --quiet    check only (print, no notifications)

Exit code 1 when something is wrong, so cron logs show it.
"""
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils import timezone

from clinic365.backup_health import backup_health

NOTIFY_DEPARTMENTS = ['Admin', 'CMD']


class Command(BaseCommand):
    help = 'Check that backups ran, were copied off-site and can be restored; warn Admin/CMD if not.'

    def add_arguments(self, parser):
        parser.add_argument('--quiet', action='store_true', help='Print the result only; send no notifications.')

    def handle(self, *args, **opts):
        h = backup_health()
        b = h['backup'] or {}
        if b:
            db = b.get('database') or {}
            self.stdout.write(f"Last backup: {b.get('finished_at')} ok={b.get('ok')} "
                              f"db={db.get('file')} ({db.get('bytes')} bytes) off-site={b.get('offsite')}")
        if h['restore_test']:
            self.stdout.write(f"Last restore test: {h['restore_test'].get('finished_at')} ok={h['restore_test'].get('ok')}")
        if h['level'] == 'ok':
            self.stdout.write(self.style.SUCCESS('Backups OK.'))
            return
        for p in h['problems']:
            self.stdout.write(self.style.ERROR(f"[{p['level']}] {p['text']}"))
        if not opts['quiet']:
            self._tell(h)
        raise SystemExit(1)

    def _tell(self, h):
        today = timezone.localdate().isoformat()
        title = 'Backups need attention' if h['level'] == 'warning' else 'BACKUP PROBLEM: patient data at risk'
        message = ' '.join(p['text'] for p in h['problems'])[:900]
        try:
            from notifications.models import Notification
            from notifications.services import notify_department
            # once a day is enough: skip if today's alert was already sent
            if not Notification.objects.filter(kind='backup_health', ref=f'backup:{today}').exists():
                notify_department(NOTIFY_DEPARTMENTS, kind='backup_health', level=h['level'], icon='fa-database',
                                  title=title, message=message, link='', ref=f'backup:{today}')
        except Exception as e:  # the check itself must still report, even if notifications fail
            self.stderr.write(f'Could not create the notification: {e}')
        to = getattr(settings, 'BACKUP_ALERT_EMAIL', '') or ''
        if to and getattr(settings, 'EMAIL_HOST', ''):
            try:
                from django.core.mail import send_mail
                lines = [f"- [{p['level']}] {p['text']}" for p in h['problems']]
                send_mail(f'[Clinic365] {title}', 'Backup check on ' + today + ':\n\n' + '\n'.join(lines) +
                          f"\n\nBackup folder: {h['backup_dir']}\nSee deploy/README.md, section Backups.",
                          None, [a.strip() for a in to.split(',') if a.strip()])
            except Exception as e:
                self.stderr.write(f'Could not send the email: {e}')
