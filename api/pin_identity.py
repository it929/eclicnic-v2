"""
Who is doing this? Identify a staff member from their security PIN within one module.

Shared computers (lab benches, pharmacy counters) stay signed in as one account while several
people work at them. For actions that must be attributed to a person (entering lab results), the
PIN, not the signed-in account, says who did it. The PIN is matched only against active staff who
have the module (e.g. "laboratory": the Laboratory role, Admin, CMD), so a PIN from another
department is refused. A PIN shared by two such staff is refused rather than guessed.
Every wrong PIN is logged (api.audit.pin_failed); the digits are never stored.
"""
from rest_framework import status
from rest_framework.response import Response


def _module_holders(module):
    """Active users who may use `module` (a code, or a list/tuple of codes: any of them),
    with a PIN set. Mirrors notification_views._has_module."""
    from inventory.permissions import is_admin
    from users.models import RolePermission, User
    codes = list(module) if isinstance(module, (list, tuple, set)) else [module]
    roles = list(RolePermission.objects.filter(module__code__in=codes).values_list('role_id', 'role__name'))
    role_ids = {rid for rid, _ in roles}
    role_names = {str(n or '').strip().lower() for _, n in roles}
    out = []
    for u in (User.objects.filter(is_active=True).exclude(pin__isnull=True).exclude(pin__in=['', '0'])
              .select_related('department', 'role')):
        if u.role_id:
            ok = u.role_id in role_ids
        else:   # accounts not yet linked to a role use the role named after their department
            ok = str(getattr(u.department, 'department', '') or '').strip().lower() in role_names
        if ok or is_admin(u):
            out.append(u)
    return out


def _refuse(message, code, http=status.HTTP_400_BAD_REQUEST):
    return None, Response({'detail': message, 'error': message, 'code': code}, status=http)


def staff_by_pin(request, module, unit, purpose, pin=None):
    """
    -> (user, None) or (None, error Response).
    `unit` names the team for messages ("Laboratory"); `purpose` completes "to ..." for the audit log.
    """
    if not (request.user and request.user.is_authenticated):
        return _refuse(f'Please sign in to {purpose}.', 'not_signed_in', status.HTTP_401_UNAUTHORIZED)
    raw = str(pin if pin is not None else (request.data.get('pin') or request.data.get('pin_code') or '')).strip()
    if not raw:
        return _refuse(f'Enter the 4-digit PIN of the person who will {purpose}.', 'pin_required')
    if not raw.isdigit():
        return _refuse('A PIN is made of digits only.', 'pin_invalid')

    holders = _module_holders(module)
    me = request.user
    # Common case first: the signed-in person typed their own PIN (one hash check).
    if any(u.pk == me.pk for u in holders) and me.check_pin(raw):
        return me, None
    matches = [u for u in holders if u.pk != me.pk and u.check_pin(raw)]
    if len(matches) == 1:
        return matches[0], None
    if not matches:
        from api.audit import pin_failed
        pin_failed(request, purpose, module=module)
        return _refuse(f'PIN not recognised for any {unit} staff member.', 'pin_invalid')
    return _refuse(f'This PIN is used by {len(matches)} {unit} staff, so the person cannot be identified. '
                   f'Each of them should set a different PIN in Profile Settings.', 'pin_ambiguous')


def display_name(u):
    return (getattr(u, 'fullname', '') or f'{u.first_name} {u.last_name}'.strip() or u.username) if u else ''
