"""
Immunization Section -> Drugs Record.

The immunization clinic requests vaccines / drugs from the Central Medical Store (CMS),
records how much it received, how many patients it expected and actually served, how much
it used, and returns the unused balance to the CMS at the end of the day.

Stock effects (central store only; the clinic is not a stock-holding store):
    CMS issue (PIN)          -> central StoreStock / batch / Product.stock DEDUCTED, StockMovement TRANSFER_OUT
    CMS receive return (PIN) -> central StoreStock / batch / Product.stock CREDITED,  StockMovement RETURN
"""
import re
import uuid
from datetime import datetime

from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import PharmacyStore, Product, StockMovement, StoreStock, StoreStockBatch
from queue_operations.models import ImmunizationDrugRecord, ImmunizationRecord
from users.models import User

from .immunization_views import verify_staff_pin
from .vaccine_pricing import CATALOG_CODE_PATTERNS

CLINIC_NAME = 'Immunization Clinic'


# ----------------------------------------------------------------------------- helpers
def _central_store():
    return PharmacyStore.objects.filter(is_central=True, is_active=True).first()


def _staff_name(user):
    if not user:
        return ''
    full = getattr(user, 'fullname', '') or ''
    if not full and hasattr(user, 'get_full_name'):
        full = user.get_full_name() or ''
    return (full or getattr(user, 'username', '') or '').strip()


def _current_user(request, data=None):
    if request.user and request.user.is_authenticated:
        return request.user
    sid = (data or {}).get('staff_id') or request.query_params.get('staff_id')
    if sid:
        return User.objects.filter(id=sid, is_active=True).first()
    return None


def _int(value, field, minimum=0):
    try:
        n = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f'{field} must be a whole number.')
    if n < minimum:
        raise ValueError(f'{field} cannot be less than {minimum}.')
    return n


def _parse_date(value):
    if not value:
        return timezone.localdate()
    try:
        return datetime.strptime(str(value)[:10], '%Y-%m-%d').date()
    except ValueError:
        return timezone.localdate()


def _central_batches(store, product):
    today = timezone.localdate()
    rows = []
    for b in StoreStockBatch.objects.filter(store=store, product=product, quantity__gt=0).order_by('expiry_date', 'created_date'):
        rows.append({
            'batch_number': b.batch_number,
            'expiry_date': b.expiry_date.isoformat() if b.expiry_date else None,
            'quantity': b.quantity,
            'expired': bool(b.expiry_date and b.expiry_date <= today),
        })
    return rows


def _system_usage(record_date, product_names):
    """
    Patients who actually received each product on that day, from confirmed immunization records.
    Matches by the priced tariff name, else by the EPI code -> product-name pattern.
    """
    compiled = [(re.compile(c, re.I), re.compile(p, re.I)) for c, p in CATALOG_CODE_PATTERNS]
    recs = ImmunizationRecord.objects.filter(administration_confirmed=True).filter(
        Q(confirmed_at__date=record_date) | Q(confirmed_at__isnull=True, administered_date=record_date)
    ).values_list('tariff_name', 'vaccine_code', 'vaccine_name')
    counts = {n.lower(): 0 for n in product_names}
    for tariff_name, code, vname in recs:
        tn = (tariff_name or '').strip().lower()
        if tn and tn in counts:
            counts[tn] += 1
            continue
        code = (code or '').upper()
        pattern = next((p for c, p in compiled if code and c.search(code)), None)
        for name in product_names:
            if pattern is not None and pattern.search(name):
                counts[name.lower()] += 1
                break
    return counts


