"""
Single source of truth for every stock change in the hospital.

All quantities are WHOLE PIECES (one tablet, one capsule, one bottle, one vial,
one ampoule ... = 1 piece).  Every function here must be called inside
``transaction.atomic()``; rows are locked with ``select_for_update`` so two
people dispensing / dispatching the same drug at the same moment can never
oversell it.

Invariants maintained on every call
-----------------------------------
1. ``StoreStock.stock`` == sum of that row's ``StoreStockBatch.quantity``.
   Stock that arrived without a batch number is held in an ``UNBATCHED`` lot.
2. ``Product.stock`` == stock held in the Central Medical Store(s).
3. Every change writes one ``StockMovement`` row whose ``balance_after`` equals
   the new ``StoreStock.stock`` - the movement ledger always replays to the
   shelf figure.
4. Expired lots are never issued to a patient or another store
   (they can only be written off through a stock count).
"""
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from django.db.models import Sum

from inventory.models import (
    PharmacyStore, Product, StockMovement, StoreStock, StoreStockBatch,
)

UNBATCHED = 'UNBATCHED'


class StockError(ValueError):
    """A business-rule failure that should be shown to the user verbatim."""


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #
def to_pieces(value, label='Quantity', allow_zero=False):
    """Parse a quantity of pieces. Pieces are whole numbers - 2.5 is rejected."""
    if value is None or str(value).strip() == '':
        raise StockError(f'{label} is required.')
    raw = str(value).replace(',', '').strip()
    try:
        num = Decimal(raw)
    except (InvalidOperation, ValueError):
        raise StockError(f'{label} "{value}" is not a number.')
    if num != num.to_integral_value():
        raise StockError(f'{label} must be a whole number of pieces (got {value}).')
    num = int(num)
    if num < 0 or (num == 0 and not allow_zero):
        raise StockError(f'{label} must be {"zero or more" if allow_zero else "at least 1"} piece(s).')
    return num


def _clean_batch(batch_number):
    b = str(batch_number or '').strip()[:50]
    return b or UNBATCHED


def _parse_expiry(value):
    if not value:
        return None
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        raise StockError(f'Expiry date "{value}" is not a valid date (use YYYY-MM-DD).')


def is_expired(expiry, today=None):
    return bool(expiry) and expiry <= (today or date.today())


def _fefo(qs):
    """Earliest expiry first; lots with no expiry date last."""
    rows = list(qs)
    rows.sort(key=lambda b: (b.expiry_date is None, b.expiry_date or date.max, b.created_date))
    return rows


def store_label(store):
    return store.name if store else 'store'


# --------------------------------------------------------------------------- #
# Internal row handling
# --------------------------------------------------------------------------- #
def _lock_row(store, product):
    row, _ = StoreStock.objects.select_for_update().get_or_create(
        store=store, product=product,
        defaults={'stock': 0, 'low_stock_threshold': product.low_stock_threshold or 10},
    )
    return row


def _batch(row, batch_number, expiry=None, supplier=None):
    b, created = StoreStockBatch.objects.select_for_update().get_or_create(
        store=row.store, product=row.product, batch_number=batch_number,
        defaults={'store_stock': row, 'quantity': 0, 'expiry_date': expiry, 'supplier': supplier},
    )
    if b.store_stock_id != row.id:
        b.store_stock = row
    return b


def _heal(row):
    """Make the lots add up to the shelf figure (repairs legacy drift)."""
    batches = list(StoreStockBatch.objects.select_for_update().filter(store=row.store, product=row.product))
    total = sum(b.quantity for b in batches)
    if total == row.stock:
        return
    if total < row.stock:
        b = _batch(row, UNBATCHED)
        b.quantity += row.stock - total
        b.save()
        return
    excess = total - row.stock
    # Remove phantom pieces from UNBATCHED first, then earliest-expiry lots.
    ordered = ([b for b in batches if b.batch_number == UNBATCHED]
               + _fefo(b for b in batches if b.batch_number != UNBATCHED))
    for b in ordered:
        if excess <= 0:
            break
        take = min(b.quantity, excess)
        if take:
            b.quantity -= take
            b.save(update_fields=['quantity', 'updated_date'])
            excess -= take


