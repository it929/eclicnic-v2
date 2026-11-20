"""
One way to read a price/rate that came from a form or a spreadsheet cell.

    parse_money('5,000')      -> Decimal('5000.00')
    parse_money('₦1,250.50')  -> Decimal('1250.50')
    parse_money('')           -> Decimal('0.00')     (blank means free / not priced)
    parse_money('-500')       -> MoneyError('cannot be negative')
    parse_money('5k'), 'NaN', 'abc', '12.345', '1e9' -> MoneyError

Callers turn MoneyError into a 400 (forms) or a skipped row with its reason (bulk uploads), instead
of silently saving 0 or a wrong number.
"""
import re
from decimal import Decimal, InvalidOperation

MAX_PRICE = Decimal('100000000')          # ₦100m: anything above is a typo
_CLEAN = re.compile(r'[\s,₦$]|NGN|ngn|N(?=\d)')


class MoneyError(ValueError):
    pass


def parse_money(raw, label='Price', allow_blank=True):
    if raw is None or (isinstance(raw, str) and raw.strip() == ''):
        if allow_blank:
            return Decimal('0.00')
        raise MoneyError(f'{label} is required.')
    if isinstance(raw, bool):
        raise MoneyError(f'{label} must be a number.')
    if isinstance(raw, (int, float, Decimal)):
        s = str(raw)
    else:
        s = _CLEAN.sub('', str(raw).strip())
    if s.startswith('-'):
        raise MoneyError(f'{label} cannot be negative ({raw}).')
    if not re.fullmatch(r'\d+(\.\d+)?', s):
        raise MoneyError(f'{label} "{raw}" is not a valid amount.')
    try:
        val = Decimal(s)
    except InvalidOperation:
        raise MoneyError(f'{label} "{raw}" is not a valid amount.')
    if val != val.quantize(Decimal('0.01')):
        # spreadsheets often store 1500 as 1500.0000001; accept tiny float noise, refuse real extra decimals
        if abs(val - val.quantize(Decimal('0.01'))) > Decimal('0.000001'):
            raise MoneyError(f'{label} "{raw}" has more than 2 decimal places.')
    if val > MAX_PRICE:
        raise MoneyError(f'{label} {raw} is too high. Please check it.')
    return val.quantize(Decimal('0.01'))
