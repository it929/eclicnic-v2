"""
Rules for staff passwords and security PINs, shared by every endpoint that sets them.

A PIN identifies the person signing an action (dispensing, lab/scan results, vitals) on shared
computers, so guessable PINs are refused. The same list is mirrored in the frontend
(frontend/src/utils/validation.js isWeakPin) for an immediate message.
"""

_COMMON = {'2580', '0852', '1004', '2000', '1122', '6969', '1998', '1999'}


def is_weak_pin(pin):
    s = str(pin or '')
    if len(s) != 4 or not s.isdigit():
        return False
    return (len(set(s)) == 1 or s in '0123456789' or s in '9876543210'
            or s[:2] == s[2:] or s in _COMMON)


def pin_error(pin):
    """'' when the PIN is acceptable, else the message to show."""
    s = str(pin or '').strip()
    if not (len(s) == 4 and s.isdigit()):
        return 'PIN must be a 4-digit number.'
    if is_weak_pin(s):
        return 'This PIN is too easy to guess (e.g. 1234, 0000, 1212). Choose a less obvious one.'
    return ''


def password_error(new_password, old_password=None):
    """'' when the password meets the policy, else the message to show."""
    p = str(new_password or '')
    if len(p) < 8:
        return 'Password must be at least 8 characters.'
    if not any(c.isalpha() for c in p) or not any(c.isdigit() for c in p):
        return 'Password must contain both letters and numbers.'
    if old_password and p == old_password:
        return 'New password must be different from the current one.'
    return ''