def _refresh_primary(row):
    """Headline batch/expiry on the stock row = earliest-expiring lot in hand."""
    live = _fefo(StoreStockBatch.objects.filter(store=row.store, product=row.product, quantity__gt=0))
    if live:
        row.batch_number = '' if live[0].batch_number == UNBATCHED else live[0].batch_number
        row.expiry_date = live[0].expiry_date
    else:
        row.batch_number = ''
        row.expiry_date = None


def _mirror_product(product):
    total = StoreStock.objects.filter(store__is_central=True, product=product).aggregate(t=Sum('stock'))['t'] or 0
    # queryset update: Product.save() regenerates the barcode image every call
    Product.objects.filter(pk=product.pk).update(stock=total)
    product.stock = total


def _record(row, movement_type, qty, reference, notes, user):
    return StockMovement.objects.create(
        store=row.store, product=row.product, movement_type=movement_type,
        quantity=qty, balance_after=row.stock,
        reference_number=(reference or '')[:50] or None,
        notes=(notes or '')[:255] or None,
        performed_by=user if (user and getattr(user, 'is_authenticated', False)) else None,
    )


def _save(row, movement_type, qty, reference, notes, user):
    _refresh_primary(row)
    row.save()
    if row.store.is_central:
        _mirror_product(row.product)
    return _record(row, movement_type, qty, reference, notes, user)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def availability(store, product, today=None):
    """{'on_hand', 'usable', 'expired'} in pieces, without locking."""
    today = today or date.today()
    row = StoreStock.objects.filter(store=store, product=product).first()
    if not row:
        return {'on_hand': 0, 'usable': 0, 'expired': 0}
    expired = StoreStockBatch.objects.filter(
        store=store, product=product, quantity__gt=0, expiry_date__lte=today,
    ).aggregate(t=Sum('quantity'))['t'] or 0
    expired = min(expired, row.stock)
    return {'on_hand': row.stock, 'usable': row.stock - expired, 'expired': expired}


def receive(store, product, qty, *, movement_type, reference='', notes='', user=None,
            batch_number='', expiry_date=None, supplier=None):
    """Add pieces to a store (GRN, transfer-in, return)."""
    qty = to_pieces(qty)
    expiry = _parse_expiry(expiry_date)
    row = _lock_row(store, product)
    _heal(row)
    b = _batch(row, _clean_batch(batch_number), expiry, supplier)
    b.quantity += qty
    if expiry:
        b.expiry_date = expiry
    if supplier and not b.supplier:
        b.supplier = supplier[:200]
    b.save()
    row.stock += qty
    _save(row, movement_type, qty, reference, notes, user)
    return row


def issue(store, product, qty, *, movement_type, reference='', notes='', user=None,
          batch_number=None, allow_expired=False):
    """
    Remove pieces from a store, earliest-expiry first (FEFO).
    Returns the lots taken: [{'batch_number', 'expiry_date', 'quantity'}].
    """
    qty = to_pieces(qty)
    today = date.today()
    row = _lock_row(store, product)
    _heal(row)
    lots = StoreStockBatch.objects.select_for_update().filter(store=store, product=product, quantity__gt=0)
    if batch_number:
        lots = lots.filter(batch_number=_clean_batch(batch_number))
    lots = _fefo(lots)
    usable = [b for b in lots if allow_expired or not is_expired(b.expiry_date, today)]
    available = sum(b.quantity for b in usable)
    if available < qty:
        expired = sum(b.quantity for b in lots if is_expired(b.expiry_date, today))
        where = f' (batch {batch_number})' if batch_number else ''
        msg = (f'Not enough {product.product_name} in {store_label(store)}{where}: '
               f'{available} pc(s) available, {qty} needed.')
        if expired and not allow_expired:
            msg += f' {expired} pc(s) on the shelf are EXPIRED and cannot be issued - write them off with a stock count.'
        raise StockError(msg)

    taken, need = [], qty
    for b in usable:
        if need <= 0:
            break
        take = min(b.quantity, need)
        b.quantity -= take
        b.save(update_fields=['quantity', 'updated_date'])
        need -= take
        taken.append({
            'batch_number': '' if b.batch_number == UNBATCHED else b.batch_number,
            'expiry_date': b.expiry_date,
            'quantity': take,
        })
    row.stock -= qty
    _save(row, movement_type, -qty, reference, notes, user)
    return taken