def serialize(rec, system_counts=None):
    return {
        'id': rec.id,
        'reference_number': rec.reference_number,
        'record_date': rec.record_date.isoformat(),
        'product_id': rec.product_id,
        'product_name': rec.product_name,
        'product_sku': rec.product.product_id if rec.product_id else '',
        'status': rec.status,
        'status_label': rec.get_status_display(),
        'quantity_requested': rec.quantity_requested,
        'expected_patients': rec.expected_patients,
        'request_notes': rec.request_notes,
        'requested_by_name': rec.requested_by_name,
        'requested_at': rec.requested_at.isoformat() if rec.requested_at else None,
        'quantity_issued': rec.quantity_issued,
        'batch_number': rec.batch_number,
        'expiry_date': rec.expiry_date.isoformat() if rec.expiry_date else None,
        'issued_by_name': rec.issued_by_name,
        'issued_at': rec.issued_at.isoformat() if rec.issued_at else None,
        'store_notes': rec.store_notes,
        'quantity_used': rec.quantity_used,
        'patients_served': rec.patients_served,
        'usage_notes': rec.usage_notes,
        'quantity_returned': rec.quantity_returned,
        'returned_by_name': rec.returned_by_name,
        'returned_at': rec.returned_at.isoformat() if rec.returned_at else None,
        'quantity_return_received': rec.quantity_return_received,
        'return_received_by_name': rec.return_received_by_name,
        'return_received_at': rec.return_received_at.isoformat() if rec.return_received_at else None,
        'on_hand': rec.on_hand,
        'unaccounted': rec.unaccounted,
        'return_shortfall': max(0, rec.quantity_returned - rec.quantity_return_received) if rec.status == 'closed' else 0,
        'system_patients_served': (system_counts or {}).get(rec.product_name.lower()),
    }


# ----------------------------------------------------------------------------- stock moves (central store)
def _deduct_central(store, product, qty, reference, batch_number, user):
    """FEFO deduction from the central store. Returns (batch_used, expiry)."""
    stock = StoreStock.objects.select_for_update().filter(store=store, product=product).first()
    if stock is None or stock.stock < qty:
        have = stock.stock if stock else 0
        raise ValueError(f'Not enough {product.product_name} in {store.name}. Available: {have}, requested: {qty}.')

    batches = list(
        StoreStockBatch.objects.select_for_update()
        .filter(store=store, product=product, quantity__gt=0)
        .order_by('expiry_date', 'created_date')
    )
    today = timezone.localdate()
    if batch_number:
        batches = [b for b in batches if b.batch_number == batch_number]
        if not batches:
            raise ValueError(f'Batch {batch_number} of {product.product_name} has no stock in {store.name}.')
    used_batch, used_expiry = '', None
    if batches:
        remaining = qty
        usable = [b for b in batches if not (b.expiry_date and b.expiry_date <= today)]
        if sum(b.quantity for b in usable) < qty:
            raise ValueError(f'Not enough unexpired {product.product_name} batches in {store.name} to issue {qty}.')
        for b in usable:
            if remaining <= 0:
                break
            take = min(b.quantity, remaining)
            b.quantity -= take
            b.save(update_fields=['quantity', 'updated_date'])
            remaining -= take
            if not used_batch:
                used_batch, used_expiry = b.batch_number, b.expiry_date
            elif b.batch_number != used_batch and ',' not in used_batch:
                used_batch = f'{used_batch}, {b.batch_number}'
    else:
        used_batch, used_expiry = stock.batch_number or '', stock.expiry_date

    stock.stock -= qty
    stock.save(update_fields=['stock', 'updated_date'])
    product.stock = max(0, (product.stock or 0) - qty)
    product.save(update_fields=['stock'])
    StockMovement.objects.create(
        store=store, product=product, movement_type='TRANSFER_OUT', quantity=-qty,
        balance_after=stock.stock, reference_number=reference,
        notes=f'Issued to {CLINIC_NAME}', performed_by=user,
    )
    return used_batch, used_expiry


def _credit_central(store, product, qty, reference, batch_number, expiry, user):
    stock, _ = StoreStock.objects.select_for_update().get_or_create(store=store, product=product, defaults={'stock': 0})
    stock.stock += qty
    stock.save(update_fields=['stock', 'updated_date'])
    first_batch = (batch_number or '').split(',')[0].strip()
    if first_batch:
        b = StoreStockBatch.objects.select_for_update().filter(store=store, product=product, batch_number=first_batch).first()
        if b:
            b.quantity += qty
            b.save(update_fields=['quantity', 'updated_date'])
        else:
            StoreStockBatch.objects.create(
                store_stock=stock, store=store, product=product, batch_number=first_batch,
                expiry_date=expiry, quantity=qty, supplier=f'Return - {CLINIC_NAME}',
            )
    product.stock = (product.stock or 0) + qty
    product.save(update_fields=['stock'])
    StockMovement.objects.create(
        store=store, product=product, movement_type='RETURN', quantity=qty,
        balance_after=stock.stock, reference_number=reference,
        notes=f'Unused stock returned from {CLINIC_NAME}', performed_by=user,
    )


