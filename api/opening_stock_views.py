"""
Go-live OPENING STOCK, per store (administrators only).

At go-live every store - the Central Medical Store and each pharmacy - loads what is
physically on its shelf. This is not a purchase: there is no vendor, and it is booked
as OPENING in the stock ledger (never PURCHASE_GRN).

  GET  pharmacy/opening-stock/template/?store=<id>&file_format=xlsx|csv
       every catalogue item with its code, so rows match by code, not by spelling
  POST pharmacy/opening-stock/preview/   file (or rows) + store_id  -> what WOULD happen
  POST pharmacy/opening-stock/apply/     same + pin [+ create_new, allow_possible_duplicates]
  GET  pharmacy/opening-stock/history/

Rules
  * The shelf is SET to the counted quantity (not added to), so re-loading the same
    sheet changes nothing - a sheet uploaded twice can never double the stock.
  * Rows match by Item_Code first, then the exact name. A name that only looks like an
    existing item ("Amlodipine 5mg Tab" vs "AMLODIPINE 5MG") is flagged as a possible
    duplicate instead of silently becoming a second product.
  * Rows with no Counted_Qty are skipped: those items keep their current figure.
  * Batch, expiry and unit cost are optional (no batch -> UNBATCHED lot).
  * All or nothing: if any row has an error, nothing is loaded.
"""
import csv
import io
import re
import uuid
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Count, Max, Min, Sum
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from inventory.models import PharmacyStore, Product, StockMovement, StoreStock
from inventory.permissions import is_admin
from inventory.stock_service import StockError, set_opening, to_pieces

from .product_merge_views import _compatible, _parse

ALIASES = {
    'code': ('item_code', 'code', 'sku', 'product_id', 'product_code', 'isl_code'),
    'name': ('item_name', 'product_name', 'medication_name', 'drug_name', 'name', 'item'),
    'qty': ('counted_qty', 'counted_quantity', 'counted', 'quantity', 'qty', 'current_in_stock', 'stock', 'pieces'),
    'batch': ('batch_number', 'batch', 'lot', 'batch_no'),
    'expiry': ('expiry_date', 'expiry', 'exp_date', 'expiry_dt'),
    'cost': ('unit_cost', 'cost', 'cost_price', 'unit_price'),
    'uom': ('dosage_unit', 'dosage_type_uom', 'uom', 'unit'),
    'category': ('category', 'drug_category'),
}
BLANK = ('', 'nan', 'none', 'null', 'nat')


def _deny(request):
    if not (request.user and request.user.is_authenticated):
        return Response({'error': 'Sign in first.'}, status=status.HTTP_401_UNAUTHORIZED)
    if not is_admin(request.user):
        return Response({'error': 'Only an administrator can load opening stock.', 'code': 'admin_only'},
                        status=status.HTTP_403_FORBIDDEN)
    return None


def _val(row, field):
    for k in ALIASES[field]:
        v = row.get(k)
        if v is not None and str(v).strip().lower() not in BLANK:
            return v
    return None


def _expiry(v):
    if v is None:
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    s = str(v).strip()[:10]
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise StockError(f'Expiry date "{v}" is not a date (use YYYY-MM-DD or DD/MM/YYYY).')


def _money(v):
    if v is None:
        return None
    try:
        d = Decimal(str(v).replace(',', '').replace('₦', '').strip())
    except InvalidOperation:
        raise StockError(f'Unit cost "{v}" is not a number.')
    if d < 0:
        raise StockError('Unit cost cannot be negative.')
    return d


def _read_rows(request):
    f = request.FILES.get('file')
    if f:
        name = f.name.lower()
        if name.endswith('.csv'):
            text = f.read().decode('utf-8-sig', errors='ignore')
            rows = list(csv.DictReader(io.StringIO(text)))
        elif name.endswith(('.xlsx', '.xls')):
            import pandas as pd
            df = pd.read_excel(io.BytesIO(f.read()), sheet_name=0, dtype={'Item_Code': str, 'Batch_Number': str})
            df = df.where(pd.notnull(df), None)
            rows = df.to_dict(orient='records')
        else:
            raise StockError('Upload a CSV (.csv) or Excel (.xlsx) file.')
    else:
        rows = request.data.get('rows') or []
    out = []
    for r in rows:
        if isinstance(r, dict):
            out.append({str(k).strip().lower().replace(' ', '_'): v for k, v in r.items() if k is not None})
    return out