def set_count(store, product, counted, *, reference='', notes='', user=None, batch_number=None):
    """
    Physical stock count: set the shelf to ``counted`` pieces.
    Shortfalls come off the earliest-expiring (incl. expired) lots; surpluses go
    to the named lot, else the current headline lot, else UNBATCHED.
    Returns (row, delta).
    """
    counted = to_pieces(counted, 'Counted quantity', allow_zero=True)
    row = _lock_row(store, product)
    _heal(row)
    delta = counted - row.stock
    if delta == 0:
        return row, 0
    if delta > 0:
        target = _clean_batch(batch_number or row.batch_number)
        b = _batch(row, target)
        b.quantity += delta
        b.save()
    else:
        need = -delta
        lots = StoreStockBatch.objects.select_for_update().filter(store=store, product=product, quantity__gt=0)
        if batch_number:
            named = list(lots.filter(batch_number=_clean_batch(batch_number)))
            rest = _fefo(lots.exclude(batch_number=_clean_batch(batch_number)))
            ordered = named + rest
        else:
            ordered = _fefo(lots)
        for b in ordered:
            if need <= 0:
                break
            take = min(b.quantity, need)
            b.quantity -= take
            b.save(update_fields=['quantity', 'updated_date'])
            need -= take
    row.stock = counted
    _save(row, 'ADJUSTMENT', delta, reference, notes, user)
    return row, delta


# --------------------------------------------------------------------------- #
# Prescription -> catalogue product
# --------------------------------------------------------------------------- #
def _norm(text):
    return re.sub(r'[^a-z0-9]+', ' ', str(text or '').lower()).strip()


def resolve_product(item_name, catalogue=None):
    """
    ``catalogue``: optional preloaded [(id, product_name)] to avoid reloading
    the whole catalogue when resolving many names in one request.

    Map a prescription's free-text drug name to ONE catalogue product.
    Returns (product | None, candidates[list of {id, product_name}]).
    Never guesses between two different products - a wrong match would deduct
    the wrong drug (e.g. FOLIC ACID TAB vs FOLIC ACID SYR).
    """
    name = str(item_name or '').strip()
    if not name:
        return None, []
    exact = Product.objects.filter(product_name__iexact=name).order_by('id')
    if exact.count() == 1:
        return exact.first(), []
    if exact.count() > 1:
        return None, [{'id': p.id, 'product_name': p.product_name} for p in exact]

    target = _norm(name)
    tokens = target.split()
    all_products = catalogue if catalogue is not None else list(Product.objects.values_list('id', 'product_name'))
    same = [(pid, pn) for pid, pn in all_products if _norm(pn) == target]
    if len(same) == 1:
        return Product.objects.get(pk=same[0][0]), []

    containing = [(pid, pn) for pid, pn in all_products
                  if tokens and all(t in _norm(pn).split() for t in tokens)]
    if len(containing) == 1:
        return Product.objects.get(pk=containing[0][0]), []

    pool = containing or [(pid, pn) for pid, pn in all_products
                          if tokens and tokens[0] in _norm(pn).split()]
    return None, [{'id': pid, 'product_name': pn} for pid, pn in pool[:12]]


