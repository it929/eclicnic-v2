"""
Raising notifications.

    notify(users, kind=..., title=..., message=..., link='/inventory/requests', level='warning', actor=user)
    notify_store(store, ...)        everyone whose department is assigned to the store
    notify_department(['Nursing'], ...)

Rules
  * The person who did the action is never notified about it (actor is excluded).
  * Inactive accounts are skipped; each person gets one copy.
  * Raising a notification can never break the action that raised it: errors are logged
    and swallowed inside a savepoint. When the action's transaction rolls back, its
    notifications roll back with it.
"""
import logging

from django.db import transaction

from .models import Notification

logger = logging.getLogger(__name__)


def _ids(users):
    out = []
    for u in users or []:
        uid = getattr(u, 'pk', u)
        if uid and uid not in out:
            out.append(uid)
    return out


def notify(users, *, kind, title, message='', link='', level='info', icon='', actor=None, ref=''):
    """Create one notification per active recipient. Returns the number created."""
    try:
        from users.models import User
        ids = _ids(users)
        actor_id = getattr(actor, 'pk', None)
        if actor_id in ids:
            ids.remove(actor_id)
        if not ids:
            return 0
        ids = list(User.objects.filter(pk__in=ids, is_active=True).values_list('pk', flat=True))
        rows = [Notification(recipient_id=i, kind=kind[:40], title=title[:150], message=(message or '')[:500],
                             link=(link or '')[:200], level=level, icon=icon[:40], actor_id=actor_id, ref=ref[:60])
                for i in ids]
        with transaction.atomic():
            Notification.objects.bulk_create(rows)
        return len(rows)
    except Exception:  # never break the caller
        logger.exception('notify(%s) failed', kind)
        return 0


def store_staff(store):
    """Active staff whose department is assigned to the store (administrators are not included)."""
    from users.models import User
    if not store:
        return []
    return list(User.objects.filter(is_active=True, department__in=store.departments.all()))


def notify_store(store, **kw):
    return notify(store_staff(store), **kw)


def department_staff(names):
    from users.models import User
    from django.db.models import Q
    cond = Q(pk__in=[])
    for n in names:
        cond |= Q(department__department__iexact=n)
    return list(User.objects.filter(cond, is_active=True))


def notify_department(names, **kw):
    return notify(department_staff(names), **kw)
