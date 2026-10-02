import pandas as pd
from django.shortcuts import render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import Http404, HttpResponse, JsonResponse
import os
from django.conf import settings
from django.core.files.storage import FileSystemStorage
from decimal import Decimal
from django.contrib.auth.decorators import login_required
from .decorators import department_required
from django.db.models import Q, F, Sum, ExpressionWrapper, DecimalField
from django.db import transaction
from django.utils import timezone 
from datetime import datetime, timedelta
from django.template.defaultfilters import timesince
from users.templatetags.custom_tags import currency
from .models import Product, Transaction, ProductRequests, Expense, VendorTransaction
from IPD_pharm.models import Drugs, DrugsUpdate
from IPD_pharm2.models import Ipd2Drugs, Ipd2DrugsUpdate
from IPD_pharm3.models import Ipd3Drugs, Ipd3DrugsUpdate
from OPD_pharm.models import OpdDrugs, OpdDrugsUpdate
from OPD_pharm2.models import Opd2Drugs, Opd2DrugsUpdate
from .forms import ProductForm, EditProductForm, ProductForm2, EditVendorForm, VendorsUploadForm
import json
today = timezone.now().date()


def check_expiring_products():
    notification_date = today + timedelta(weeks=2)
    expiring_products = Product.objects.filter(expiry_date__lte = notification_date)
    return expiring_products


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def add_product(request):
    page = 'add-product'

    prod_form = ProductForm()

    expiring_conditions = Q()
    expired_condition = Q(expiry_date__lt=today)
    products = Product.objects.filter(activation_status=1)
    locked = Product.objects.filter(activation_status=0)
    locked_counts = locked.count()
    for prod in products:
        expiry_flag = prod.expiry_flag_in
        number = prod.expiry_flag_in_num
        
        delta_args = {expiry_flag: number}
        try:
            threshold_date = today + timedelta(**delta_args)
        except (TypeError, ValueError):
            continue
        
        expiring_conditions |= Q(
            pk=prod.pk,
            expiry_date__gte=today,
            expiry_date__lte=threshold_date
        )

    # Get all matching products in single queries
    expired_prod = Product.objects.filter(expired_condition)
    expiring_prod = Product.objects.filter(expiring_conditions)
    
    
    # in stock calculation
    in_stock = Transaction.objects.filter(transaction_type = 'PURCHASE', created_date__gte=timezone.now() - timedelta(hours=24))
    in_asset = in_stock.aggregate(total=Sum(ExpressionWrapper(F('price') * F('quantity'),output_field=DecimalField())))['total'] or 0


    # out stock calculation
    out_stock = Transaction.objects.filter(transaction_type = 'SALE', created_date__gte=timezone.now() - timedelta(hours=24))
    out_asset = out_stock.aggregate(total=Sum(ExpressionWrapper(F('price') * F('quantity'),output_field=DecimalField())))['total'] or 0


    expiry_status = 0
    if expired_prod.exists():
        expiry_status = 1

    # Current Stock Balance
    total_revenue = Product.objects.filter().only('price','stock')
    asset = total_revenue.aggregate(total=Sum(ExpressionWrapper(F('price') * F('stock'),output_field=DecimalField())))['total'] or 0

    low_stock_products = Product.objects.filter(stock__lte=F('low_stock_threshold')).count()

    if request.method == 'POST':
        if 'product' in request.POST:
            prod_form = ProductForm(request.POST)
            if prod_form.is_valid():
                try:
                    product = prod_form.save(commit=False)
                    product.staff = request.user
                    product.save()
                    messages.success(request, 'Product Successfully Created!')
                    return redirect('add_product')
                except Exception as e:
                    messages.error(request, f'Error saving product: {str(e)}')
            else:
                # Print form errors to console for debugging
                print(prod_form.errors)
                messages.error(request, 'Please correct the errors below.')
    context = {
        'prod_form': prod_form,
        'page': page,
        'products': products,
        'expiring_prod': expiring_prod,
        'expired_prod': expired_prod,
        'expiry_status':expiry_status,
        'low_stock_products': low_stock_products,
        'locked':locked,
        'locked_counts':locked_counts,
        'asset': asset,
        'in_stock':in_stock,
        'in_asset':in_asset,
        'out_stock':out_stock,
        'out_asset':out_asset
    }
    return render(request, 'inventory/inventory.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def generate_report(request):
    # Default values (last 24 hours)
    time_delta = timedelta(days=1)
    time_period = 'days'
    
    # Check if it's an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
        time_period = request.GET.get('time_period', 'days')
        
        if time_period == 'weeks':
            time_delta = timedelta(weeks=1)
        elif time_period == 'months':
            time_delta = timedelta(days=30)
    
    # Filter transactions
    in_stock = Transaction.objects.filter(
        transaction_type='PURCHASE',
        created_date__gte=timezone.now() - time_delta
    )
    
    # Calculate aggregates
    in_asset = in_stock.aggregate(total=Sum(ExpressionWrapper(F('price') * F('quantity'),output_field=DecimalField())))['total'] or 0

    
    # Prepare data for response
    transactions_data = [{
        'product_names': t.product_names,
        'price': currency(t.price),
        'quantity': t.quantity,
        'created_date': t.created_date.strftime('%Y-%m-%d %H:%M:%S'),
        'timesince': timesince(t.created_date),  
        'id': t.id
    } for t in in_stock]
    
    # Return JSON for AJAX or render template for regular request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'in_asset': currency(in_asset),
            'transactions': transactions_data
        })
    else:
        context = {
            'in_stock': in_stock,
            'in_asset': in_asset
        }
        return render(request, 'inventory/inventory.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def out_stock_report(request):
    # Default values (last 24 hours)
    time_delta = timedelta(days=1)
    time_period = 'days'
    
    # Check if it's an AJAX request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest' and request.method == 'GET':
        time_period = request.GET.get('time_period', 'days')
        
        if time_period == 'weeks':
            time_delta = timedelta(weeks=1)
        elif time_period == 'months':
            time_delta = timedelta(days=30)
    
    # Filter transactions
    out_stock = Transaction.objects.filter(
        transaction_type='SALE',
        created_date__gte=timezone.now() - time_delta
    ) 
    
    # Calculate aggregates
    out_asset = out_stock.aggregate(total=Sum(ExpressionWrapper(F('price') * F('quantity'),output_field=DecimalField())))['total'] or 0

    
    # Prepare data for response
    transactions_data = [{
        'product_names': t.product_names,
        'price': currency(t.price),
        'quantity': t.quantity,
        'created_date': t.created_date.strftime('%Y-%m-%d %H:%M:%S'),
        'timesince': timesince(t.created_date),  
        'id': t.id
    } for t in out_stock]
    
    # Return JSON for AJAX or render template for regular request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'out_asset': currency(out_asset),
            'transactions': transactions_data
        })
    else:
        context = {
            'out_stock': out_stock,
            'out_asset': out_asset
        }
        return render(request, 'inventory/inventory.html', context)
    



# Mapping Excel values to UOM choices (case-insensitive + variations)
UOM_MAP = {
    "ampoule": "ampoules",
    "ampoules": "ampoules",
    "immuno": "immuno",
    "Immuno": "immuno",
    "bottle": "bottles",
    "bottles": "bottles",
    "box": "boxes",
    "boxes": "boxes",
    "carton": "cartons",
    "cartons": "cartons",
    "roll": "rolls",
    "rolls": "rolls",
    "pack": "packs",
    "packs": "packs",
    "piece": "pieces",
    "pieces": "pieces",
    "prefilled syringe": "prefilled_syringe",
    "sachet": "sachets",
    "sachets": "sachets",
    "syringe": "syringes",
    "syringes": "syringes",
    "tin": "tins",
    "tins": "tins",
    "tube": "tubes",
    "tubes": "tubes",
    "vial": "vial",
    "others": "others",
    "each": "each",
    "ml": "mls",
    "mls": "mls",
    "mls (mililiters)": "mls",
    "mgs": "mg",
    "mg": "mg",
    "mcgs": "mcg",
    "mcg": "mcg",
    "g": "g",
    "grams": "g",
    "IUs": "IU",
    "IU": "IU",
    "capsule": "capsules",
    "capsules": "capsules",
    "tablet": "tablets",
    "tablets": "tablets",
    "suppositorys": "suppository",
    "suppositories": "suppository",
    "suppository": "suppository",
    "pessarys": "pessary",
    "pessaries": "pessary",
    "pessary": "pessary",
    "drop": "drops",
    "drops": "drops",
    "puff": "puffs",
    "puffs": "puffs",
    "Puffs (Inhaler)": "puffs",
    "Puffs (Inhalers)": "puffs",
    "Puff (Inhaler)": "puffs",
    "Puff (Inhalers)": "puffs",
    "Puffs Inhaler": "puffs",
    "Puffs Inhalers": "puffs",
    "Puff Inhalers": "puffs",
    "Puff Inhaler": "puffs",

}

