"""Receipt numbers: one place, one running counter per year (REC-26000001, REC-26000002, ...).

The old code used REC-<random 5 digits>, which repeats after a few thousand receipts. New
numbers have 8 digits after REC-, so they can never clash with those older ones.
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import DocumentCounter


def _next(key):
    with transaction.atomic():
        try:
            with transaction.atomic():
                DocumentCounter.objects.get_or_create(key=key)
        except IntegrityError:   # another request created it a moment ago
            pass
        c = DocumentCounter.objects.select_for_update().get(key=key)
        c.value += 1
        c.save(update_fields=['value'])
        return c.value


def next_receipt_number(prefix='REC', series='receipt'):
    yy = timezone.localtime().strftime('%y')
    return f'{prefix}-{yy}{_next(f"{series}-{yy}"):06d}'


def next_deposit_slip_number():
    """Deposit slips have their own series (DEP-26000001) so receipt numbers stay gap-free."""
    return next_receipt_number(prefix='DEP', series='deposit')
