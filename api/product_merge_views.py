"""
Merge duplicate catalogue products (administrators only).

The same medicine can end up in the catalogue twice - e.g. an early hand-entered item
("Amlodipine 5mg Tablet", ISL-006) and the same drug from the price-list import
("AMLODIPINE 5MG", ISL-057). Stock, prices and reports are then split across two rows.

Merging keeps ONE product and folds each duplicate into it:
  * every store's stock moves across lot by lot (batch numbers and expiry dates kept),
    with a MERGE entry in the stock ledger on both sides - or is written off when the
    duplicate's figures were not a real count;
  * requisitions, transfers and other records that point at the duplicate are re-pointed;
  * sponsor/HMO tariffs move to the kept product (where the kept product already has a
    rate for the same sponsor and plan, that rate wins);
  * the duplicate is deactivated and marked merged_into the kept product. It is never
    deleted: its ledger history stays, and old prescriptions written with its name
    resolve to the kept product when dispensed.

Routes (all under /api/):
  GET  pharmacy/product-merge/suggestions/   likely duplicate groups
  GET  pharmacy/product-merge/search/?q=     products to merge by hand
  GET  pharmacy/product-merge/history/       recent merges
  POST pharmacy/product-merge/merge/         {keep_id, merge_ids, carry_stock, price, pin}
"""
import re
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import (
    Product, PharmacyTariff, ProductMerge, StockMovement, StockRequisitionItem,
    StockTransferItem, StoreStock, StoreStockBatch,
)
from inventory.permissions import is_admin
from inventory.stock_service import StockError, merge_stock

# --------------------------------------------------------------------------- #
# Name matching
# --------------------------------------------------------------------------- #
FORMS = {
    'tab': 'tab', 'tabs': 'tab', 'tablet': 'tab', 'tablets': 'tab', 'tabl': 'tab',
    'cap': 'cap', 'caps': 'cap', 'capsule': 'cap', 'capsules': 'cap',
    'syr': 'liquid', 'syrup': 'liquid', 'susp': 'liquid', 'suspension': 'liquid', 'elixir': 'liquid',
    'inj': 'inj', 'injection': 'inj', 'amp': 'inj', 'ampoule': 'inj', 'amps': 'inj', 'vial': 'inj',
    'cream': 'cream', 'crm': 'cream', 'oint': 'oint', 'ointment': 'oint', 'gel': 'gel',
    'drop': 'drop', 'drops': 'drop', 'sachet': 'sachet', 'sachets': 'sachet',
    'supp': 'supp', 'suppository': 'supp', 'suppositories': 'supp',
    'inhaler': 'inhaler', 'spray': 'spray',
}
UNIT = {'mg': 'mg', 'mcg': 'mcg', 'g': 'g', 'gm': 'g', 'gram': 'g', 'ml': 'ml', 'iu': 'iu', '%': '%'}


def _parse(name):
    """-> (ingredient/strength tokens, dosage forms) e.g. 'Amlodipine 5 mg Tablet' -> ({amlodipine, 5mg}, {tab})."""
    s = str(name or '').lower()
    s = re.sub(r'(\d+(?:\.\d+)?)\s*(mcg|mg|gm|gram|g|ml|iu|%)(?![a-z])',
               lambda m: f" {m.group(1)}{UNIT[m.group(2)]} ", s)
    s = s.replace('/', ' / ')
    toks = [t for t in re.split(r'[^a-z0-9.%]+', s) if t and t != '.']
    forms = {FORMS[t] for t in toks if t in FORMS}
    core = frozenset(t for t in toks if t not in FORMS)
    return core, forms


def _compatible(forms_a, forms_b):
    # A name without a dosage form matches any form; two named forms must overlap
    # (FOLIC ACID TAB and FOLIC ACID SYR are different products).
    return not forms_a or not forms_b or bool(forms_a & forms_b)


# --------------------------------------------------------------------------- #
# Product summaries
# --------------------------------------------------------------------------- #
def _prescription_model():
    try:
        return apps.get_model('queue_operations', 'WrittenPrescriptions')
    except LookupError:
        return None


def _summaries(products):
    ids = [p.id for p in products]
    stock = defaultdict(list)
    for r in (StoreStock.objects.filter(product_id__in=ids, stock__gt=0)
              .select_related('store').order_by('-store__is_central', 'store__name')):
        stock[r.product_id].append({'store': r.store.name, 'is_central': r.store.is_central, 'stock': r.stock})

    req = defaultdict(int)
    for pid in StockRequisitionItem.objects.filter(product_id__in=ids).values_list('product_id', flat=True):
        req[pid] += 1
    trf = defaultdict(int)
    for pid in StockTransferItem.objects.filter(product_id__in=ids).values_list('product_id', flat=True):
        trf[pid] += 1
    mov = defaultdict(int)
    for pid in StockMovement.objects.filter(product_id__in=ids).values_list('product_id', flat=True):
        mov[pid] += 1

    WP = _prescription_model()
    out = []
    for p in products:
        tq = Q(product_name__iexact=p.product_name)
        if p.product_id:
            tq |= Q(product_id=p.product_id)
        tariffs = PharmacyTariff.objects.filter(tq).count()
        rx = WP.objects.filter(item__iexact=p.product_name).count() if WP else 0
        rows = stock.get(p.id, [])
        out.append({
            'id': p.id,
            'sku': p.product_id or '',
            'name': p.product_name,
            'price': str(p.price),
            'category': p.category or '',
            'uom': p.minimum_UoM or '',
            'created_date': p.created_date,
            'total_stock': sum(r['stock'] for r in rows),
            'stores': rows,
            'refs': {
                'prescriptions': rx,
                'tariffs': tariffs,
                'requisitions': req[p.id],
                'transfers': trf[p.id],
                'movements': mov[p.id],
            },
        })
    return out