def _analyse(store, raw_rows):
    """Plan the load without changing anything."""
    live = list(Product.objects.filter(merged_into__isnull=True).only(
        'id', 'product_id', 'product_name', 'minimum_UoM', 'category'))
    by_code = {(p.product_id or '').strip().upper(): p for p in live if p.product_id}
    merged_code = {(p.product_id or '').strip().upper(): p.merged_into
                   for p in Product.objects.filter(merged_into__isnull=False).select_related('merged_into')}
    by_name = {}
    for p in live:
        by_name.setdefault(p.product_name.strip().lower(), p)
    by_core = defaultdict(list)
    for p in live:
        core, forms = _parse(p.product_name)
        if core:
            by_core[core].append((p, forms))

    shelf = {s.product_id: s.stock for s in StoreStock.objects.filter(store=store)}

    lines = []                      # one per sheet row
    groups = {}                     # product id or 'new:<name>' -> plan
    for idx, row in enumerate(raw_rows, start=2):      # row 1 is the header in the sheet
        code = str(_val(row, 'code') or '').strip().upper()
        name = str(_val(row, 'name') or '').strip()
        if not code and not name:
            continue
        line = {'row': idx, 'code': code, 'name': name, 'status': None, 'message': ''}
        lines.append(line)
        qty_raw = _val(row, 'qty')
        if qty_raw is None:
            line['status'] = 'skipped'
            line['message'] = 'No counted quantity - this item keeps its current figure.'
            continue
        try:
            qty = to_pieces(qty_raw, 'Counted_Qty', allow_zero=True)
            expiry = _expiry(_val(row, 'expiry'))
            cost = _money(_val(row, 'cost'))
        except StockError as e:
            line['status'], line['message'] = 'error', str(e)
            continue
        batch = str(_val(row, 'batch') or '').strip()
        if batch.endswith('.0') and batch[:-2].isdigit():       # Excel turns 1234 into 1234.0
            batch = batch[:-2]
        line.update({'qty': qty, 'batch': batch or 'UNBATCHED', 'expiry': expiry.isoformat() if expiry else None})

        product, how = None, None
        if code:
            product = by_code.get(code)
            if product is None and code in merged_code:
                product, how = merged_code[code], f'{code} was merged into {merged_code[code].product_id}'
            elif product is None:
                line['status'] = 'error'
                line['message'] = f'Item_Code {code} is not in the catalogue. Clear the code to add it as a new item.'
                continue
            how = how or 'code'
            if name and product.product_name.strip().lower() != name.lower():
                line['note'] = f'Name in the sheet differs from the catalogue ("{product.product_name}") - matched by code.'
        elif name.lower() in by_name:
            product, how = by_name[name.lower()], 'name'

        if product is not None:
            line.update({'product_id': product.id, 'sku': product.product_id, 'product_name': product.product_name, 'matched_by': how})
            g = groups.setdefault(product.id, {'product': product, 'new': False, 'lots': [], 'rows': [], 'cost': None})
        else:
            core, forms = _parse(name)
            similar = [p for p, f in by_core.get(core, []) if _compatible(forms, f)] if core else []
            key = 'new:' + re.sub(r'\s+', ' ', name.lower())
            g = groups.setdefault(key, {'product': None, 'new': True, 'name': name, 'lots': [], 'rows': [], 'cost': None,
                                        'uom': _val(row, 'uom'), 'category': _val(row, 'category'),
                                        'similar': similar})
            line['similar'] = [{'sku': p.product_id, 'name': p.product_name} for p in similar]
        g['lots'].append((batch, qty, expiry))
        g['rows'].append(line)
        if cost is not None:
            g['cost'] = cost

    # Status per item
    summary = defaultdict(int)
    for key, g in groups.items():
        total = sum(q for _, q, _ in g['lots'])
        if g['new']:
            st = 'possible_duplicate' if g['similar'] else 'new'
            before = 0
        else:
            before = shelf.get(g['product'].id, 0)
            st = 'change' if total != before else 'same'
        g['status'], g['total'], g['before'] = st, total, before
        for line in g['rows']:
            line['status'] = st
            line['before'], line['after'] = before, total
            if st == 'possible_duplicate':
                line['message'] = ('Not in the catalogue, but looks like ' + ', '.join(
                    f"{s['sku']} {s['name']}" for s in line['similar'])
                    + '. Put that Item_Code on the row to use it, or allow it as a new item.')
            elif st == 'new':
                line['message'] = 'Not in the catalogue - a new item will be created.'
        summary[st] += 1
    for line in lines:
        if line['status'] in ('skipped', 'error'):
            summary[line['status'] + '_rows'] += 1
    summary['items'] = len(groups)
    summary['pieces_after'] = sum(g['total'] for g in groups.values())
    summary['pieces_change'] = sum(g['total'] - g['before'] for g in groups.values())
    return lines, groups, dict(summary)