# --------------------------------------------------------------------------- #
# Integrity report / repair
# --------------------------------------------------------------------------- #
def integrity_report(limit=50):
    """Read-only audit of the invariants above."""
    issues = {'batch_mismatch': [], 'product_mirror': [], 'ledger_mismatch': []}
    rows = StoreStock.objects.select_related('store', 'product')
    batch_sums = {
        (r['store_id'], r['product_id']): r['t']
        for r in StoreStockBatch.objects.values('store_id', 'product_id').annotate(t=Sum('quantity'))
    }
    last_balance = {}
    for m in StockMovement.objects.order_by('created_date', 'id').values('store_id', 'product_id', 'balance_after'):
        last_balance[(m['store_id'], m['product_id'])] = m['balance_after']
    central = {}
    counts = {'rows': 0, 'batch_mismatch': 0, 'ledger_mismatch': 0, 'product_mirror': 0, 'no_ledger': 0}
    for r in rows:
        counts['rows'] += 1
        key = (r.store_id, r.product_id)
        bs = batch_sums.get(key, 0) or 0
        if bs != r.stock:
            counts['batch_mismatch'] += 1
            if len(issues['batch_mismatch']) < limit:
                issues['batch_mismatch'].append({'store': r.store.name, 'product': r.product.product_name,
                                                 'shelf': r.stock, 'lots_total': bs})
        if key in last_balance:
            if last_balance[key] != r.stock:
                counts['ledger_mismatch'] += 1
                if len(issues['ledger_mismatch']) < limit:
                    issues['ledger_mismatch'].append({'store': r.store.name, 'product': r.product.product_name,
                                                      'shelf': r.stock, 'ledger': last_balance[key]})
        elif r.stock:
            counts['no_ledger'] += 1
        if r.store.is_central:
            central[r.product_id] = central.get(r.product_id, 0) + r.stock
    for p in Product.objects.only('id', 'product_name', 'stock'):
        if central.get(p.id, 0) != p.stock:
            counts['product_mirror'] += 1
            if len(issues['product_mirror']) < limit:
                issues['product_mirror'].append({'product': p.product_name, 'product_stock': p.stock,
                                                 'central_store': central.get(p.id, 0)})
    expired_units = StoreStockBatch.objects.filter(quantity__gt=0, expiry_date__lte=date.today()).aggregate(
        t=Sum('quantity'))['t'] or 0
    counts['expired_pieces_on_shelves'] = expired_units
    counts['ok'] = not (counts['batch_mismatch'] or counts['ledger_mismatch'] or counts['product_mirror'])
    return {'summary': counts, 'issues': issues}


def repair(user=None):
    """
    Book-keeping repair - never changes how many pieces any store holds:
      * lots made to add up to the shelf figure (UNBATCHED lot for the remainder)
      * Product.stock re-mirrored from the Central Store
      * shelf rows with stock but no ledger history get an OPENING balance entry,
        and rows whose ledger disagrees get a 0-quantity RECONCILE marker
    Must be called inside transaction.atomic().
    """
    fixed = {'lots': 0, 'mirror': 0, 'opening_entries': 0, 'ledger_markers': 0}
    last_balance = {}
    for m in StockMovement.objects.order_by('created_date', 'id').values('store_id', 'product_id', 'balance_after'):
        last_balance[(m['store_id'], m['product_id'])] = m['balance_after']
    for row in StoreStock.objects.select_for_update().select_related('store', 'product'):
        before = StoreStockBatch.objects.filter(store=row.store, product=row.product).aggregate(t=Sum('quantity'))['t'] or 0
        if before != row.stock:
            _heal(row)
            _refresh_primary(row)
            row.save()
            fixed['lots'] += 1
        key = (row.store_id, row.product_id)
        if key not in last_balance and row.stock:
            _record(row, 'ADJUSTMENT', 0, 'OPENING-BAL',
                    f'Opening balance recorded by ledger reconciliation: {row.stock} pcs on shelf', user)
            fixed['opening_entries'] += 1
        elif key in last_balance and last_balance[key] != row.stock:
            _record(row, 'ADJUSTMENT', 0, 'RECONCILE',
                    f'Ledger re-based to shelf count {row.stock} pcs (previous ledger balance {last_balance[key]})', user)
            fixed['ledger_markers'] += 1
    central = {r['product_id']: r['t'] for r in StoreStock.objects.filter(store__is_central=True)
               .values('product_id').annotate(t=Sum('stock'))}
    for p in Product.objects.only('id', 'stock'):
        want = central.get(p.id, 0)
        if p.stock != want:
            Product.objects.filter(pk=p.pk).update(stock=want)
            fixed['mirror'] += 1
    return fixed