def normalize_uom(value):
    if not value:
        return ""
    value = str(value).strip().lower()
    return UOM_MAP.get(value, "")  # return "" if not recognized



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def upload_products_from_excel(request):
    page = 'upload-product'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try: 
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
                # Required fields
                product_id = str(row.get('product_id')).strip() if pd.notna(row.get('product_id')) else ''
                product_name = str(row.get('product_name')).strip() if pd.notna(row.get('product_name')) else ''
                
                raw_uom = str(row.get('minimum_UoM')) if pd.notna(row.get('minimum_UoM')) else ''
                minimum_UoM = normalize_uom(raw_uom)
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{raw_uom}' in row {index+2}. Skipping row."
                    )
                    continue

                # Handle unit parsing & validation conditional on UoM
                raw_unit = row.get('unit')
                unit = None
                
                if pd.notna(raw_unit) and str(raw_unit).strip() != '':
                    try:
                        unit = int(raw_unit)
                        if unit < 0:
                            raise ValueError()
                    except (ValueError, TypeError):
                        messages.warning(request, f"Invalid unit value '{raw_unit}' in row {index+2}. Must be a positive integer. Skipping row.")
                        continue
                else:
                    # Enforce compulsory requirement for 'bottles'
                    if minimum_UoM == 'bottles':
                        messages.warning(
                            request, 
                            f"'unit' is compulsory when minimum_UoM is 'bottles' (Row {index+2}). Skipping row."
                        )
                        continue
                    else:
                        unit = 0  # Default value for non-bottle items if omitted

                # Handle required numeric fields
                try:
                    price = Decimal(row['price']) if pd.notna(row.get('price')) else None
                except:
                    messages.warning(request, f"Invalid price in row {index+2}. Skipping row.")
                    continue

                try:
                    stock = int(row['stock']) if pd.notna(row.get('stock')) else None
                except:
                    messages.warning(request, f"Invalid stock in row {index+2}. Skipping row.")
                    continue

                try:
                    low_stock_threshold = int(row['low_stock_threshold']) if pd.notna(row.get('low_stock_threshold')) else None
                except:
                    messages.warning(request, f"Invalid threshold in row {index+2}. Skipping row.")
                    continue

                # Check required
                if not all([product_id, product_name, price is not None, stock is not None, minimum_UoM, low_stock_threshold is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                product, created = Product.objects.get_or_create(
                    product_id=product_id,
                    product_name=product_name,
                    defaults={
                        'price': price,
                        'stock': stock,
                        'minimum_UoM': minimum_UoM,
                        'unit': unit,
                        'low_stock_threshold': low_stock_threshold,
                    }
                )

                if not created:
                    product.price = price
                    product.stock += stock
                    product.minimum_UoM = minimum_UoM
                    product.unit = unit
                    product.low_stock_threshold = low_stock_threshold

                # Optional fields
                optional_fields = [
                    'description', 'expiry_flag_in', 'expiry_flag_in_num'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        setattr(product, field, row[field])

                # Date fields
                if pd.notna(row.get('manufacturing_date')):
                    product.manufacturing_date = pd.to_datetime(row['manufacturing_date']).date()
                if pd.notna(row.get('expiry_date')):
                    product.expiry_date = pd.to_datetime(row['expiry_date']).date()
                if not pd.notna(row.get('description')):
                    product.description = 'No entry'

                # Staff assignment
                product.staff = request.user
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # Record transaction
                Transaction.objects.create(
                    product=product,
                    product_names=product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    minimum_UoM=minimum_UoM,
                    staff=request.user
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1

            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('upload_products') 

    return render(request, 'inventory/upload_products.html', {'page': page})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def download_import_template(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'products_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=products_import_template.xlsx'
            return response
    raise Http404


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def download_vendors_import_template(request):
    """Serve template Excel file"""
    template_path = os.path.join(settings.BASE_DIR, 'static', 'files', 'vendors_import_template.xlsx')
    if os.path.exists(template_path):
        with open(template_path, 'rb') as fh:
            response = HttpResponse(fh.read(), content_type="application/vnd.ms-excel")
            response['Content-Disposition'] = 'attachment; filename=vendors_import_template.xlsx'
            return response
    raise Http404


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def update_stock(request, product_id):
    product = get_object_or_404(Product, id=product_id)
    sku = product.product_id
    ipd_sku = get_object_or_404(Drugs, product_id=sku)
    ipd2_sku = get_object_or_404(Ipd2Drugs, product_id=sku)
    ipd3_sku = get_object_or_404(Ipd3Drugs, product_id=sku)
    opd_sku = get_object_or_404(OpdDrugs, product_id=sku)
    opd2_sku = get_object_or_404(Opd2Drugs, product_id=sku)
    form = EditProductForm(instance=product)
    expired_prod = Product.objects.filter(expiry_date__lt=today, id=product_id) 
    expiry_status = 0
    if expired_prod.exists():
        expiry_status = 1
    if request.method == 'POST':
        if 'update_transaction' in request.POST:
            quantity = int(request.POST['quantity'])
            transaction_type = request.POST['transaction_type']
            destinations = request.POST['destinations']
            if transaction_type == '--Transaction Type--':
                messages.error(request,'Error: You must select Transaction Type')
            elif destinations == '--Destinations--':
                messages.error(request,'Error: You must select Destinations')
                return redirect('update_stock', product_id=product.id)
            else:
                transaction = Transaction.objects.create(
                product=product,
                quantity=quantity,
                transaction_type=transaction_type,
                destination=destinations,
                staff=request.user
            )
                if transaction_type == 'SALE':
                    if quantity > product.stock:
                        messages.error(request, f'Insufficient Balance: You only have up to {product.stock} Quantity in your stock')
                        return redirect('update_stock', product_id=product.id)
                    else:
                        product.stock -= quantity
                        product.status = product.stock - product.low_stock_threshold
                        if destinations == 'ipd_pharm':
                            ipd_sku.stock +=quantity
                            ipd_sku.save()
                            # update IPD DrugsUpdate
                            DrugsUpdate.objects.create(
                            product=ipd_sku,
                            product_names=product.product_name,
                            quantity=quantity,
                            price=product.price,
                            transaction_type="PURCHASE",
                            destination="inventory",
                            minimum_UoM=product.minimum_UoM,
                            staff=request.user,
                            transaction_id=transaction.id,
                        )
                            messages.success(request, f'{quantity} {product.minimum_UoM} of {product.product_name} Successfully sent to IPD Pharmacy 1')
                        
                        elif destinations == 'ipd2_pharm':
                            ipd2_sku.stock +=quantity
                            ipd2_sku.save()
                            # update IPD2 DrugsUpdate
                            Ipd2DrugsUpdate.objects.create(
                            product=ipd2_sku,
                            product_names=product.product_name,
                            quantity=quantity,
                            price=product.price,
                            transaction_type="PURCHASE",
                            destination="inventory",
                            minimum_UoM=product.minimum_UoM,
                            staff=request.user,
                            transaction_id=transaction.id,
                        )
                            messages.success(request, f'{quantity} {product.minimum_UoM} of {product.product_name} Successfully sent to IPD Pharmacy 2')

                        elif destinations == 'ipd3_pharm':
                            ipd3_sku.stock +=quantity
                            ipd3_sku.save()
                            # update IPD3 DrugsUpdate
                            Ipd3DrugsUpdate.objects.create(
                            product=ipd3_sku,
                            product_names=product.product_name,
                            quantity=quantity,
                            price=product.price,
                            transaction_type="PURCHASE",
                            destination="inventory",
                            minimum_UoM=product.minimum_UoM,
                            staff=request.user,
                            transaction_id=transaction.id,
                        )
                            messages.success(request, f'{quantity} {product.minimum_UoM} of {product.product_name} Successfully sent to IPD Pharmacy 3')
                       
                        elif destinations == 'opd_pharm':
                            opd_sku.stock +=quantity
                            opd_sku.save()
                            # update OPD DrugsUpdate
                            OpdDrugsUpdate.objects.create(
                            product=opd_sku,
                            product_names=product.product_name,
                            quantity=quantity,
                            price=product.price,
                            transaction_type="PURCHASE",
                            destination="inventory",
                            minimum_UoM=product.minimum_UoM,
                            staff=request.user,
                            transaction_id=transaction.id,
                        )
                            messages.success(request, f'{quantity} {product.minimum_UoM} of {product.product_name} Successfully sent to OPD Pharmacy 1')

                        elif destinations == 'opd2_pharm':
                            opd2_sku.stock +=quantity
                            opd2_sku.save()
                            # update OPD2 DrugsUpdate
                            Opd2DrugsUpdate.objects.create(
                            product=opd2_sku,
                            product_names=product.product_name,
                            quantity=quantity,
                            price=product.price,
                            transaction_type="PURCHASE",
                            destination="inventory",
                            minimum_UoM=product.minimum_UoM,
                            staff=request.user,
                            transaction_id=transaction.id,
                        )
                            messages.success(request, f'{quantity} {product.minimum_UoM} of {product.product_name} Successfully sent to OPD Pharmacy 2')
                elif transaction_type == 'PURCHASE':
                    product.stock += quantity
                    product.status = product.stock - product.low_stock_threshold
                product.save()
    
            messages.success(request, 'Product Successfully Updated!')
            return redirect('update_stock', product_id=product.id)
        
        elif 'product_edit' in request.POST:
            form = EditProductForm(request.POST, instance=product)
            if form.is_valid():
                mod_product = form.save(commit=False)
                mod_product.staff = request.user
                mod_product.save()
                messages.success(request, 'Product record updated successfully!')
                return redirect('update_stock', product_id=product.id)  
            else:
                messages.error(request, 'Please correct the error above.')
        elif 'product_delete' in request.POST:
            Drugs.objects.get(product_name = product.product_name).delete()
            Ipd2Drugs.objects.get(product_name = product.product_name).delete()
            Ipd3Drugs.objects.get(product_name = product.product_name).delete()
            OpdDrugs.objects.get(product_name = product.product_name).delete()
            Opd2Drugs.objects.get(product_name = product.product_name).delete()
            product.delete()
            messages.success(request, f'Product {product.product_name} successfully removed from all stores!')
            return redirect('update_stock', product_id=product.id)
        elif 'product_lock' in request.POST:
            Drugs.objects.filter(product_name = product.product_name).update(activation_status=0)
            Ipd2Drugs.objects.filter(product_name = product.product_name).update(activation_status=0)
            Ipd3Drugs.objects.filter(product_name = product.product_name).update(activation_status=0)
            OpdDrugs.objects.filter(product_name = product.product_name).update(activation_status=0)
            Opd2Drugs.objects.filter(product_name = product.product_name).update(activation_status=0)
            product.activation_status=0
            product.save()
            messages.success(request, f'Product {product.product_name} successfully locked from all stores!')
            return redirect('update_stock', product_id=product.id)
        elif 'product_unlock' in request.POST:
            Drugs.objects.filter(product_name = product.product_name).update(activation_status=1)
            Ipd2Drugs.objects.filter(product_name = product.product_name).update(activation_status=1)
            Ipd3Drugs.objects.filter(product_name = product.product_name).update(activation_status=1)
            OpdDrugs.objects.filter(product_name = product.product_name).update(activation_status=1)
            Opd2Drugs.objects.filter(product_name = product.product_name).update(activation_status=1)
            product.activation_status=1
            product.save()
            messages.success(request, f'Product {product.product_name} successfully unlocked across all stores!')
            return redirect('update_stock', product_id=product.id)

    context = {
        'product': product,
        'form':form,
        'expiry_status':expiry_status
    }
    return render(request, 'inventory/transactions.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()     
def barcodeScan(request):
    form = ProductForm2()
    bar_code = request.GET.get('barcode') if request.GET.get('barcode') != None else ''
    bar_code =  bar_code[:13]
    verify_barcode = Product.objects.filter(product_id = bar_code)
    if verify_barcode.count():
        results = Product.objects.filter(product_id__icontains=bar_code)
    else:
        results = 'unavailable'
        form = ProductForm2()
        if request.method == 'POST':
            form = ProductForm2(request.POST, request.FILES)
            if form.is_valid():
                product = form.save(commit=False)
                product.product_id = bar_code
                product.save()
                messages.success(request, 'product successfully added')
                return redirect('scan-barcode')
    if request.GET.get('barcode') == None:
        set_result = 'p'
    else:
        set_result = 'q'
    context = {
        'results':results,
        'bar_code':bar_code,
        'set_result':set_result,
        'form':form
    }
    return render(request, 'inventory/barcode_scanner.html', context)


@login_required(login_url='login')
# @department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def product_search_api2(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    products = Product.objects.filter(product_name__icontains=query, activation_status=1)[:10]

    data = []
    for product in products:
        data.append({
            'id': product.id,
            'label': f"{product.product_name} ({product.product_id})",
            'product_name': product.product_name,
            'price': float(product.price),
            'stock': product.stock,
        })

    return JsonResponse(data, safe=False)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_inventory_export_transaction(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='SALE',
                    destination='ipd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
                # update inventory product
                product.stock = product.stock + int(tx["quantity"])
                product.save()
                # save into Transaction table
                tx = Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    minimum_UoM=tx["minimum_UoM"],
                    transaction_type='PURCHASE',
                    destination='inventory',
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    staff=request.user
                )

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_ipd_export_transaction(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                transaction = Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='SALE',
                    destination='ipd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
                # update inventory product
                product.stock = product.stock - int(tx["quantity"])
                product.status = product.stock - product.low_stock_threshold
                product.save()
                # update IPD stock
                drug_obj, created = Drugs.objects.get_or_create(
                        product_id=product.product_id,
                        defaults={
                            "product_name": product.product_name,
                            "description": product.description,
                            "price": product.price,
                            "stock": 0,
                            "minimum_UoM": product.minimum_UoM,
                            "low_stock_threshold": product.low_stock_threshold,
                            "staff": product.staff,
                            "manufacturing_date": product.manufacturing_date,
                            "expiry_date": product.expiry_date,
                            "expiry_flag_in": product.expiry_flag_in,
                            "expiry_flag_in_num": product.expiry_flag_in_num,
                        }
                    )
                drug_obj.stock = drug_obj.stock + int(tx["quantity"])
                drug_obj.save()

                # update drugupdate table
                DrugsUpdate.objects.create(
                    product=drug_obj,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='PURCHASE',
                    destination='ipd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user,
                    transaction_id=transaction.id,
                )

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_ipd2_export_transaction(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                transaction = Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='SALE',
                    destination='ipd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
                # update inventory product
                product.stock = product.stock - int(tx["quantity"])
                product.status = product.stock - product.low_stock_threshold
                product.save()
                # update IPD stock
                drug_obj, created = Ipd2Drugs.objects.get_or_create(
                        product_id=product.product_id,
                        defaults={
                            "product_name": product.product_name,
                            "description": product.description,
                            "price": product.price,
                            "stock": 0,
                            "minimum_UoM": product.minimum_UoM,
                            "low_stock_threshold": product.low_stock_threshold,
                            "staff": product.staff,
                            "manufacturing_date": product.manufacturing_date,
                            "expiry_date": product.expiry_date,
                            "expiry_flag_in": product.expiry_flag_in,
                            "expiry_flag_in_num": product.expiry_flag_in_num,
                        }
                    )
                drug_obj.stock = drug_obj.stock + int(tx["quantity"])
                drug_obj.save()

                # update drugupdate table
                Ipd2DrugsUpdate.objects.create(
                    product=drug_obj,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='PURCHASE',
                    destination='ipd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user,
                    transaction_id=transaction.id,
                )

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_ipd3_export_transaction(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                transaction = Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='SALE',
                    destination='ipd3_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
                # update inventory product
                product.stock = product.stock - int(tx["quantity"])
                product.status = product.stock - product.low_stock_threshold
                product.save()
                # update IPD stock
                drug_obj, created = Ipd3Drugs.objects.get_or_create(
                        product_id=product.product_id,
                        defaults={
                            "product_name": product.product_name,
                            "description": product.description,
                            "price": product.price,
                            "stock": 0,
                            "minimum_UoM": product.minimum_UoM,
                            "low_stock_threshold": product.low_stock_threshold,
                            "staff": product.staff,
                            "manufacturing_date": product.manufacturing_date,
                            "expiry_date": product.expiry_date,
                            "expiry_flag_in": product.expiry_flag_in,
                            "expiry_flag_in_num": product.expiry_flag_in_num,
                        }
                    )
                drug_obj.stock = drug_obj.stock + int(tx["quantity"])
                drug_obj.save()

                # update drugupdate table
                Ipd3DrugsUpdate.objects.create(
                    product=drug_obj,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='PURCHASE',
                    destination='ipd3_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user,
                    transaction_id=transaction.id,
                )

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_opd_export_transaction(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                transaction = Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='SALE',
                    destination='opd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
                # update inventory product
                product.stock = product.stock - int(tx["quantity"])
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # update OPD stock
                drug_opd, created = OpdDrugs.objects.get_or_create(
                        product_id=product.product_id,
                        defaults={
                            "product_name": product.product_name,
                            "description": product.description,
                            "price": product.price,
                            "stock": 0,
                            "minimum_UoM": product.minimum_UoM,
                            "low_stock_threshold": product.low_stock_threshold,
                            "staff": product.staff,
                            "manufacturing_date": product.manufacturing_date,
                            "expiry_date": product.expiry_date,
                            "expiry_flag_in": product.expiry_flag_in,
                            "expiry_flag_in_num": product.expiry_flag_in_num,
                        }
                    )
                drug_opd.stock = drug_opd.stock + int(tx["quantity"])
                drug_opd.save()

                # update OPD drugupdate table
                OpdDrugsUpdate.objects.create(
                    product=drug_opd,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='PURCHASE',
                    destination='opd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user,
                    transaction_id=transaction.id,
                )

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_opd2_export_transaction(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                transaction = Transaction.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='SALE',
                    destination='opd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
                # update inventory product
                product.stock = product.stock - int(tx["quantity"])
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # update OPD2 stock
                drug_opd2, created = Opd2Drugs.objects.get_or_create(
                        product_id=product.product_id,
                        defaults={
                            "product_name": product.product_name,
                            "description": product.description,
                            "price": product.price,
                            "stock": 0,
                            "minimum_UoM": product.minimum_UoM,
                            "low_stock_threshold": product.low_stock_threshold,
                            "staff": product.staff,
                            "manufacturing_date": product.manufacturing_date,
                            "expiry_date": product.expiry_date,
                            "expiry_flag_in": product.expiry_flag_in,
                            "expiry_flag_in_num": product.expiry_flag_in_num,
                        }
                    )
                drug_opd2.stock = drug_opd2.stock + int(tx["quantity"])
                drug_opd2.save()

                # update OPD2 drugupdate table
                Opd2DrugsUpdate.objects.create(
                    product=drug_opd2,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    transaction_type='PURCHASE',
                    destination='opd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user,
                    transaction_id=transaction.id,
                )

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_imported_product(request):
    # administered_drugs = AdministerDrugs.objects.filter(patient=patient)
    page = 'manage-imports'
    product_imports = Transaction.objects.filter(staff=request.user, transaction_type='PURCHASE',created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        # 'patient': patient,
        'product_imports': product_imports, 
        'page':page,
    }
    return render(request, 'inventory/manage_imports.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_imported_products(request, product_id):
    try:
        import_record = Transaction.objects.get(id=product_id)
        delete = import_record.product  # This is from Drugs model

        #  Update Product inventory stock
        try:
            product_inventory = Product.objects.get(product_id=delete.product_id)
            product_inventory.stock += import_record.quantity
            product_inventory.save()
        except Product.DoesNotExist:
            pass  # If not found in Product, skip but continue cleanup


        #  delete the exported record
        import_record.delete()

        return JsonResponse({'success': True})
    except DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic
def edit_imported_products(request, product_id):
    try:
        import_record = Transaction.objects.get(id=product_id)
        drug = import_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - import_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Product inventory stock
        product_inventory.stock -= diff
        product_inventory.save()

        # update transaction
        import_record.quantity=new_quantity
        import_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_exported_ipd(request):
    page = 'manage-ipd'
    ipd_exports = DrugsUpdate.objects.filter(staff=request.user,created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        # 'patient': patient,
        'ipd_exports': ipd_exports, 
        'page':page,
    }
    return render(request, 'inventory/manage_exports.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_exported_ipd_products(request, product_id):
    try:
        export_record = DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # This is from Drugs model

        #  Update Product inventory stock
        try:
            product_inventory = Product.objects.get(product_id=drug.product_id)
            product_inventory.stock += export_record.quantity
            product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
            product_inventory.save()
        except Product.DoesNotExist:
            pass  # If not found in Product, skip but continue cleanup

        #  Update Drugs stock directly
        drug.stock -= export_record.quantity
        drug.save()

        #  Delete corresponding Transaction record
        # Delete
        Transaction.objects.filter(id=export_record.transaction_id).delete()


        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic
def edit_exported_ipd_products(request, product_id):
    try:
        export_record = DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - export_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Product inventory stock
        product_inventory.stock -= diff
        product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
        product_inventory.save()

        #  Update Drugs stock
        drug.stock += diff
        drug.save()

        #  Update export record (DrugsUpdate)
        export_record.quantity = new_quantity
        export_record.save()

        #  Update matching Transaction
        # Edit
        Transaction.objects.filter(id=export_record.transaction_id).update(quantity=new_quantity)

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_exported_ipd2(request):
    page = 'manage-ipd2'
    ipd2_exports = Ipd2DrugsUpdate.objects.filter(staff=request.user,created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        # 'patient': patient,
        'ipd2_exports': ipd2_exports, 
        'page':page,
    }
    return render(request, 'inventory/manage_exports.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_exported_ipd2_products(request, product_id):
    try:
        export_record = Ipd2DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # This is from Ipd2Drugs model

        #  Update Product inventory stock
        try:
            product_inventory = Product.objects.get(product_id=drug.product_id)
            product_inventory.stock += export_record.quantity
            product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
            product_inventory.save()
        except Product.DoesNotExist:
            pass  # If not found in Product, skip but continue cleanup

        #  Update Ipd2Drugs stock directly
        drug.stock -= export_record.quantity
        drug.save()

        #  Delete corresponding Transaction record
        Transaction.objects.filter(id=export_record.transaction_id).delete()


        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except Ipd2DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic
def edit_exported_ipd2_products(request, product_id):
    try:
        export_record = Ipd2DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # from Ipd2Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - export_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Product inventory stock
        product_inventory.stock -= diff
        product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
        product_inventory.save()

        #  Update Ipd2Drugs stock
        drug.stock += diff
        drug.save()

        #  Update export record (Ipd2DrugsUpdate)
        export_record.quantity = new_quantity
        export_record.save()

        #  Update matching Transaction
        Transaction.objects.filter(id=export_record.transaction_id).update(quantity=new_quantity)

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except Ipd2DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_exported_ipd3(request):
    page = 'manage-ipd3'
    ipd3_exports = Ipd3DrugsUpdate.objects.filter(staff=request.user,created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        # 'patient': patient,
        'ipd3_exports': ipd3_exports, 
        'page':page,
    }
    return render(request, 'inventory/manage_exports.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_exported_ipd3_products(request, product_id):
    try:
        export_record = Ipd3DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # This is from Ipd3Drugs model

        #  Update Product inventory stock
        try:
            product_inventory = Product.objects.get(product_id=drug.product_id)
            product_inventory.stock += export_record.quantity
            product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
            product_inventory.save()
        except Product.DoesNotExist:
            pass  # If not found in Product, skip but continue cleanup

        #  Update Ipd3Drugs stock directly
        drug.stock -= export_record.quantity
        drug.save()

        #  Delete corresponding Transaction record
        Transaction.objects.filter(id=export_record.transaction_id).delete()


        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except Ipd3DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic
def edit_exported_ipd3_products(request, product_id):
    try:
        export_record = Ipd3DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # from Ipd3Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - export_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Product inventory stock
        product_inventory.stock -= diff
        product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
        product_inventory.save()

        #  Update Ipd3Drugs stock
        drug.stock += diff
        drug.save()

        #  Update export record (Ipd3DrugsUpdate)
        export_record.quantity = new_quantity
        export_record.save()

        #  Update matching Transaction
        # Edit
        Transaction.objects.filter(id=export_record.transaction_id).update(quantity=new_quantity)

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except Ipd3DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_exported_opd(request):
    page = 'manage-opd'
    opd_exports = OpdDrugsUpdate.objects.filter(staff=request.user,created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        'opd_exports': opd_exports, 
        'page':page,
    }
    return render(request, 'inventory/manage_exports.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic
def delete_exported_opd_products(request, product_id):
    try:
        export_record = OpdDrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # This is from opdDrugs model

        #  Update Product inventory stock
        try:
            product_inventory = Product.objects.get(product_id=drug.product_id)
            product_inventory.stock += export_record.quantity
            product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
            product_inventory.save()
        except Product.DoesNotExist:
            pass  # If not found in Product, skip but continue cleanup

        #  Update opdDrugs stock directly
        drug.stock -= export_record.quantity
        drug.save()

        #  Delete corresponding Transaction record
        Transaction.objects.filter(id=export_record.transaction_id).delete()

        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_exported_opd2(request):
    page = 'manage-opd2'
    opd2_exports = Opd2DrugsUpdate.objects.filter(staff=request.user,created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        # 'patient': patient,
        'opd2_exports': opd2_exports, 
        'page':page,
    }
    return render(request, 'inventory/manage_exports.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_exported_opd2_products(request, product_id):
    try:
        export_record = Opd2DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # This is from opd2Drugs model

        #  Update Product inventory stock
        try:
            product_inventory = Product.objects.get(product_id=drug.product_id)
            product_inventory.stock += export_record.quantity
            product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
            product_inventory.save()
        except Product.DoesNotExist:
            pass  # If not found in Product, skip but continue cleanup

        #  Update opd2Drugs stock directly
        drug.stock -= export_record.quantity
        drug.save()

        #  Delete corresponding Transaction record
        Transaction.objects.filter(id=export_record.transaction_id).delete()


        #  delete the exported record
        export_record.delete()

        return JsonResponse({'success': True})
    except Opd2DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic
def edit_exported_opd2_products(request, product_id):
    try:
        export_record = Opd2DrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # from opd2Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - export_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Product inventory stock
        product_inventory.stock -= diff
        product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
        product_inventory.save()

        #  Update opd2Drugs stock
        drug.stock += diff
        drug.save()

        #  Update export record (Opd2DrugsUpdate)
        export_record.quantity = new_quantity
        export_record.save()

        #  Update matching Transaction
        # Edit
        Transaction.objects.filter(id=export_record.transaction_id).update(quantity=new_quantity)

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except Opd2DrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic()
def edit_exported_opd_products(request, product_id):
    try:
        export_record = OpdDrugsUpdate.objects.get(id=product_id)
        drug = export_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - export_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)

        #  Update Product inventory stock
        product_inventory.stock -= diff
        product_inventory.status = product_inventory.stock - product_inventory.low_stock_threshold
        product_inventory.save()
        

        #  Update Drugs stock
        drug.stock += diff
        drug.save()

        #  Update export record (DrugsUpdate)
        export_record.quantity = new_quantity
        export_record.save()

        #  Update matching Transaction
        # Edit
        Transaction.objects.filter(id=export_record.transaction_id).update(quantity=new_quantity)

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except OpdDrugsUpdate.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)



# Export to IPD Pharmacy

@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def upload_to_ipdpharm(request):
    page = 'ipd-pharm'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
            # Required fields
                product_id = str(row.get('product_id')).strip() if pd.notna(row.get('product_id')) else ''
                product_name = str(row.get('product_name')).strip() if pd.notna(row.get('product_name')) else ''
                raw_uom = str(row.get('minimum_UoM')) if pd.notna(row.get('minimum_UoM')) else ''
                minimum_UoM = normalize_uom(raw_uom)
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{raw_uom}' in row {index+2}. Skipping row."
                    )
                    continue

                # Handle unit parsing & validation conditional on UoM
                raw_unit = row.get('unit')
                unit = None
                
                if pd.notna(raw_unit) and str(raw_unit).strip() != '':
                    try:
                        unit = int(raw_unit)
                        if unit < 0:
                            raise ValueError()
                    except (ValueError, TypeError):
                        messages.warning(request, f"Invalid unit value '{raw_unit}' in row {index+2}. Must be a positive integer. Skipping row.")
                        continue
                else:
                    # Enforce compulsory requirement for 'bottles'
                    if minimum_UoM == 'bottles':
                        messages.warning(
                            request, 
                            f"'unit' is compulsory when minimum_UoM is 'bottles' (Row {index+2}). Skipping row."
                        )
                        continue
                    else:
                        unit = 0 

                try:
                    price = Decimal(row['price']) if pd.notna(row.get('price')) else None
                except:
                    messages.warning(request, f"Invalid price in row {index+2}. Skipping row.")
                    continue

                try:
                    stock = int(row['stock']) if pd.notna(row.get('stock')) else None
                except:
                    messages.warning(request, f"Invalid stock in row {index+2}. Skipping row.")
                    continue

                try:
                    low_stock_threshold = int(row['low_stock_threshold']) if pd.notna(row.get('low_stock_threshold')) else None
                except:
                    messages.warning(request, f"Invalid threshold in row {index+2}. Skipping row.")
                    continue

                if not all([product_id, product_name, price is not None, stock is not None, minimum_UoM, low_stock_threshold is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                #  Get Product from central inventory
                try:
                    product_obj = Product.objects.get(product_name=product_name)
                except Product.DoesNotExist:
                    messages.warning(request, f"Product '{product_name}' not found in inventory (row {index+2}). Skipping row.")
                    continue

                #  Check stock availability
                if product_obj.stock < stock:
                    messages.warning(
                        request, 
                        f"Insufficient stock for '{product_name}' in row {index+2}. "
                        f"Available: {product_obj.stock}, Requested: {stock}"
                    )
                    continue  # Skip this row

                # Deduct from Product stock
                product_obj.stock -= stock
                product_obj.status = product_obj.stock - product_obj.low_stock_threshold
                product_obj.save()

                # Create/Update Drugs record
                drug, created = Drugs.objects.get_or_create(
                    product_id=product_id,
                    product_name=product_name,
                    defaults={
                        'price': price,
                        'stock': stock,
                        'minimum_UoM': minimum_UoM,
                        'unit':unit,
                        'low_stock_threshold': low_stock_threshold,
                    }
                )

                if not created:
                    drug.price = price
                    drug.stock += stock
                    drug.minimum_UoM = minimum_UoM
                    drug.unit = unit
                    drug.low_stock_threshold = low_stock_threshold

                # Optional fields
                optional_fields = [
                    'description', 'expiry_flag_in', 'expiry_flag_in_num'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        setattr(drug, field, row[field])

                # Save extra fields
                if pd.notna(row.get('manufacturing_date')):
                    drug.manufacturing_date = pd.to_datetime(row['manufacturing_date']).date()
                if pd.notna(row.get('expiry_date')):
                    drug.expiry_date = pd.to_datetime(row['expiry_date']).date()
                if not pd.notna(row.get('description')):
                    drug.description = 'No entry'

                drug.staff = request.user
                drug.save()

                # Create Transaction
                transaction = Transaction.objects.create(
                    product=product_obj,
                    product_names=drug.product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="SALE",
                    destination="ipd_pharm",
                    minimum_UoM=minimum_UoM,
                    staff=request.user
                )

                # Update DrugsUpdate
                DrugsUpdate.objects.create(
                    product=drug,
                    product_names=product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    minimum_UoM=minimum_UoM,
                    staff=request.user,
                    transaction_id=transaction.id,
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1


            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('upload_to_ipd')
    return render(request, 'inventory/export_products.html', {'page': page})


# Export to IPD Pharmacy 2

@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def upload_to_ipd2pharm(request):
    page = 'ipd2-pharm'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
            # Required fields
                product_id = str(row.get('product_id')).strip() if pd.notna(row.get('product_id')) else ''
                product_name = str(row.get('product_name')).strip() if pd.notna(row.get('product_name')) else ''
                raw_uom = str(row.get('minimum_UoM')) if pd.notna(row.get('minimum_UoM')) else ''
                minimum_UoM = normalize_uom(raw_uom)
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{raw_uom}' in row {index+2}. Skipping row."
                    )
                    continue

                # Handle unit parsing & validation conditional on UoM
                raw_unit = row.get('unit')
                unit = None
                
                if pd.notna(raw_unit) and str(raw_unit).strip() != '':
                    try:
                        unit = int(raw_unit)
                        if unit < 0:
                            raise ValueError()
                    except (ValueError, TypeError):
                        messages.warning(request, f"Invalid unit value '{raw_unit}' in row {index+2}. Must be a positive integer. Skipping row.")
                        continue
                else:
                    # Enforce compulsory requirement for 'bottles'
                    if minimum_UoM == 'bottles':
                        messages.warning(
                            request, 
                            f"'unit' is compulsory when minimum_UoM is 'bottles' (Row {index+2}). Skipping row."
                        )
                        continue
                    else:
                        unit = 0 
                try:
                    price = Decimal(row['price']) if pd.notna(row.get('price')) else None
                except:
                    messages.warning(request, f"Invalid price in row {index+2}. Skipping row.")
                    continue

                try:
                    stock = int(row['stock']) if pd.notna(row.get('stock')) else None
                except:
                    messages.warning(request, f"Invalid stock in row {index+2}. Skipping row.")
                    continue

                try:
                    low_stock_threshold = int(row['low_stock_threshold']) if pd.notna(row.get('low_stock_threshold')) else None
                except:
                    messages.warning(request, f"Invalid threshold in row {index+2}. Skipping row.")
                    continue

                if not all([product_id, product_name, price is not None, stock is not None, minimum_UoM, low_stock_threshold is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                #  Get Product from central inventory
                try:
                    product_obj = Product.objects.get(product_name=product_name)
                except Product.DoesNotExist:
                    messages.warning(request, f"Product '{product_name}' not found in inventory (row {index+2}). Skipping row.")
                    continue

                #  Check stock availability
                if product_obj.stock < stock:
                    messages.warning(
                        request, 
                        f"Insufficient stock for '{product_name}' in row {index+2}. "
                        f"Available: {product_obj.stock}, Requested: {stock}"
                    )
                    continue  # Skip this row

                # Deduct from Product stock
                product_obj.stock -= stock
                product_obj.status = product_obj.stock - product_obj.low_stock_threshold
                product_obj.save()

                # Create/Update Ipd2Drugs record
                drug, created = Ipd2Drugs.objects.get_or_create(
                    product_id=product_id,
                    product_name=product_name,
                    defaults={
                        'price': price,
                        'stock': stock,
                        'unit':unit,
                        'minimum_UoM': minimum_UoM,
                        'low_stock_threshold': low_stock_threshold,
                    }
                )

                if not created:
                    drug.price = price
                    drug.stock += stock
                    drug.minimum_UoM = minimum_UoM
                    drug.unit = unit
                    drug.low_stock_threshold = low_stock_threshold

                # Optional fields
                optional_fields = [
                    'description', 'expiry_flag_in', 'expiry_flag_in_num'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        setattr(drug, field, row[field])

                # Save extra fields
                if pd.notna(row.get('manufacturing_date')):
                    drug.manufacturing_date = pd.to_datetime(row['manufacturing_date']).date()
                if pd.notna(row.get('expiry_date')):
                    drug.expiry_date = pd.to_datetime(row['expiry_date']).date()
                if not pd.notna(row.get('description')):
                    drug.description = 'No entry'

                drug.staff = request.user
                drug.save()

                # Create Transaction
                transaction = Transaction.objects.create(
                    product=product_obj,
                    product_names=drug.product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="SALE",
                    destination="ipd2_pharm",
                    minimum_UoM=minimum_UoM,
                    staff=request.user
                )

                # Update Ipd2DrugsUpdate
                Ipd2DrugsUpdate.objects.create(
                    product=drug,
                    product_names=product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    minimum_UoM=minimum_UoM,
                    staff=request.user,
                    transaction_id=transaction.id,
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1


            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('upload_to_ipd2')
    return render(request, 'inventory/export_products.html', {'page': page})


# Export to IPD Pharmacy 3

@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def upload_to_ipd3pharm(request):
    page = 'ipd3-pharm'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
            # Required fields
                product_id = str(row.get('product_id')).strip() if pd.notna(row.get('product_id')) else ''
                product_name = str(row.get('product_name')).strip() if pd.notna(row.get('product_name')) else ''
                raw_uom = str(row.get('minimum_UoM')) if pd.notna(row.get('minimum_UoM')) else ''
                minimum_UoM = normalize_uom(raw_uom)
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{raw_uom}' in row {index+2}. Skipping row."
                    )
                    continue

                # Handle unit parsing & validation conditional on UoM
                raw_unit = row.get('unit')
                unit = None
                
                if pd.notna(raw_unit) and str(raw_unit).strip() != '':
                    try:
                        unit = int(raw_unit)
                        if unit < 0:
                            raise ValueError()
                    except (ValueError, TypeError):
                        messages.warning(request, f"Invalid unit value '{raw_unit}' in row {index+2}. Must be a positive integer. Skipping row.")
                        continue
                else:
                    # Enforce compulsory requirement for 'bottles'
                    if minimum_UoM == 'bottles':
                        messages.warning(
                            request, 
                            f"'unit' is compulsory when minimum_UoM is 'bottles' (Row {index+2}). Skipping row."
                        )
                        continue
                    else:
                        unit = 0     

                try:
                    price = Decimal(row['price']) if pd.notna(row.get('price')) else None
                except:
                    messages.warning(request, f"Invalid price in row {index+2}. Skipping row.")
                    continue

                try:
                    stock = int(row['stock']) if pd.notna(row.get('stock')) else None
                except:
                    messages.warning(request, f"Invalid stock in row {index+2}. Skipping row.")
                    continue

                try:
                    low_stock_threshold = int(row['low_stock_threshold']) if pd.notna(row.get('low_stock_threshold')) else None
                except:
                    messages.warning(request, f"Invalid threshold in row {index+2}. Skipping row.")
                    continue

                if not all([product_id, product_name, price is not None, stock is not None, minimum_UoM, low_stock_threshold is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                #  Get Product from central inventory
                try:
                    product_obj = Product.objects.get(product_name=product_name)
                except Product.DoesNotExist:
                    messages.warning(request, f"Product '{product_name}' not found in inventory (row {index+2}). Skipping row.")
                    continue

                #  Check stock availability
                if product_obj.stock < stock:
                    messages.warning(
                        request, 
                        f"Insufficient stock for '{product_name}' in row {index+2}. "
                        f"Available: {product_obj.stock}, Requested: {stock}"
                    )
                    continue  # Skip this row

                # Deduct from Product stock
                product_obj.stock -= stock
                product_obj.status = product_obj.stock - product_obj.low_stock_threshold
                product_obj.save()

                # Create/Update Ipd3Drugs record
                drug, created = Ipd3Drugs.objects.get_or_create(
                    product_id=product_id,
                    product_name=product_name,
                    defaults={
                        'price': price,
                        'stock': stock,
                        'minimum_UoM': minimum_UoM,
                        'unit':unit,
                        'low_stock_threshold': low_stock_threshold,
                    }
                )

                if not created:
                    drug.price = price
                    drug.stock += stock
                    drug.minimum_UoM = minimum_UoM
                    drug.unit = unit
                    drug.low_stock_threshold = low_stock_threshold

                # Optional fields
                optional_fields = [
                    'description', 'expiry_flag_in', 'expiry_flag_in_num'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        setattr(drug, field, row[field])

                # Save extra fields
                if pd.notna(row.get('manufacturing_date')):
                    drug.manufacturing_date = pd.to_datetime(row['manufacturing_date']).date()
                if pd.notna(row.get('expiry_date')):
                    drug.expiry_date = pd.to_datetime(row['expiry_date']).date()
                if not pd.notna(row.get('description')):
                    drug.description = 'No entry'

                drug.staff = request.user
                drug.save()

                # Create Transaction
                transaction = Transaction.objects.create(
                    product=product_obj,
                    product_names=drug.product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="SALE",
                    destination="ipd3_pharm",
                    minimum_UoM=minimum_UoM,
                    staff=request.user
                )

                # Update Ipd3DrugsUpdate
                Ipd3DrugsUpdate.objects.create(
                    product=drug,
                    product_names=product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    minimum_UoM=minimum_UoM,
                    staff=request.user,
                    transaction_id=transaction.id,
                )

                if created:
                    created_count += 1
                else:
                    updated_count += 1


            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('upload_to_ipd3')
    return render(request, 'inventory/export_products.html', {'page': page})


# Upload to OPD Pharmacy 1

@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def upload_to_opdpharm(request):
    page = 'opd-pharm'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
            # Required fields
                product_id = str(row.get('product_id')).strip() if pd.notna(row.get('product_id')) else ''
                product_name = str(row.get('product_name')).strip() if pd.notna(row.get('product_name')) else ''
                raw_uom = str(row.get('minimum_UoM')) if pd.notna(row.get('minimum_UoM')) else ''
                minimum_UoM = normalize_uom(raw_uom)
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{raw_uom}' in row {index+2}. Skipping row."
                    )
                    continue

                # Handle unit parsing & validation conditional on UoM
                raw_unit = row.get('unit')
                unit = None
                
                if pd.notna(raw_unit) and str(raw_unit).strip() != '':
                    try:
                        unit = int(raw_unit)
                        if unit < 0:
                            raise ValueError()
                    except (ValueError, TypeError):
                        messages.warning(request, f"Invalid unit value '{raw_unit}' in row {index+2}. Must be a positive integer. Skipping row.")
                        continue
                else:
                    # Enforce compulsory requirement for 'bottles'
                    if minimum_UoM == 'bottles':
                        messages.warning(
                            request, 
                            f"'unit' is compulsory when minimum_UoM is 'bottles' (Row {index+2}). Skipping row."
                        )
                        continue
                    else:
                        unit = 0 

                try:
                    price = Decimal(row['price']) if pd.notna(row.get('price')) else None
                except:
                    messages.warning(request, f"Invalid price in row {index+2}. Skipping row.")
                    continue

                try:
                    stock = int(row['stock']) if pd.notna(row.get('stock')) else None
                except:
                    messages.warning(request, f"Invalid stock in row {index+2}. Skipping row.")
                    continue

                try:
                    low_stock_threshold = int(row['low_stock_threshold']) if pd.notna(row.get('low_stock_threshold')) else None
                except:
                    messages.warning(request, f"Invalid threshold in row {index+2}. Skipping row.")
                    continue

                if not all([product_id, product_name, price is not None, stock is not None, minimum_UoM, low_stock_threshold is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                #  Get Product from central inventory
                try:
                    product_obj = Product.objects.get(product_name=product_name)
                except Product.DoesNotExist:
                    messages.warning(request, f"Product '{product_name}' not found in inventory (row {index+2}). Skipping row.")
                    continue

                #  Check stock availability
                if product_obj.stock < stock:
                    messages.warning(
                        request, 
                        f"Insufficient stock for '{product_name}' in row {index+2}. "
                        f"Available: {product_obj.stock}, Requested: {stock}"
                    )
                    continue  # Skip this row

                # Deduct from Product stock
                product_obj.stock -= stock
                product_obj.status = product_obj.stock - product_obj.low_stock_threshold
                product_obj.save()

                # Create/Update Drugs record
                drug, created = OpdDrugs.objects.get_or_create(
                    product_id=product_id,
                    product_name=product_name,
                    defaults={
                        'price': price,
                        'stock': stock,
                        'minimum_UoM': minimum_UoM,
                        'unit':unit,
                        'low_stock_threshold': low_stock_threshold,
                    }
                )

                if not created:
                    drug.price = price
                    drug.stock += stock
                    drug.minimum_UoM = minimum_UoM
                    drug.unit = unit
                    drug.low_stock_threshold = low_stock_threshold

                # Optional fields
                optional_fields = [
                    'description', 'expiry_flag_in', 'expiry_flag_in_num'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        setattr(drug, field, row[field])

                # Save extra fields
                if pd.notna(row.get('manufacturing_date')):
                    drug.manufacturing_date = pd.to_datetime(row['manufacturing_date']).date()
                if pd.notna(row.get('expiry_date')):
                    drug.expiry_date = pd.to_datetime(row['expiry_date']).date()
                if not pd.notna(row.get('description')):
                    drug.description = 'No entry'

                drug.staff = request.user
                drug.save()

                # Create Transaction
                transaction = Transaction.objects.create(
                    product=product_obj,
                    product_names=drug.product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="SALE",
                    destination="opd_pharm",
                    minimum_UoM=minimum_UoM,
                    staff=request.user
                )

                # Update DrugsUpdate
                opd = OpdDrugsUpdate.objects.create(
                    product=drug,
                    product_names=product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    minimum_UoM=minimum_UoM,
                    staff=request.user,
                    transaction_id=transaction.id,
                )
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1


            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('upload_to_opd')
    return render(request, 'inventory/export_products.html', {'page': page})


# Upload to OPD Pharmacy 2

@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def upload_to_opd2pharm(request):
    page = 'opd2-pharm'
    if request.method == 'POST' and request.FILES.get('excel_file'):
        excel_file = request.FILES['excel_file']

        try:
            # Save uploaded file temporarily
            fs = FileSystemStorage()
            filename = fs.save(excel_file.name, excel_file)
            file_path = fs.path(filename)

            # Read Excel file
            df = pd.read_excel(file_path)

            created_count = 0
            updated_count = 0

            for index, row in df.iterrows():
            # Required fields
                product_id = str(row.get('product_id')).strip() if pd.notna(row.get('product_id')) else ''
                product_name = str(row.get('product_name')).strip() if pd.notna(row.get('product_name')) else ''
                raw_uom = str(row.get('minimum_UoM')) if pd.notna(row.get('minimum_UoM')) else ''
                minimum_UoM = normalize_uom(raw_uom)
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{raw_uom}' in row {index+2}. Skipping row."
                    )
                    continue

                # Handle unit parsing & validation conditional on UoM
                raw_unit = row.get('unit')
                unit = None
                
                if pd.notna(raw_unit) and str(raw_unit).strip() != '':
                    try:
                        unit = int(raw_unit)
                        if unit < 0:
                            raise ValueError()
                    except (ValueError, TypeError):
                        messages.warning(request, f"Invalid unit value '{raw_unit}' in row {index+2}. Must be a positive integer. Skipping row.")
                        continue
                else:
                    # Enforce compulsory requirement for 'bottles'
                    if minimum_UoM == 'bottles':
                        messages.warning(
                            request, 
                            f"'unit' is compulsory when minimum_UoM is 'bottles' (Row {index+2}). Skipping row."
                        )
                        continue
                    else:
                        unit = 0 


                try:
                    price = Decimal(row['price']) if pd.notna(row.get('price')) else None
                except:
                    messages.warning(request, f"Invalid price in row {index+2}. Skipping row.")
                    continue

                try:
                    stock = int(row['stock']) if pd.notna(row.get('stock')) else None
                except:
                    messages.warning(request, f"Invalid stock in row {index+2}. Skipping row.")
                    continue

                try:
                    low_stock_threshold = int(row['low_stock_threshold']) if pd.notna(row.get('low_stock_threshold')) else None
                except:
                    messages.warning(request, f"Invalid threshold in row {index+2}. Skipping row.")
                    continue

                if not all([product_id, product_name, price is not None, stock is not None, minimum_UoM, low_stock_threshold is not None]):
                    messages.warning(request, f"Missing required fields in row {index+2}. Skipping row.")
                    continue

                #  Get Product from central inventory
                try:
                    product_obj = Product.objects.get(product_name=product_name)
                except Product.DoesNotExist:
                    messages.warning(request, f"Product '{product_name}' not found in inventory (row {index+2}). Skipping row.")
                    continue

                #  Check stock availability
                if product_obj.stock < stock:
                    messages.warning(
                        request, 
                        f"Insufficient stock for '{product_name}' in row {index+2}. "
                        f"Available: {product_obj.stock}, Requested: {stock}"
                    )
                    continue  # Skip this row

                # Deduct from Product stock
                product_obj.stock -= stock
                product_obj.status = product_obj.stock - product_obj.low_stock_threshold
                product_obj.save()

                # Create/Update Drugs record
                drug, created = Opd2Drugs.objects.get_or_create(
                    product_id=product_id,
                    product_name=product_name,
                    defaults={
                        'price': price,
                        'stock': stock,
                        'minimum_UoM': minimum_UoM,
                        'unit':unit,
                        'low_stock_threshold': low_stock_threshold,
                    }
                )

                if not created:
                    drug.price = price
                    drug.stock += stock
                    drug.minimum_UoM = minimum_UoM
                    drug.unit = unit
                    drug.low_stock_threshold = low_stock_threshold

                # Optional fields
                optional_fields = [
                    'description', 'expiry_flag_in', 'expiry_flag_in_num'
                ]
                for field in optional_fields:
                    if field in row and pd.notna(row[field]):
                        setattr(drug, field, row[field])

                # Save extra fields
                if pd.notna(row.get('manufacturing_date')):
                    drug.manufacturing_date = pd.to_datetime(row['manufacturing_date']).date()
                if pd.notna(row.get('expiry_date')):
                    drug.expiry_date = pd.to_datetime(row['expiry_date']).date()
                if not pd.notna(row.get('description')):
                    drug.description = 'No entry'

                drug.staff = request.user
                drug.save()

                # Create Transaction
                transaction = Transaction.objects.create(
                    product=product_obj,
                    product_names=drug.product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="SALE",
                    destination="opd2_pharm",
                    minimum_UoM=minimum_UoM,
                    staff=request.user
                )

                # Update DrugsUpdate
                opd2 = Opd2DrugsUpdate.objects.create(
                    product=drug,
                    product_names=product_name,
                    quantity=stock,
                    price=price,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    minimum_UoM=minimum_UoM,
                    staff=request.user,
                    transaction_id=transaction.id,
                )
                
                if created:
                    created_count += 1
                else:
                    updated_count += 1


            fs.delete(filename)
            messages.success(request, f"Import complete: {created_count} created, {updated_count} updated.")

        except Exception as e:
            messages.error(request, f"Error processing file: {e}")

        return redirect('upload_to_opd2')
    return render(request, 'inventory/export_products.html', {'page': page})



# Requests Handlers


# IPD1 requests
# -----------------Beginning untouched ipd1 requsts: From Inventory to IPD1 Pharmacy
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_ipd1_requests(request):
    page = 'manage-ipd1-requests'
    ipd_requests =  ProductRequests.objects.filter(source = 'ipd_pharm', status=0)
    ipd1_store = Drugs.objects.filter().only('product_name','product_id','stock','minimum_UoM','expiry_date')
    inventory_to_ipd1_requests = ProductRequests.objects.filter(staff=request.user, source='inventory', destination='ipd_pharm', status=0, created_date__gte=timezone.now() - timedelta(hours=24))
    context = {
        'page':page,
        'get_ipd_requests':ipd_requests,
        'ipd1_store':ipd1_store,
        'inventory_to_ipd1_requests':inventory_to_ipd1_requests,
    }
    return render(request, 'inventory/review_requests.html', context)



@login_required(login_url='login')
# @department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def product_search_ipd1(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    products = Drugs.objects.filter(product_name__icontains=query, activation_status=1)[:10]

    data = []
    for product in products:
        data.append({
            'id': product.id,
            'product_id':product.product_id,
            'label': f"{product.product_name} ({product.product_id})",
            'product_name': product.product_name,
            'price': float(product.price),
            'stock': product.stock,
        })

    return JsonResponse(data, safe=False)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_inventory_to_ipd1_requisition_form(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(product_id=tx["product_id"])  # match Product

                # Save Transaction
                transaction = ProductRequests.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    source='inventory',
                    destination='ipd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_requested_inventory_to_ipd1_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # This is from Drugs model

        #  delete the requested record
        request_record.delete()

        return JsonResponse({'success': True})
    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic()
def edit_requested_inventory_to_ipd1_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - request_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)
        

        #  Update request record (DrugsUpdate)
        request_record.quantity = new_quantity
        request_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)

# ----------------------End of untouched ipd1 requsts: From Inventory to IPD1 Pharmacy


# ----------------------Beginning of untouched ipd1 requests: From IPD1 Pharmacy 1 to Inventory
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_ipd_request(request, pk):
    if request.method == "POST":
        try:
            with transaction.atomic():
                req = ProductRequests.objects.get(pk=pk)

                # Prevent insufficient stock
                if req.product.stock < req.quantity:
                    return JsonResponse({
                        "success": False,
                        "error": f"Insufficient stock! Only {req.product.stock} left."
                    })
                # 1. Record into Transaction (linked to Product)
                txn = Transaction.objects.create(
                    product=req.product,
                    quantity=req.quantity,
                    transaction_type="SALE",
                    destination='ipd_pharm',
                    staff=request.user
                )

                # 2. Find matching ipdDrugs by product_name
                try:
                    ipd_drug = Drugs.objects.get(product_name=req.product.product_name)
                except Drugs.DoesNotExist:
                    return JsonResponse({
                        "success": False,
                        "error": f"No matching Drugs found for product {req.product.product_name}"
                    })

                # 3. Record into DrugsUpdate
                DrugsUpdate.objects.create(
                    product=ipd_drug,        # this is a Drugs instance
                    quantity=req.quantity,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    staff=request.user,
                    transaction_id=txn.id
                )

                # 4. Update Product stock
                product = req.product
                product.stock = max(0, product.stock - req.quantity)
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # 5. Update ProductRequest
                req.staff2 = request.user.fullname
                req.status = 1
                req.save()

                # 6 update Drugs
                ipd_drug.stock += req.quantity
                ipd_drug.status = ipd_drug.stock - ipd_drug.low_stock_threshold
                ipd_drug.save()

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_all_ipd_requests(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                pending_requests = ProductRequests.objects.filter(
                    source='ipd_pharm', status=0
                )

                for req in pending_requests:
                    product = req.product

                    # Check stock availability before approving
                    if product.stock < req.quantity:
                        return JsonResponse({
                            "success": False,
                            "error": f"Insufficient stock for {product.product_name}"
                        })

                    # 1. Record into Transaction
                    txn = Transaction.objects.create(
                        product=product,
                        quantity=req.quantity,
                        transaction_type="SALE",
                        destination='ipd_pharm',
                        staff=request.user
                    )

                    try:
                        ipd_drug = Drugs.objects.get(product_name=req.product.product_name)
                    except Drugs.DoesNotExist:
                        return JsonResponse({
                            "success": False,
                            "error": f"No matching Drugs found for product {req.product.product_name}"
                        })

                    # 3. Record into DrugsUpdate
                    DrugsUpdate.objects.create(
                        product=ipd_drug,        #  this is an Drugs instance
                        quantity=req.quantity,
                        transaction_type="PURCHASE",
                        destination="inventory",
                        staff=request.user,
                        transaction_id=txn.id
                    )


                    # 3. Update stock
                    product.stock = max(0, product.stock - req.quantity)    
                    product.status = product.stock - product.low_stock_threshold
                    product.save()

                    # 4. Update ProductRequest
                    req.staff2 = request.user.fullname
                    req.status = 1
                    req.save()

                    # 5 update Drugs
                    ipd_drug.stock += req.quantity
                    ipd_drug.status = ipd_drug.stock - ipd_drug.low_stock_threshold
                    ipd_drug.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
@transaction.atomic()
def decline_ipd_request(request, pk):
    if request.method == "POST":
        try:
            req = ProductRequests.objects.get(pk=pk)
            req.staff2 = request.user.fullname
            req.status = 2
            req.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})

# -------------------End of untouched ipd1 requests: From IPD Pharmacy 1 to Inventory



# -------------------Beginning of untouched ipd2 requests: Inventory to IPD2 Pharmacy
# IPD2 requests
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_ipd2_requests(request):
    page = 'manage-ipd2-requests'
    ipd2_requests =  ProductRequests.objects.filter(source = 'ipd2_pharm', status=0)
    ipd2_store = Ipd2Drugs.objects.filter().only('product_name','product_id','stock','minimum_UoM','expiry_date')
    inventory_to_ipd2_requests = ProductRequests.objects.filter(staff=request.user, source='inventory', destination='ipd2_pharm', status=0, created_date__gte=timezone.now() - timedelta(hours=24))
    context = {
        'page':page,
        'get_ipd2_requests':ipd2_requests,
        'ipd2_store':ipd2_store,
        'inventory_to_ipd2_requests':inventory_to_ipd2_requests,
    }
    return render(request, 'inventory/review_requests_ipd2.html', context)


@login_required(login_url='login')
# @department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def product_search_ipd2(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    products = Ipd2Drugs.objects.filter(product_name__icontains=query, activation_status=1)[:10]

    data = []
    for product in products:
        data.append({
            'id': product.id,
            'product_id':product.product_id,
            'label': f"{product.product_name} ({product.product_id})",
            'product_name': product.product_name,
            'price': float(product.price),
            'stock': product.stock,
        })

    return JsonResponse(data, safe=False)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_inventory_to_ipd2_requisition_form(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(product_id=tx["product_id"])  # match Product

                # Save Transaction
                transaction = ProductRequests.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    source='inventory',
                    destination='ipd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_requested_inventory_to_ipd2_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # This is from Drugs model

        #  delete the requested record
        request_record.delete()

        return JsonResponse({'success': True})
    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic()
def edit_requested_inventory_to_ipd2_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - request_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)
        

        #  Update request record (Ipd2DrugsUpdate)
        request_record.quantity = new_quantity
        request_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)

# ------------------End of untouched ipd2 requsts: From Inventory to IPD2 Pharmacy


# -----------------Beginning of untouched ipd2 requests: From IPD2 Pharmacy  to Inventory
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_ipd2_request(request, pk):
    if request.method == "POST":
        try:
            with transaction.atomic():
                req = ProductRequests.objects.get(pk=pk)

                # Prevent insufficient stock
                if req.product.stock < req.quantity:
                    return JsonResponse({
                        "success": False,
                        "error": f"Insufficient stock! Only {req.product.stock} left."
                    })
                # 1. Record into Transaction (linked to Product)
                txn = Transaction.objects.create(
                    product=req.product,
                    quantity=req.quantity,
                    transaction_type="SALE",
                    destination='ipd2_pharm',
                    staff=request.user
                )

                # 2. Find matching ipdDrugs by product_name
                try:
                    ipd2_drug = Ipd2Drugs.objects.get(product_name=req.product.product_name)
                except Ipd2Drugs.DoesNotExist:
                    return JsonResponse({
                        "success": False,
                        "error": f"No matching Drugs found for product {req.product.product_name}"
                    })

                # 3. Record into Ipd2DrugsUpdate
                Ipd2DrugsUpdate.objects.create(
                    product=ipd2_drug,        #  this is an Drugs instance
                    quantity=req.quantity,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    staff=request.user,
                    transaction_id=txn.id
                )

                # 4. Update Product stock
                product = req.product
                product.stock = max(0, product.stock - req.quantity)
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # 5. Update ProductRequest
                req.staff2 = request.user.fullname
                req.status = 1
                req.save()

                # 6 update Drugs
                ipd2_drug.stock += req.quantity
                ipd2_drug.status = ipd2_drug.stock - ipd2_drug.low_stock_threshold
                ipd2_drug.save()

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_all_ipd2_requests(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                pending_requests = ProductRequests.objects.filter(
                    source='ipd2_pharm', status=0
                )

                for req in pending_requests:
                    product = req.product

                    # Check stock availability before approving
                    if product.stock < req.quantity:
                        return JsonResponse({
                            "success": False,
                            "error": f"Insufficient stock for {product.product_name}"
                        })

                    # 1. Record into Transaction
                    txn = Transaction.objects.create(
                        product=product,
                        quantity=req.quantity,
                        transaction_type="SALE",
                        destination='ipd2_pharm',
                        staff=request.user
                    )

                    try:
                        ipd2_drug = Ipd2Drugs.objects.get(product_name=req.product.product_name)
                    except Ipd2Drugs.DoesNotExist:
                        return JsonResponse({
                            "success": False,
                            "error": f"No matching Drugs found for product {req.product.product_name}"
                        })

                    # 3. Record into Ipd2DrugsUpdate
                    Ipd2DrugsUpdate.objects.create(
                        product=ipd2_drug,        #  this is an Drugs instance
                        quantity=req.quantity,
                        transaction_type="PURCHASE",
                        destination="inventory",
                        staff=request.user,
                        transaction_id=txn.id
                    )


                    # 3. Update stock
                    product.stock = max(0, product.stock - req.quantity)    
                    product.status = product.stock - product.low_stock_threshold
                    product.save()

                    # 4. Update ProductRequest
                    req.staff2 = request.user.fullname
                    req.status = 1
                    req.save()

                    # 5 update Drugs
                    ipd2_drug.stock += req.quantity
                    ipd2_drug.status = ipd2_drug.stock - ipd2_drug.low_stock_threshold
                    ipd2_drug.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
@transaction.atomic()
def decline_ipd2_request(request, pk):
    if request.method == "POST":
        try:
            req = ProductRequests.objects.get(pk=pk)
            req.staff2 = request.user.fullname
            req.status = 2
            req.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})

# -------------------End of untouched ipd2 requests: From IPD Pharmacy 1 to Inventory



# --------------------Beginning of untouched ipd3 requests: Inventory to IPD3 Pharmacy
# IPD3 requests
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_ipd3_requests(request):
    page = 'manage-ipd3-requests'
    ipd3_requests =  ProductRequests.objects.filter(source = 'ipd3_pharm', status=0)
    ipd3_store = Ipd3Drugs.objects.filter().only('product_name','product_id','stock','minimum_UoM','expiry_date')
    inventory_to_ipd3_requests = ProductRequests.objects.filter(staff=request.user, source='inventory', destination='ipd3_pharm', status=0, created_date__gte=timezone.now() - timedelta(hours=24))
    context = {
        'page':page,
        'get_ipd3_requests':ipd3_requests,
        'ipd3_store':ipd3_store,
        'inventory_to_ipd3_requests':inventory_to_ipd3_requests,
    }
    return render(request, 'inventory/review_requests_ipd3.html', context)


@login_required(login_url='login')
# @department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def product_search_ipd3(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    products = Ipd3Drugs.objects.filter(product_name__icontains=query, activation_status=1)[:10]

    data = []
    for product in products:
        data.append({
            'id': product.id,
            'product_id':product.product_id,
            'label': f"{product.product_name} ({product.product_id})",
            'product_name': product.product_name,
            'price': float(product.price),
            'stock': product.stock,
        })

    return JsonResponse(data, safe=False)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_inventory_to_ipd3_requisition_form(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(product_id=tx["product_id"])  # match Product

                # Save Transaction
                transaction = ProductRequests.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    source='inventory',
                    destination='ipd3_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_requested_inventory_to_ipd3_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # This is from Drugs model

        #  delete the requested record
        request_record.delete()

        return JsonResponse({'success': True})
    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic()
def edit_requested_inventory_to_ipd3_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - request_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)
        

        #  Update request record (Ipd3DrugsUpdate)
        request_record.quantity = new_quantity
        request_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)

# ---------------------End of untouched ipd3 requsts: From Inventory to IPD3 Pharmacy


# --------------------Beginning of untouched ipd3 requests: From IPD3 Pharmacy  to Inventory
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_ipd3_request(request, pk):
    if request.method == "POST":
        try:
            with transaction.atomic():
                req = ProductRequests.objects.get(pk=pk)

                # Prevent insufficient stock
                if req.product.stock < req.quantity:
                    return JsonResponse({
                        "success": False,
                        "error": f"Insufficient stock! Only {req.product.stock} left."
                    })
                # 1. Record into Transaction (linked to Product)
                txn = Transaction.objects.create(
                    product=req.product,
                    quantity=req.quantity,
                    transaction_type="SALE",
                    destination='ipd3_pharm',
                    staff=request.user
                )

                # 2. Find matching ipdDrugs by product_name
                try:
                    ipd3_drug = Ipd3Drugs.objects.get(product_name=req.product.product_name)
                except Ipd3Drugs.DoesNotExist:
                    return JsonResponse({
                        "success": False,
                        "error": f"No matching Drugs found for product {req.product.product_name}"
                    })

                # 3. Record into Ipd3DrugsUpdate
                Ipd3DrugsUpdate.objects.create(
                    product=ipd3_drug,        #  this is an Ipd3Drugs instance
                    quantity=req.quantity,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    staff=request.user,
                    transaction_id=txn.id
                )

                # 4. Update Product stock
                product = req.product
                product.stock = max(0, product.stock - req.quantity)
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # 5. Update ProductRequest
                req.staff2 = request.user.fullname
                req.status = 1
                req.save()

                # 6 update Drugs
                ipd3_drug.stock += req.quantity
                ipd3_drug.status = ipd3_drug.stock - ipd3_drug.low_stock_threshold
                ipd3_drug.save()

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_all_ipd3_requests(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                pending_requests = ProductRequests.objects.filter(
                    source='ipd3_pharm', status=0
                )

                for req in pending_requests:
                    product = req.product

                    # Check stock availability before approving
                    if product.stock < req.quantity:
                        return JsonResponse({
                            "success": False,
                            "error": f"Insufficient stock for {product.product_name}"
                        })

                    # 1. Record into Transaction
                    txn = Transaction.objects.create(
                        product=product,
                        quantity=req.quantity,
                        transaction_type="SALE",
                        destination='ipd3_pharm',
                        staff=request.user
                    )

                    try:
                        ipd3_drug = Ipd3Drugs.objects.get(product_name=req.product.product_name)
                    except Ipd3Drugs.DoesNotExist:
                        return JsonResponse({
                            "success": False,
                            "error": f"No matching Drugs found for product {req.product.product_name}"
                        })

                    # 3. Record into Ipd3DrugsUpdate
                    Ipd3DrugsUpdate.objects.create(
                        product=ipd3_drug,        #  this is an Drugs instance
                        quantity=req.quantity,
                        transaction_type="PURCHASE",
                        destination="inventory",
                        staff=request.user,
                        transaction_id=txn.id
                    )


                    # 3. Update stock
                    product.stock = max(0, product.stock - req.quantity)    
                    product.status = product.stock - product.low_stock_threshold
                    product.save()

                    # 4. Update ProductRequest
                    req.staff2 = request.user.fullname
                    req.status = 1
                    req.save()

                    # 5 update Drugs
                    ipd3_drug.stock += req.quantity
                    ipd3_drug.status = ipd3_drug.stock - ipd3_drug.low_stock_threshold
                    ipd3_drug.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
@transaction.atomic()
def decline_ipd3_request(request, pk):
    if request.method == "POST":
        try:
            req = ProductRequests.objects.get(pk=pk)
            req.staff2 = request.user.fullname
            req.status = 2
            req.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})

# ----------------End of untouched ipd3 requests: From IPD Pharmacy 1 to Inventory


# -------------------Beginning of untouched OPD requests: Inventory to OPD Pharmacy 1
# opd requests
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_opd_requests(request):
    page = 'manage-opd-requests'
    opd_requests =  ProductRequests.objects.filter(source = 'opd_pharm', status=0)
    opd_store = OpdDrugs.objects.filter().only('product_name','product_id','stock','minimum_UoM','expiry_date')
    inventory_to_opd_requests = ProductRequests.objects.filter(staff=request.user, source='inventory', destination='opd_pharm', status=0, created_date__gte=timezone.now() - timedelta(hours=24))
    context = {
        'page':page,
        'get_opd_requests':opd_requests,
        'opd_store':opd_store,
        'inventory_to_opd_requests':inventory_to_opd_requests,
    }
    return render(request, 'inventory/review_requests_opd.html', context)


@login_required(login_url='login')
# @department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def product_search_opd(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    products = OpdDrugs.objects.filter(product_name__icontains=query, activation_status=1)[:10]

    data = []
    for product in products:
        data.append({
            'id': product.id,
            'product_id':product.product_id,
            'label': f"{product.product_name} ({product.product_id})",
            'product_name': product.product_name,
            'price': float(product.price),
            'stock': product.stock,
        })

    return JsonResponse(data, safe=False)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_inventory_to_opd_requisition_form(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(product_id=tx["product_id"])  # match Product

                # Save Transaction
                transaction = ProductRequests.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    source='inventory',
                    destination='opd_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_requested_inventory_to_opd_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # This is from OpdDrugs model

        #  delete the requested record
        request_record.delete()

        return JsonResponse({'success': True})
    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic()
def edit_requested_inventory_to_opd_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # from Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - request_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)
        

        #  Update request record (OpdDrugsUpdate)
        request_record.quantity = new_quantity
        request_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)

# ----------------End of untouched opd requsts: From Inventory to opd Pharmacy


# ----------------Beginning of untouched opd requests: From opd Pharmacy  to Inventory
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_opd_request(request, pk):
    if request.method == "POST":
        try:
            with transaction.atomic():
                req = ProductRequests.objects.get(pk=pk)

                # Prevent insufficient stock
                if req.product.stock < req.quantity:
                    return JsonResponse({
                        "success": False,
                        "error": f"Insufficient stock! Only {req.product.stock} left."
                    })
                # 1. Record into Transaction (linked to Product)
                txn = Transaction.objects.create(
                    product=req.product,
                    quantity=req.quantity,
                    transaction_type="SALE",
                    destination='opd_pharm',
                    staff=request.user
                )

                # 2. Find matching ipdDrugs by product_name
                try:
                    opd_drug = OpdDrugs.objects.get(product_name=req.product.product_name)
                except OpdDrugs.DoesNotExist:
                    return JsonResponse({
                        "success": False,
                        "error": f"No matching Drugs found for product {req.product.product_name}"
                    })

                # 3. Record into OpdDrugsUpdate
                OpdDrugsUpdate.objects.create(
                    product=opd_drug,        #  this is an OpdDrugs instance
                    quantity=req.quantity,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    staff=request.user,
                    transaction_id=txn.id
                )

                # 4. Update Product stock
                product = req.product
                product.stock = max(0, product.stock - req.quantity)
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # 5. Update ProductRequest
                req.staff2 = request.user.fullname
                req.status = 1
                req.save()

                # 6 update Drugs
                opd_drug.stock += req.quantity
                opd_drug.status = opd_drug.stock - opd_drug.low_stock_threshold
                opd_drug.save()

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_all_opd_requests(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                pending_requests = ProductRequests.objects.filter(
                    source='opd_pharm', status=0
                )

                for req in pending_requests:
                    product = req.product

                    # Check stock availability before approving
                    if product.stock < req.quantity:
                        return JsonResponse({
                            "success": False,
                            "error": f"Insufficient stock for {product.product_name}"
                        })

                    # 1. Record into Transaction
                    txn = Transaction.objects.create(
                        product=product,
                        quantity=req.quantity,
                        transaction_type="SALE",
                        destination='opd_pharm',
                        staff=request.user
                    )

                    try:
                        opd_drug = OpdDrugs.objects.get(product_name=req.product.product_name)
                    except OpdDrugs.DoesNotExist:
                        return JsonResponse({
                            "success": False,
                            "error": f"No matching Drugs found for product {req.product.product_name}"
                        })

                    # 3. Record into OpdDrugsUpdate
                    OpdDrugsUpdate.objects.create(
                        product=opd_drug,        #  this is an Drugs instance
                        quantity=req.quantity,
                        transaction_type="PURCHASE",
                        destination="inventory",
                        staff=request.user,
                        transaction_id=txn.id
                    )


                    # 3. Update stock
                    product.stock = max(0, product.stock - req.quantity)    
                    product.status = product.stock - product.low_stock_threshold
                    product.save()

                    # 4. Update ProductRequest
                    req.staff2 = request.user.fullname
                    req.status = 1
                    req.save()

                    # 5 update Drugs
                    opd_drug.stock += req.quantity
                    opd_drug.status = opd_drug.stock - opd_drug.low_stock_threshold
                    opd_drug.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
@transaction.atomic()
def decline_opd_request(request, pk):
    if request.method == "POST":
        try:
            req = ProductRequests.objects.get(pk=pk)
            req.staff2 = request.user.fullname
            req.status = 2
            req.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})

# ----------------End of untouched opd requests: From OPD Pharmacy 1 to Inventory



# -----------------Beginning of untouched opd2 requests: Inventory to opd2 Pharmacy
# opd2 requests
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_opd2_requests(request):
    page = 'manage-opd2-requests'
    opd2_requests =  ProductRequests.objects.filter(source = 'opd2_pharm', status=0)
    opd2_store = Opd2Drugs.objects.filter().only('product_name','product_id','stock','minimum_UoM','expiry_date')
    inventory_to_opd2_requests = ProductRequests.objects.filter(staff=request.user, source='inventory', destination='opd2_pharm', status=0, created_date__gte=timezone.now() - timedelta(hours=24))
    context = {
        'page':page,
        'get_opd2_requests':opd2_requests,
        'opd2_store':opd2_store,
        'inventory_to_opd2_requests':inventory_to_opd2_requests,
    }
    return render(request, 'inventory/review_requests_opd2.html', context)


@login_required(login_url='login')
# @department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def product_search_opd2(request):
    query = request.GET.get('term', '')
    if not query:
        return JsonResponse([], safe=False)

    products = Opd2Drugs.objects.filter(product_name__icontains=query, activation_status=1)[:10]

    data = []
    for product in products:
        data.append({
            'id': product.id,
            'product_id':product.product_id,
            'label': f"{product.product_name} ({product.product_id})",
            'product_name': product.product_name,
            'price': float(product.price),
            'stock': product.stock,
        })

    return JsonResponse(data, safe=False)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def save_inventory_to_opd2_requisition_form(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(product_id=tx["product_id"])  # match Product

                # Save Transaction
                transaction = ProductRequests.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    source='inventory',
                    destination='opd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})



@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@transaction.atomic()
def delete_requested_inventory_to_opd2_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # This is from Opd2Drugs model

        #  delete the requested record
        request_record.delete()

        return JsonResponse({'success': True})
    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@require_POST
@transaction.atomic()
def edit_requested_inventory_to_opd2_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # from Opd2Drugs model
        product_inventory = Product.objects.get(product_id=drug.product_id)

        new_quantity = int(request.POST.get("quantity", 0))

        if new_quantity <= 0:
            return JsonResponse({'error': 'Quantity must be greater than zero'}, status=400)

        # Calculate difference
        diff = new_quantity - request_record.quantity  

        # Check stock if increasing quantity
        if diff > 0 and product_inventory.stock < diff:
            return JsonResponse({'error': 'Not enough stock available to increase quantity'}, status=400)
        

        #  Update request record (Opd2DrugsUpdate)
        request_record.quantity = new_quantity
        request_record.save()

        return JsonResponse({
            'success': True,
            'new_quantity': new_quantity
        })

    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)
    except Product.DoesNotExist:
        return JsonResponse({'error': 'Matching product not found in inventory'}, status=404)

# -------------------End of untouched opd2 requsts: From Inventory to opd2 Pharmacy


# -------------------Beginning of untouched opd2 requests: From opd2 Pharmacy  to Inventory
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_opd2_request(request, pk):
    if request.method == "POST":
        try:
            with transaction.atomic():
                req = ProductRequests.objects.get(pk=pk)

                # Prevent insufficient stock
                if req.product.stock < req.quantity:
                    return JsonResponse({
                        "success": False,
                        "error": f"Insufficient stock! Only {req.product.stock} left."
                    })
                # 1. Record into Transaction (linked to Product)
                txn = Transaction.objects.create(
                    product=req.product,
                    quantity=req.quantity,
                    transaction_type="SALE",
                    destination='opd2_pharm',
                    staff=request.user
                )

                # 2. Find matching ipdDrugs by product_name
                try:
                    opd2_drug = Opd2Drugs.objects.get(product_name=req.product.product_name)
                except Opd2Drugs.DoesNotExist:
                    return JsonResponse({
                        "success": False,
                        "error": f"No matching Drugs found for product {req.product.product_name}"
                    })

                # 3. Record into Opd2DrugsUpdate
                Opd2DrugsUpdate.objects.create(
                    product=opd2_drug,        #  this is an Drugs instance
                    quantity=req.quantity,
                    transaction_type="PURCHASE",
                    destination="inventory",
                    staff=request.user,
                    transaction_id=txn.id
                )

                # 4. Update Product stock
                product = req.product
                product.stock = max(0, product.stock - req.quantity)
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # 5. Update ProductRequest
                req.staff2 = request.user.fullname
                req.status = 1
                req.save()

                # 6 update Drugs
                opd2_drug.stock += req.quantity
                opd2_drug.status = opd2_drug.stock - opd2_drug.low_stock_threshold
                opd2_drug.save()

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def approve_all_opd2_requests(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                pending_requests = ProductRequests.objects.filter(
                    source='opd2_pharm', status=0
                )

                for req in pending_requests:
                    product = req.product

                    # Check stock availability before approving
                    if product.stock < req.quantity:
                        return JsonResponse({
                            "success": False,
                            "error": f"Insufficient stock for {product.product_name}"
                        })

                    # 1. Record into Transaction
                    txn = Transaction.objects.create(
                        product=product,
                        quantity=req.quantity,
                        transaction_type="SALE",
                        destination='opd2_pharm',
                        staff=request.user
                    )

                    try:
                        opd2_drug = Opd2Drugs.objects.get(product_name=req.product.product_name)
                    except Opd2Drugs.DoesNotExist:
                        return JsonResponse({
                            "success": False,
                            "error": f"No matching Drugs found for product {req.product.product_name}"
                        })

                    # 3. Record into Opd2DrugsUpdate
                    Opd2DrugsUpdate.objects.create(
                        product=opd2_drug,        #  this is an Drugs instance
                        quantity=req.quantity,
                        transaction_type="PURCHASE",
                        destination="inventory",
                        staff=request.user,
                        transaction_id=txn.id
                    )


                    # 3. Update stock
                    product.stock = max(0, product.stock - req.quantity)    
                    product.status = product.stock - product.low_stock_threshold
                    product.save()

                    # 4. Update ProductRequest
                    req.staff2 = request.user.fullname
                    req.status = 1
                    req.save()

                    # 5 update Drugs
                    opd2_drug.stock += req.quantity
                    opd2_drug.status = opd2_drug.stock - opd2_drug.low_stock_threshold
                    opd2_drug.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
@transaction.atomic()
def decline_opd2_request(request, pk):
    if request.method == "POST":
        try:
            req = ProductRequests.objects.get(pk=pk)
            req.staff2 = request.user.fullname
            req.status = 2
            req.save()
            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})

# ------------------End of untouched opd2 requests: From OPD Pharmacy 2 to Inventory


# Histories
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def imports_history(request):
    page = 'import-history'
    history_imports = Transaction.objects.filter(transaction_type='PURCHASE')
    context = {
        'page':page,
        'history_imports':history_imports
    }
    return render(request, 'inventory/history.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def exports_history(request):
    page = 'export-history'
    history_exports = Transaction.objects.filter(transaction_type='SALE')
    context = {
        'page':page,
        'history_exports':history_exports
    }
    return render(request, 'inventory/history.html', context)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def requests_history(request):
    page = 'request-history'
    history_requests = ProductRequests.objects.all()
    context = {
        'page':page,
        'history_requests':history_requests
    }
    return render(request, 'inventory/history.html', context)



# ------------------------- Vendors
@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def view_vendors(request):
    page = 'view-vendors'
    vendors = Expense.objects.all()
    total_payments = 0
    for pay in vendors:
        total_payments += pay.payment
    total_assets = vendors.aggregate(total=Sum(ExpressionWrapper(F('unit_price') * F('quantity'),output_field=DecimalField())))['total'] or 0
    bills_payable = total_assets - total_payments
    creditors_counts = vendors.filter(due__gt = 0).count()
    # upload vendors from MS-Excel file
    if request.method == 'POST':
        form = VendorsUploadForm(request.POST, request.FILES)
        if form.is_valid():
            # Read the Excel file
            excel_file = request.FILES['file']
            df = pd.read_excel(excel_file)
            # Iterate over the DataFrame and save to the database
            for index, row in df.iterrows():
                minimum_UoM =  normalize_uom(row['minimum_UoM'])
                if not minimum_UoM:
                    messages.warning(
                        request, 
                        f"Invalid minimum_UoM '{minimum_UoM}' in row {index+2}. Skipping row."
                    )
                    continue
                created = Expense.objects.create(
                    vendor_name = row['vendor_name'],
                    vendor_id = row['vendor_id'],
                    product_name = row['product_name'],
                    product_id = row['product_id'],
                    minimum_UoM =  normalize_uom(row['minimum_UoM']),
                    quantity = row['quantity'],
                    unit_price = row['unit_price'],
                    payment = row['payment'],
                    staff = request.user
                )
                VendorTransaction.objects.create(
                    vendor=created,
                    payment = row['payment'],
                    expense_id = created.id,
                    staff = request.user
                    )
            messages.success(request, 'Vendors records Uploaded Successfully')
    else:
        form = VendorsUploadForm()
    contex = {
        'page':page,
        'form':form,
        'vendors':vendors,
        'total_assets':total_assets,
        'total_payments':total_payments,
        'bills_payable':bills_payable,
        'creditors_counts':creditors_counts,
    }
    return render(request, 'inventory/vendors.html', contex)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
def manage_vendors(request, vendor_id):
    vendor = get_object_or_404(Expense, id=vendor_id)
    payment_history = VendorTransaction.objects.filter(expense_id=vendor.id)
    other_payments = 0
    for total in payment_history:
        other_payments += total.payment

    # retain initial payment
    initial_payment = vendor.payment - Decimal(other_payments)

    form = EditVendorForm(instance=vendor)
    if request.method == 'POST':
        if 'edit_vendor' in request.POST:
            form = EditVendorForm(request.POST, instance=vendor)
            if form.is_valid():
                mod_vendor = form.save(commit=False)
                mod_vendor.staff = request.user
                mod_vendor.save()
                form.save()
                messages.success(request,'Detail of this Vendor was successfully modified!')
            else:
                messages.error(request,'Error Occurred, Invalid form submission!')
        elif 'payment' in request.POST:
            create = VendorTransaction.objects.create(
                    vendor=vendor,
                    payment = request.POST.get('amount'),
                    expense_id = vendor.id,
                    staff = request.user
                    )
            # update existing payment
            vendor.payment += Decimal(create.payment)
            vendor.save()
            if create:
                messages.success(request,'Payment successfully recorded!')
            else:
                messages.error(request,'Error Occurred, Payment cound not be processed!')

    contex = {
        'vendor':vendor,
        'form':form,
        'payment_history':payment_history,
        'other_payments':other_payments,
        'initial_payment':initial_payment,
    }
    return render(request, 'inventory/manage_vendors.html', contex)


@login_required(login_url='login')
@department_required('Inventory', 'Admin', 'CMD')
@csrf_exempt
def create_vendors_records(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)

            items = data.get("items", [])
            if not items:
                return JsonResponse({"success": False, "error": "At least one item is required."}, status=400)

            with transaction.atomic():
                for record in items:
                    vendor = record.get("vendor", "").strip()
                    vendor_id = record.get("vendor_id", "")
                    product_name = record.get("product_name", "").strip()
                    product_id = record.get("product_id", "")
                    qty = record.get("qty", 0)
                    uom = record.get("uom", "")
                    rate = record.get("rate", 0)
                    payment = record.get("payment", 0)

                    if not vendor or not rate:
                        return JsonResponse({"success": False, "error": "Each item must have vendor and rate."}, status=400)

                    try:
                        qty = int(qty)
                        rate = float(rate) 
                        payment = float(payment)
                    except (TypeError, ValueError):
                        return JsonResponse({"success": False, "error": "Invalid quantity or rate."}, status=400)

                    if qty <= 0 or rate <= 0:
                        return JsonResponse({"success": False, "error": "Quantity and rate must be greater than zero."}, status=400)

                    created = Expense.objects.create(
                        vendor_name=vendor,
                        vendor_id=vendor_id.strip() if vendor_id else "",
                        product_name=product_name,
                        product_id=product_id.strip() if product_id else "",
                        quantity=qty,
                        minimum_UoM=uom.strip() if uom else "",
                        unit_price=rate,
                        payment=payment if payment else 0,
                        staff=request.user
                    )
                    VendorTransaction.objects.create(
                    vendor=created,
                    payment = payment if payment else 0,
                    expense_id = created.id,
                    staff = request.user
                    )

            return JsonResponse({"success": True, "message": "Vendor records created successfully."})

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "Invalid JSON payload."}, status=400)

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)}, status=500)

    return JsonResponse({"success": False, "error": "Invalid request method."}, status=405)

