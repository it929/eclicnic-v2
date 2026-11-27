"""
Is the hospital's data safely backed up? Reads the status files written by
deploy/bin/clinic365-backup (last_status.json) and deploy/bin/clinic365-restore-test
(restore_test.json) and says what, if anything, is wrong. Used by
`manage.py check_backups` (daily: tells Admin/CMD) and the admin API.
"""
import json
import os
from datetime import datetime, timedelta

from django.conf import settings
from django.utils import timezone


def _read(path):
    try:
        with open(path, encoding='utf-8') as fh:
            return json.load(fh)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as e:
        return {'_unreadable': str(e)}


def _when(value):
    try:
        dt = datetime.fromisoformat(str(value))
        return dt if timezone.is_aware(dt) else timezone.make_aware(dt)
    except (TypeError, ValueError):
        return None


def _age_text(td):
    hours = int(td.total_seconds() // 3600)
    return f'{hours // 24} day(s)' if hours >= 48 else f'{hours} hour(s)'


def backup_health(now=None):
    """{'level': 'ok'|'warning'|'danger', 'problems': [...], 'backup': {...}, 'restore_test': {...}}"""
    now = now or timezone.now()
    folder = getattr(settings, 'BACKUP_DIR', '/var/backups/clinic365')
    max_age = timedelta(hours=int(getattr(settings, 'BACKUP_MAX_AGE_HOURS', 26)))
    drill_age = timedelta(days=int(getattr(settings, 'BACKUP_RESTORE_TEST_MAX_DAYS', 8)))
    status = _read(os.path.join(folder, 'last_status.json'))
    drill = _read(os.path.join(folder, 'restore_test.json'))
    problems = []          # (level, text)

    if status is None:
        problems.append(('danger', f'No backup has ever run on this server (nothing in {folder}). '
                                   'Patient and billing records would be lost with the disk.'))
    elif '_unreadable' in status:
        problems.append(('danger', f'The backup status file cannot be read: {status["_unreadable"]}'))
    else:
        finished = _when(status.get('finished_at'))
        if not status.get('ok'):
            problems.append(('danger', f'The last backup FAILED: {status.get("error") or "unknown error"}.'))
        if finished is None or now - finished > max_age:
            ago = _age_text(now - finished) if finished else 'unknown time'
            problems.append(('danger', f'The last backup finished {ago} ago; one should run every night.'))
        offsite = str(status.get('offsite') or '')
        if offsite.upper().startswith('NOT CONFIGURED'):
            problems.append(('warning', 'Backups are kept only on this server. A disk failure, theft or fire would '
                                        'lose them too: set BACKUP_REMOTE or BACKUP_RCLONE (off-site copy).'))
        elif offsite.upper().startswith('FAILED'):
            problems.append(('danger', f'The off-site copy failed ({offsite}).'))
        if str((status.get('media') or {}).get('snapshot') or '').startswith('MISSING'):
            problems.append(('danger', 'Uploaded files (lab results, scans, photos) were not found, so they were not backed up.'))

    if drill is None:
        problems.append(('warning', 'No restore test has been run: nobody has proved the backups can be restored.'))
    elif '_unreadable' in drill:
        problems.append(('warning', f'The restore-test result cannot be read: {drill["_unreadable"]}'))
    else:
        finished = _when(drill.get('finished_at'))
        if not drill.get('ok'):
            problems.append(('danger', f'The last restore test FAILED: {drill.get("error") or "unknown error"}.'))
        elif finished is None or now - finished > drill_age:
            problems.append(('warning', 'The weekly restore test has not run for over a week.'))

    level = 'danger' if any(l == 'danger' for l, _ in problems) else ('warning' if problems else 'ok')
    return {
        'level': level,
        'problems': [{'level': l, 'text': t} for l, t in problems],
        'backup': status if isinstance(status, dict) and '_unreadable' not in status else None,
        'restore_test': drill if isinstance(drill, dict) and '_unreadable' not in drill else None,
        'backup_dir': folder,
        'checked_at': timezone.localtime(now).isoformat(),
    }