class OpeningStockView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request, action):
        denied = _deny(request)
        if denied:
            return denied
        if action == 'template':
            return self._template(request)
        if action == 'history':
            return self._history()
        return Response({'error': 'Unknown action.'}, status=status.HTTP_404_NOT_FOUND)

    def post(self, request, action):
        denied = _deny(request)
        if denied:
            return denied
        if action not in ('preview', 'apply'):
            return Response({'error': 'Unknown action.'}, status=status.HTTP_404_NOT_FOUND)
        store = PharmacyStore.objects.filter(id=request.data.get('store_id')).first()
        if not store:
            return Response({'error': 'Choose the store whose shelf you counted.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            raw = _read_rows(request)
        except StockError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f'Could not read the file: {e}'}, status=status.HTTP_400_BAD_REQUEST)
        if not raw:
            return Response({'error': 'The file has no rows.'}, status=status.HTTP_400_BAD_REQUEST)

        lines, groups, summary = _analyse(store, raw)
        payload = {'store': {'id': store.id, 'name': store.name}, 'summary': summary, 'lines': lines}
        if action == 'preview':
            return Response(payload)
        return self._apply(request, store, lines, groups, summary)

    # ------------------------------------------------------------------ apply
    def _apply(self, request, store, lines, groups, summary):
        def flag(v):
            return str(v).lower() in ('1', 'true', 'yes', 'on')
        pin = str(request.data.get('pin') or '').strip()
        if not pin:
            return Response({'error': 'Enter your PIN to load the opening stock.', 'code': 'pin_required'}, status=400)
        if not request.user.check_pin(pin):
            return Response({'error': 'That PIN is not correct for your account.', 'code': 'pin_invalid'}, status=400)
        errors = [l for l in lines if l['status'] == 'error']
        if errors:
            return Response({'error': f'Nothing was loaded - {len(errors)} row(s) need fixing first.',
                             'summary': summary, 'lines': lines}, status=400)
        if summary.get('possible_duplicate') and not flag(request.data.get('allow_possible_duplicates')):
            return Response({'error': f"{summary['possible_duplicate']} item(s) look like products already in the catalogue. "
                                      'Add their Item_Code, or tick "create them anyway".',
                             'summary': summary, 'lines': lines}, status=400)
        create_new = flag(request.data.get('create_new', 'true'))
        if (summary.get('new') or summary.get('possible_duplicate')) and not create_new:
            return Response({'error': 'Some items are not in the catalogue. Allow new items or remove those rows.',
                             'summary': summary, 'lines': lines}, status=400)

        from inventory.categories import infer_dosage_uom, normalize_category
        from inventory.utils import get_next_isl_sku
        ref = f"OPENING-{(store.code or store.id)}-{timezone.now():%Y%m%d}-{uuid.uuid4().hex[:4].upper()}"[:50]
        changed, created, pieces = 0, 0, 0
        try:
            with transaction.atomic():
                for key, g in groups.items():
                    product = g['product']
                    if g['new']:
                        cat = normalize_category(g.get('category')) if g.get('category') else ''
                        product = Product.objects.create(
                            product_name=g['name'][:200], product_id=get_next_isl_sku(),
                            minimum_UoM=str(g.get('uom') or infer_dosage_uom(cat, g['name']) or '')[:22].lower(),
                            category=cat, price=g['cost'] or Decimal('0'), stock=0,
                            low_stock_threshold=10, staff=request.user,
                        )
                        created += 1
                    elif g['cost']:
                        Product.objects.filter(pk=product.pk).update(price=g['cost'])   # cost price, not selling price
                    _, delta = set_opening(store, product, g['lots'], reference=ref, user=request.user,
                                           notes=f'Opening stock (go-live) for {store.name}')
                    if delta:
                        changed += 1
                        pieces += delta
        except StockError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'success': True,
            'reference': ref,
            'message': (f"Opening stock loaded into {store.name}: {changed} item(s) set"
                        + (f", {created} new item(s) added to the catalogue" if created else '')
                        + f". Unchanged items were left as they were. Reference {ref}."),
            'summary': summary,
        })

    # ------------------------------------------------------------------ template
    def _template(self, request):
        store = PharmacyStore.objects.filter(id=request.query_params.get('store')).first()
        if not store:
            return Response({'error': 'Choose a store.'}, status=status.HTTP_400_BAD_REQUEST)
        fmt = (request.query_params.get('file_format') or 'xlsx').lower()
        shelf = {s.product_id: s.stock for s in StoreStock.objects.filter(store=store)}
        head = ['Item_Code', 'Item_Name', 'Dosage_Unit', 'Category', 'On_System_Now', 'Counted_Qty',
                'Batch_Number', 'Expiry_Date', 'Unit_Cost']
        data = [[p.product_id or '', p.product_name, p.minimum_UoM or '', p.category or '',
                 shelf.get(p.id, 0), '', '', '', '']
                for p in Product.objects.filter(merged_into__isnull=True).order_by('product_name')]
        slug = re.sub(r'[^A-Za-z0-9]+', '-', store.name).strip('-')
        fname = f'opening-stock_{slug}_{date.today():%Y%m%d}'
        if fmt == 'csv':
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(head)
            w.writerows(data)
            resp = HttpResponse(buf.getvalue(), content_type='text/csv')
            resp['Content-Disposition'] = f'attachment; filename="{fname}.csv"'
            return resp
        import openpyxl
        from openpyxl.styles import Alignment, Font, PatternFill
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = 'Opening stock'
        ws.append(head)
        for r in data:
            ws.append(r)
        fill = PatternFill('solid', fgColor='1E3A8A')
        entry = PatternFill('solid', fgColor='FEF3C7')
        for c in ws[1]:
            c.font = Font(bold=True, color='FFFFFF')
            c.fill = fill
            c.alignment = Alignment(horizontal='center')
        for col in ('F', 'G', 'H', 'I'):                    # the columns the store fills in
            ws[f'{col}1'].fill = PatternFill('solid', fgColor='B45309')
        for row in ws.iter_rows(min_row=2, min_col=6, max_col=9):
            for c in row:
                c.fill = entry
        for row in ws.iter_rows(min_row=2, min_col=1, max_col=1):
            for c in row:
                c.number_format = '@'
        widths = {'A': 12, 'B': 48, 'C': 13, 'D': 14, 'E': 15, 'F': 13, 'G': 16, 'H': 13, 'I': 11}
        for k, v in widths.items():
            ws.column_dimensions[k].width = v
        ws.freeze_panes = 'C2'
        info = wb.create_sheet('How to fill')
        for line in [
            [f'Opening stock for: {store.name}'],
            [''],
            ['1. Count what is physically on this store\'s shelf, in PIECES (1 tablet / bottle / vial = 1).'],
            ['2. Type the count in Counted_Qty. Leave it blank for items you did not count - they are not changed.'],
            ['3. Keep Item_Code as it is - it is how the row is matched. Do not retype item names.'],
            ['4. One item in several batches? Copy the row: one row per batch, each with its own count and expiry.'],
            ['5. Batch_Number, Expiry_Date (YYYY-MM-DD or DD/MM/YYYY) and Unit_Cost are optional; no vendor is needed.'],
            ['6. A new item not in the list: add a row with Item_Code empty. It will be checked against similar names.'],
            ['7. The counted figure REPLACES the shelf figure, so uploading the same sheet again changes nothing.'],
        ]:
            info.append(line)
        info.column_dimensions['A'].width = 110
        info['A1'].font = Font(bold=True, size=13)
        buf = io.BytesIO()
        wb.save(buf)
        resp = HttpResponse(buf.getvalue(), content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        resp['Content-Disposition'] = f'attachment; filename="{fname}.xlsx"'
        return resp

    # ------------------------------------------------------------------ history
    def _history(self):
        rows = (StockMovement.objects.filter(movement_type='OPENING')
                .values('reference_number', 'store__name', 'performed_by__fullname', 'performed_by__username')
                .annotate(items=Count('id'), pieces=Sum('quantity'), at=Max('created_date'), first=Min('created_date'))
                .order_by('-at')[:50])
        return Response({'results': [{
            'reference': r['reference_number'], 'store': r['store__name'],
            'by': r['performed_by__fullname'] or r['performed_by__username'],
            'items': r['items'], 'pieces_change': r['pieces'], 'date': r['at'],
        } for r in rows]})