# ----------------------------------------------------------------------------- views
class ImmunizationDrugProductsView(APIView):
    """Drugs / vaccines the clinic can request, with the central store's stock and batches."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        store = _central_store()
        q = (request.query_params.get('q') or '').strip()
        scope = request.query_params.get('scope') or 'vaccine'
        qs = Product.objects.filter(Q(activation_status=1) | Q(activation_status__isnull=True))
        if scope == 'vaccine':
            qs = qs.filter(category='vaccine')
        if q:
            qs = qs.filter(Q(product_name__icontains=q) | Q(product_id__icontains=q))
        qs = qs.order_by('product_name')[:60]
        stock_map = {}
        if store:
            stock_map = dict(StoreStock.objects.filter(store=store, product__in=qs).values_list('product_id', 'stock'))
        items = []
        for p in qs:
            items.append({
                'id': p.id,
                'name': p.product_name,
                'sku': p.product_id or '',
                'category': p.category or '',
                'central_stock': int(stock_map.get(p.id, 0) or 0),
                'batches': _central_batches(store, p) if store else [],
            })
        return Response({
            'central_store': {'id': store.id, 'name': store.name, 'code': store.code} if store else None,
            'products': items,
        })


class ImmunizationDrugRecordListView(APIView):
    """
    GET  ?date=YYYY-MM-DD           -> that day's register + totals
         ?view=store                -> all records waiting on the Central Store (any date)
    POST {product_id, quantity_requested, expected_patients, notes, record_date?} -> new request
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        view = request.query_params.get('view') or 'day'
        day = _parse_date(request.query_params.get('date'))
        qs = ImmunizationDrugRecord.objects.select_related('product')
        if view == 'store':
            qs = qs.filter(status__in=['requested', 'return_pending']).order_by('record_date', 'id')
        else:
            qs = qs.filter(record_date=day).order_by('id')
        records = list(qs)
        system = _system_usage(day, [r.product_name for r in records]) if view != 'store' else {}
        rows = [serialize(r, system) for r in records]
        live = [r for r in records if r.status not in ('rejected', 'cancelled')]
        totals = {
            'requested': sum(r.quantity_requested for r in live),
            'issued': sum(r.quantity_issued for r in live),
            'expected_patients': sum(r.expected_patients for r in live),
            'used': sum(r.quantity_used for r in live),
            'patients_served': sum(r.patients_served for r in live),
            'returned': sum(r.quantity_returned for r in live),
            'return_received': sum(r.quantity_return_received for r in live),
            'on_hand': sum(r.on_hand for r in live),
            'unaccounted': sum(r.unaccounted for r in live),
        }
        pending = {
            'awaiting_issue': ImmunizationDrugRecord.objects.filter(status='requested').count(),
            'awaiting_return_receipt': ImmunizationDrugRecord.objects.filter(status='return_pending').count(),
        }
        store = _central_store()
        return Response({
            'date': day.isoformat(),
            'view': view,
            'central_store': {'id': store.id, 'name': store.name} if store else None,
            'records': rows,
            'totals': totals,
            'pending': pending,
        })

    def post(self, request):
        data = request.data
        store = _central_store()
        if not store:
            return Response({'error': 'No active Central Medical Store is set up. Mark a store as central in Inventory first.'},
                            status=status.HTTP_400_BAD_REQUEST)
        product = Product.objects.filter(id=data.get('product_id')).first()
        if not product:
            return Response({'error': 'Select the drug or vaccine to request.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            qty = _int(data.get('quantity_requested'), 'Quantity requested', 1)
            expected = _int(data.get('expected_patients') or 0, 'Expected patients', 0)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        user = _current_user(request, data)
        day = _parse_date(data.get('record_date'))
        if day > timezone.localdate():
            return Response({'error': 'You cannot request stock for a future date.'}, status=status.HTTP_400_BAD_REQUEST)
        rec = ImmunizationDrugRecord.objects.create(
            reference_number=f"IMD-{day.strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}",
            record_date=day,
            product=product,
            product_name=product.product_name,
            central_store=store,
            quantity_requested=qty,
            expected_patients=expected,
            request_notes=(data.get('notes') or '').strip(),
            requested_by=user,
            requested_by_name=_staff_name(user) or (data.get('requested_by_name') or 'Immunization Nurse'),
        )
        return Response({'message': f'{qty} x {product.product_name} requested from {store.name}.', 'record': serialize(rec)},
                        status=status.HTTP_201_CREATED)


class ImmunizationDrugRecordActionView(APIView):
    """
    POST /immunizations/drug-records/<pk>/<action>/
        issue           CMS, PIN: {quantity_issued, batch_number?, notes?}       -> central stock deducted
        reject          CMS, PIN: {notes}
        cancel          nurse: only while still 'requested'
        usage           nurse: {expected_patients, quantity_used, patients_served, notes}
        return          nurse, PIN: {quantity_returned, quantity_used?, patients_served?, notes?}
        receive-return  CMS, PIN: {quantity_received, notes?}                     -> central stock credited
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request, pk, action):
        data = request.data
        handler = {
            'issue': self._issue,
            'reject': self._reject,
            'cancel': self._cancel,
            'usage': self._usage,
            'return': self._return,
            'receive-return': self._receive_return,
        }.get(action)
        if handler is None:
            return Response({'error': 'Unknown action.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            with transaction.atomic():
                rec = get_object_or_404(ImmunizationDrugRecord.objects.select_for_update(), pk=pk)
                result = handler(request, rec, data)
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return result

    # -- Central store issues the request
    def _issue(self, request, rec, data):
        if rec.status != 'requested':
            raise ValueError(f'{rec.reference_number} is already {rec.get_status_display().lower()}.')
        staff, err = verify_staff_pin(request, data, action='issue stock from the Central Store')
        if err:
            return err
        qty = _int(data.get('quantity_issued', rec.quantity_requested), 'Quantity issued', 1)
        store = rec.central_store or _central_store()
        if not store:
            raise ValueError('No active Central Medical Store is set up.')
        batch, expiry = _deduct_central(store, rec.product, qty, rec.reference_number, (data.get('batch_number') or '').strip(), staff)
        rec.central_store = store
        rec.quantity_issued = qty
        rec.batch_number = batch
        rec.expiry_date = expiry
        rec.issued_by = staff
        rec.issued_by_name = _staff_name(staff)
        rec.issued_at = timezone.now()
        rec.store_notes = (data.get('notes') or '').strip()
        rec.status = 'issued'
        rec.save()
        short = f' ({rec.quantity_requested - qty} short of the request)' if qty < rec.quantity_requested else ''
        return Response({'message': f'{qty} x {rec.product_name} issued to {CLINIC_NAME}{short}. Central store updated.',
                         'record': serialize(rec)})

    def _reject(self, request, rec, data):
        if rec.status != 'requested':
            raise ValueError('Only a request that has not been issued can be rejected.')
        staff, err = verify_staff_pin(request, data, action='reject this request')
        if err:
            return err
        rec.status = 'rejected'
        rec.issued_by = staff
        rec.issued_by_name = _staff_name(staff)
        rec.issued_at = timezone.now()
        rec.store_notes = (data.get('notes') or '').strip() or 'Rejected by Central Store'
        rec.save()
        return Response({'message': f'{rec.reference_number} rejected.', 'record': serialize(rec)})

    def _cancel(self, request, rec, data):
        if rec.status != 'requested':
            raise ValueError('Only a request that the Central Store has not issued can be cancelled.')
        rec.status = 'cancelled'
        rec.save(update_fields=['status', 'updated_at'])
        return Response({'message': f'{rec.reference_number} cancelled.', 'record': serialize(rec)})

    def _apply_usage(self, rec, data):
        if 'expected_patients' in data and data.get('expected_patients') not in (None, ''):
            rec.expected_patients = _int(data.get('expected_patients'), 'Expected patients', 0)
        if 'quantity_used' in data and data.get('quantity_used') not in (None, ''):
            rec.quantity_used = _int(data.get('quantity_used'), 'Quantity used', 0)
        if 'patients_served' in data and data.get('patients_served') not in (None, ''):
            rec.patients_served = _int(data.get('patients_served'), 'Patients who received it', 0)
        if data.get('notes') is not None:
            rec.usage_notes = str(data.get('notes')).strip()
        if rec.quantity_used > rec.quantity_issued:
            raise ValueError(f'Quantity used ({rec.quantity_used}) cannot be more than the {rec.quantity_issued} received from the Central Store.')

    def _usage(self, request, rec, data):
        if rec.status != 'issued':
            raise ValueError('Usage can only be recorded after the Central Store has issued the stock and before it is returned.')
        self._apply_usage(rec, data)
        rec.save()
        return Response({'message': 'Usage saved.', 'record': serialize(rec)})

    # -- Nurse returns the balance (closes directly when nothing comes back)
    def _return(self, request, rec, data):
        if rec.status != 'issued':
            raise ValueError('Only issued stock can be returned.')
        staff, err = verify_staff_pin(request, data, action='return stock to the Central Store')
        if err:
            return err
        self._apply_usage(rec, {k: data.get(k) for k in ('quantity_used', 'patients_served', 'expected_patients') if k in data})
        qty = _int(data.get('quantity_returned', 0), 'Quantity returned', 0)
        balance = rec.quantity_issued - rec.quantity_used
        if qty > balance:
            raise ValueError(f'You can return at most {balance} (received {rec.quantity_issued} - used {rec.quantity_used}).')
        rec.quantity_returned = qty
        rec.returned_by = staff
        rec.returned_by_name = _staff_name(staff)
        rec.returned_at = timezone.now()
        if data.get('notes'):
            rec.usage_notes = (rec.usage_notes + '\n' if rec.usage_notes else '') + str(data.get('notes')).strip()
        if qty == 0:
            rec.status = 'closed'
            msg = 'Day closed. Nothing to return to the Central Store.'
        else:
            rec.status = 'return_pending'
            msg = f'{qty} x {rec.product_name} sent back. Waiting for the Central Store to receive it with their PIN.'
        rec.save()
        return Response({'message': msg, 'record': serialize(rec)})

    # -- Central store confirms the return (PIN) -> central stock credited
    def _receive_return(self, request, rec, data):
        if rec.status != 'return_pending':
            raise ValueError('There is no return waiting to be received on this record.')
        staff, err = verify_staff_pin(request, data, action='receive this return into the Central Store')
        if err:
            return err
        qty = _int(data.get('quantity_received', rec.quantity_returned), 'Quantity received', 0)
        if qty > rec.quantity_returned:
            raise ValueError(f'Received quantity cannot exceed the {rec.quantity_returned} returned.')
        store = rec.central_store or _central_store()
        if not store:
            raise ValueError('No active Central Medical Store is set up.')
        if qty > 0:
            _credit_central(store, rec.product, qty, rec.reference_number, rec.batch_number, rec.expiry_date, staff)
        rec.quantity_return_received = qty
        rec.return_received_by = staff
        rec.return_received_by_name = _staff_name(staff)
        rec.return_received_at = timezone.now()
        if data.get('notes'):
            rec.store_notes = (rec.store_notes + '\n' if rec.store_notes else '') + str(data.get('notes')).strip()
        rec.status = 'closed'
        rec.save()
        short = rec.quantity_returned - qty
        msg = f'{qty} x {rec.product_name} received back into {store.name}. Central stock updated.'
        if short:
            msg += f' {short} short of what the clinic sent - flagged on the record.'
        return Response({'message': msg, 'record': serialize(rec)})