def _deny(request):
    if not (request.user and request.user.is_authenticated):
        return Response({'error': 'Sign in first.'}, status=status.HTTP_401_UNAUTHORIZED)
    if not is_admin(request.user):
        return Response({'error': 'Only an administrator can merge products.', 'code': 'admin_only'},
                        status=status.HTTP_403_FORBIDDEN)
    return None


# --------------------------------------------------------------------------- #
# Views
# --------------------------------------------------------------------------- #
class ProductMergeView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, action):
        denied = _deny(request)
        if denied:
            return denied
        if action == 'suggestions':
            return self._suggestions(request)
        if action == 'search':
            return self._search(request)
        if action == 'history':
            return self._history(request)
        return Response({'error': 'Unknown action.'}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, action):
        denied = _deny(request)
        if denied:
            return denied
        if action != 'merge':
            return Response({'error': 'Unknown action.'}, status=status.HTTP_404_NOT_FOUND)
        return self._merge(request)

    # ---- GET suggestions
    def _suggestions(self, request):
        live = list(Product.objects.filter(merged_into__isnull=True).only(
            'id', 'product_id', 'product_name', 'price', 'category', 'minimum_UoM', 'created_date'))
        by_core = defaultdict(list)
        for p in live:
            core, forms = _parse(p.product_name)
            if core:
                by_core[core].append((p, forms))

        groups = []
        for core, members in by_core.items():
            if len(members) < 2:
                continue
            clusters = []
            for p, forms in members:
                for c in clusters:
                    if all(_compatible(forms, f) for _, f in c):
                        c.append((p, forms))
                        break
                else:
                    clusters.append([(p, forms)])
            for c in clusters:
                if len(c) > 1:
                    groups.append([p for p, _ in c])

        out = []
        for g in groups:
            items = _summaries(sorted(g, key=lambda p: p.id))
            # Suggest keeping the product that carries the most stock, then the newest
            keep = max(items, key=lambda i: (i['total_stock'], i['created_date']))
            out.append({'key': '-'.join(str(i['id']) for i in items), 'suggested_keep': keep['id'], 'products': items})
        out.sort(key=lambda g: g['products'][0]['name'].lower())
        return Response({'groups': out, 'count': len(out)})

    # ---- GET search
    def _search(self, request):
        q = str(request.query_params.get('q') or '').strip()
        if len(q) < 2:
            return Response({'results': []})
        qs = Product.objects.filter(merged_into__isnull=True).filter(
            Q(product_name__icontains=q) | Q(product_id__iexact=q)).order_by('product_name')[:20]
        return Response({'results': _summaries(list(qs))})

    # ---- GET history
    def _history(self, request):
        rows = ProductMerge.objects.select_related('performed_by')[:50]
        return Response({'results': [{
            'id': m.id,
            'kept_id': m.kept_id, 'kept_sku': m.kept_sku, 'kept_name': m.kept_name,
            'merged_id': m.merged_id, 'merged_sku': m.merged_sku, 'merged_name': m.merged_name,
            'stock_carried': m.stock_carried, 'pieces_moved': m.pieces_moved,
            'price_before': str(m.price_before) if m.price_before is not None else None,
            'price_after': str(m.price_after) if m.price_after is not None else None,
            'details': m.details,
            'performed_by': (m.performed_by.fullname or m.performed_by.username) if m.performed_by else None,
            'created_date': m.created_date,
        } for m in rows]})

    # ---- POST merge
    def _merge(self, request):
        d = request.data
        pin = str(d.get('pin') or '').strip()
        if not pin:
            return Response({'error': 'Enter your PIN to confirm the merge.', 'code': 'pin_required'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not request.user.check_pin(pin):
            return Response({'error': 'That PIN is not correct for your account.', 'code': 'pin_invalid'},
                            status=status.HTTP_400_BAD_REQUEST)
        try:
            keep_id = int(d.get('keep_id'))
            merge_ids = sorted({int(x) for x in (d.get('merge_ids') or [])})
        except (TypeError, ValueError):
            return Response({'error': 'Choose the product to keep and the duplicates to merge into it.'},
                            status=status.HTTP_400_BAD_REQUEST)
        merge_ids = [i for i in merge_ids if i != keep_id]
        if not merge_ids:
            return Response({'error': 'Select at least one duplicate to merge.'}, status=status.HTTP_400_BAD_REQUEST)
        carry = d.get('carry_stock', True)
        carry = not (carry is False or str(carry).lower() in ('false', '0', 'no'))
        price = d.get('price')
        if price not in (None, ''):
            try:
                price = Decimal(str(price).replace(',', '').replace('₦', '').strip())
            except InvalidOperation:
                return Response({'error': 'The selling price is not a valid amount.'}, status=status.HTTP_400_BAD_REQUEST)
            if price < 0:
                return Response({'error': 'The selling price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
        else:
            price = None

        try:
            with transaction.atomic():
                locked = {p.id: p for p in Product.objects.select_for_update().filter(id__in=[keep_id, *merge_ids])}
                keep = locked.get(keep_id)
                if not keep:
                    raise StockError('The product to keep was not found.')
                if keep.merged_into_id:
                    raise StockError(f"{keep.product_name} was itself merged into another product - keep that one instead.")
                dups = []
                for i in merge_ids:
                    p = locked.get(i)
                    if not p:
                        raise StockError(f"Product #{i} was not found.")
                    if p.merged_into_id:
                        raise StockError(f"{p.product_name} ({p.product_id}) is already merged.")
                    dups.append(p)

                price_before = keep.price
                logs, total_pieces = [], 0
                for dup in dups:
                    moved = merge_stock(keep, dup, carry_stock=carry, user=request.user)
                    repointed = self._repoint(keep, dup)
                    t_moved, t_dropped = self._move_tariffs(keep, dup)
                    WP = _prescription_model()
                    rx = WP.objects.filter(item__iexact=dup.product_name).count() if WP else 0
                    Product.objects.filter(merged_into=dup).update(merged_into=keep)
                    Product.objects.filter(pk=dup.pk).update(
                        merged_into=keep, merged_at=timezone.now(), activation_status=0)
                    pieces = sum(moved.values())
                    total_pieces += pieces if carry else 0
                    logs.append(ProductMerge.objects.create(
                        kept=keep, merged=dup,
                        kept_sku=keep.product_id or '', kept_name=keep.product_name,
                        merged_sku=dup.product_id or '', merged_name=dup.product_name,
                        stock_carried=carry, pieces_moved=pieces if carry else 0,
                        price_before=price_before, price_after=price if price is not None else price_before,
                        merged_price=dup.price,
                        details={
                            'stores': moved,
                            'records_repointed': repointed,
                            'tariffs_moved': t_moved,
                            'tariffs_dropped': t_dropped,
                            'prescriptions_by_name': rx,
                        },
                        performed_by=request.user,
                    ))
                if price is not None and price != keep.price:
                    # queryset update: Product.save() regenerates the barcode image
                    Product.objects.filter(pk=keep.pk).update(price=price)
        except StockError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        keep.refresh_from_db()
        names = ', '.join(f"{l.merged_name} ({l.merged_sku})" for l in logs)
        msg = f"Merged {names} into {keep.product_name} ({keep.product_id})."
        if carry and total_pieces:
            msg += f" {total_pieces} pcs moved across."
        elif not carry:
            msg += " The duplicates' stock was written off."
        return Response({
            'success': True,
            'message': msg,
            'kept': _summaries([keep])[0],
            'merges': [l.id for l in logs],
        }, status=status.HTTP_200_OK)

    @staticmethod
    def _repoint(keep, dup):
        """Point every other record at the kept product. Stock rows/lots/ledger are handled by merge_stock."""
        skip = {StoreStock, StoreStockBatch, StockMovement, ProductMerge, Product}
        done = {}
        for model in apps.get_models():
            if model in skip:
                continue
            for f in model._meta.get_fields():
                if getattr(f, 'many_to_one', False) and getattr(f, 'concrete', False) and f.related_model is Product:
                    n = model.objects.filter(**{f.name: dup}).update(**{f.name: keep})
                    if n:
                        done[f"{model._meta.verbose_name_plural}"] = done.get(f"{model._meta.verbose_name_plural}", 0) + n
        return done

    @staticmethod
    def _move_tariffs(keep, dup):
        own = Q(product_name__iexact=dup.product_name)
        if dup.product_id:
            own |= Q(product_id=dup.product_id)
        keep_q = Q(product_name__iexact=keep.product_name)
        if keep.product_id:
            keep_q |= Q(product_id=keep.product_id)
        moved = dropped = 0
        for t in PharmacyTariff.objects.filter(own).exclude(keep_q):
            if PharmacyTariff.objects.filter(keep_q, sponsor_id=t.sponsor_id, plan_id=t.plan_id).exists():
                t.delete()
                dropped += 1
            else:
                PharmacyTariff.objects.filter(pk=t.pk).update(product_id=keep.product_id or '', product_name=keep.product_name)
                moved += 1
        return moved, dropped
