"""Audit trail helper: one call to record an account/security event in UserActivityLog.

Types (UserActivityLog.ACTIVITY_TYPES): login, logout, failed_login, password_change, password_reset,
pin_created, pin_change, pin_reset, activated, deactivated, profile_update, profile_picture_update,
session_expired, account_accessed, failed_pin. Never raises: an audit failure must not block the action.
"""
import logging

log = logging.getLogger(__name__)


def who(user):
    """Short display name for descriptions, e.g. 'Tunde Laoye (@1638)'."""
    if not user or not getattr(user, 'is_authenticated', False):
        return 'an unknown user'
    name = getattr(user, 'fullname', '') or user.username
    return f'{name} (@{user.username})' if name != user.username else f'@{user.username}'


def pin_failed(request, action, pin_owner=None, **data):
    """
    A wrong security PIN was entered while trying to `action` (e.g. "dispense this medication").
    Logged as failed_pin on the account whose PIN was checked (`pin_owner`, e.g. the doctor signing
    a consultation), or else on the account signed in at that computer. The PIN itself is never stored.
    """
    actor = getattr(request, 'user', None)
    signed_in = actor if actor is not None and getattr(actor, 'is_authenticated', False) else None
    target = pin_owner or signed_in
    if not target:
        return
    desc = f'Wrong PIN entered trying to {action}'
    if pin_owner is not None and signed_in is not None and pin_owner.pk != signed_in.pk:
        desc += f' with the PIN of {who(pin_owner)} (signed in as {who(signed_in)})'
    elif signed_in is not None:
        desc += f' (signed in as {who(signed_in)})'
    audit(target, 'failed_pin', request, desc, action=action, **data)


def audit(user, kind, request, description, **data):
    """Record `kind` for `user` (the account affected), with browser/IP taken from `request`."""
    if not user:
        return
    try:
        from myAdmins.utils import log_user_activity
        actor = getattr(request, 'user', None)
        if actor is not None and getattr(actor, 'is_authenticated', False) and actor.pk != user.pk:
            data.setdefault('by_user_id', actor.pk)
        log_user_activity(user, kind, request, description, data or None)
    except Exception:
        log.exception('audit log failed (%s)', kind)
