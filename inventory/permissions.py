"""
Who may work in which pharmacy / store.

Every PharmacyStore lists the departments (users.Category) whose staff may operate it
(`PharmacyStore.departments`). A staff member may only view and move stock in the stores
assigned to their own department. Administrators may operate every store.

The Central Medical Store follows the same rule: only departments it is assigned to
(e.g. "Medical Store") may receive, count or issue from it. Requesting stock FROM another
store needs access to your own (requesting) store only.
"""
from rest_framework import status
from rest_framework.response import Response

ADMIN_NAMES = {'admin', 'cmd', 'administrator'}


def _dept(user):
    d = getattr(user, 'department', None)
    return str(getattr(d, 'department', '') or '').strip()


def _role(user):
    r = getattr(user, 'role', None)
    return str(getattr(r, 'name', '') or '').strip()


def _signed_in(user):
    return bool(user and getattr(user, 'is_authenticated', False))


def is_admin(user):
    if not _signed_in(user):
        return False
    if user.is_superuser or user.is_staff:
        return True
    return _dept(user).lower() in ADMIN_NAMES or _role(user).lower() in ADMIN_NAMES


def user_store_ids(user):
    """
    Store ids this user may operate.
    None  -> unrestricted (administrator).
    set() -> none (not signed in, no department, or the department has no store assigned).
    """
    if is_admin(user):
        return None
    if not _signed_in(user) or not getattr(user, 'department_id', None):
        return set()
    from inventory.models import PharmacyStore
    return set(PharmacyStore.objects.filter(departments=user.department_id).values_list('id', flat=True))


def can_use_store(user, store):
    if store is None:
        return False
    ids = user_store_ids(user)
    return ids is None or store.id in ids


def scope_to_user_stores(qs, user, *fields):
    """Filter a queryset to rows touching the user's stores (any of the given store FK fields)."""
    ids = user_store_ids(user)
    if ids is None:
        return qs
    from django.db.models import Q
    cond = Q(pk__in=[])
    for f in fields:
        cond |= Q(**{f'{f}__in': ids})
    return qs.filter(cond).distinct()


def _who(user):
    if not _signed_in(user):
        return 'You are not signed in'
    name = getattr(user, 'fullname', '') or user.get_username()
    return f"{name} ({_dept(user) or 'no department'})"


def store_denied(user, store, action):
    """None if the user may `action` in `store`, else a 403 Response explaining why."""
    if can_use_store(user, store):
        return None
    store_name = getattr(store, 'name', 'this store')
    msg = (f"{_who(user)} cannot {action} in {store_name}: this store is not assigned to your department. "
           f"An administrator can assign it under Inventory > Pharmacies & Sub-Stores.")
    return Response({'error': msg, 'detail': msg, 'code': 'store_not_assigned', 'store_id': getattr(store, 'id', None)},
                    status=status.HTTP_403_FORBIDDEN)


# ---- Central Medical Store (kept for existing callers) ---------------------------------
def _central():
    from inventory.models import PharmacyStore
    return PharmacyStore.objects.filter(is_central=True, is_active=True).first()


def can_operate_central_store(user):
    return can_use_store(user, _central()) if not is_admin(user) else True


def is_store_staff(user):
    """Works in the Central Medical Store (its store is assigned to the user's department), admins excluded."""
    if not _signed_in(user) or is_admin(user):
        return False
    central = _central()
    return bool(central and central.id in user_store_ids(user))


def central_store_denied(user, action):
    """None if allowed, else a 403 Response explaining why."""
    if can_operate_central_store(user):
        return None
    central = _central()
    name = central.name if central else 'the Central Medical Store'
    msg = (f"Only staff of a department assigned to {name}, or an administrator, can {action}. "
           f"{_who(user)} is not authorised.")
    return Response({'error': msg, 'detail': msg, 'code': 'central_store_only'}, status=status.HTTP_403_FORBIDDEN)
