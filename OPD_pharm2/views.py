import pandas as pd
from django.shortcuts import render
from django.http import Http404, HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
import os
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.db.models import Q, F, Sum, ExpressionWrapper, DecimalField, Max
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from django.template.defaultfilters import timesince
from users.templatetags.custom_tags import currency
from .models import Opd2Drugs, Opd2DrugsUpdate, OPD2AdministeredDrugs
from inventory.models import ProductRequests, Product, Transaction
from patients.models import PatientProfile
import json
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors
import time 
from io import BytesIO
from django.core.mail import EmailMessage
from django.conf import settings
from reportlab.lib.pagesizes import A4
today = timezone.now().date()

 
@login_required(login_url='login')
def check_expiring_products():
    notification_date = today + timedelta(weeks=2)
    expiring_products = Opd2Drugs.objects.filter(expiry_date__lte = notification_date)
    return expiring_products


@login_required(login_url='login')
@transaction.atomic()
def view_opd2_product(request):
    page = 'view-opd2-product'
    expiring_conditions = Q()
    expired_condition = Q(expiry_date__lt=today)
    products = Opd2Drugs.objects.filter(activation_status=1)
    locked = Opd2Drugs.objects.filter(activation_status=0)
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
    expired_prod = Opd2Drugs.objects.filter(expired_condition)
    expiring_prod = Opd2Drugs.objects.filter(expiring_conditions)
    
    
    # in stock calculation
    in_stock = Opd2DrugsUpdate.objects.filter(created_date__gte=timezone.now() - timedelta(hours=24)).only('price','quantity')
    in_asset = in_stock.aggregate(total=Sum(ExpressionWrapper(F('price') * F('quantity'),output_field=DecimalField())))['total'] or 0


    # out stock calculation
    out_stock = OPD2AdministeredDrugs.objects.filter(created_date__gte=timezone.now() - timedelta(hours=24)).only('rate','quantity')
    out_stock_balance = out_stock.aggregate(total=Sum(ExpressionWrapper(F('rate') * F('quantity'),output_field=DecimalField())))['total'] or 0


    expiry_status = 0
    if expired_prod.exists():
        expiry_status = 1

    # Current Stock Balance
    total_cost = Opd2Drugs.objects.filter()
    asset = total_cost.aggregate(total=Sum(ExpressionWrapper(F('price') * F('stock'),output_field=DecimalField())))['total'] or 0


    low_stock_products = Opd2Drugs.objects.filter(stock__lte=F('low_stock_threshold')).count()

    context = {
        'products': products,
        'locked':locked,
        'locked_counts':locked_counts,
        'expiring_prod': expiring_prod,
        'expired_prod': expired_prod,
        'expiry_status':expiry_status,
        'low_stock_products': low_stock_products,
        'asset': asset,
        'in_stock':in_stock,
        'in_asset':in_asset,
        'out_stock':out_stock,
        'out_asset':out_stock_balance,
        'page':page,
    }
    return render(request, 'OPD_pharm2/opd2_inventory.html', context)


@login_required(login_url='login')
def generate_report_opd2(request):
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
    in_stock = Opd2DrugsUpdate.objects.filter(
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
            'in_asset': in_asset,
            'page':'instock-report-opd2'
        }
        return render(request, 'OPD_pharm2/opd2_inventory.html', context)


@login_required(login_url='login')
def opd2_out_stock_report(request):
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
    out_stock = OPD2AdministeredDrugs.objects.filter(
        created_date__gte=timezone.now() - time_delta
    )
    
    # Calculate aggregates
    out_stock_balance = out_stock.aggregate(total=Sum(ExpressionWrapper(F('rate') * F('quantity'),output_field=DecimalField())))['total'] or 0

    
    # Prepare data for response
    transactions_data = [{
        'product_name': t.item,
        'price': currency(t.rate),
        'quantity': t.quantity,
        'created_date': t.created_date.strftime('%Y-%m-%d %H:%M:%S'),
        'timesince': timesince(t.created_date),  
        'id': t.id
    } for t in out_stock]
    
    # Return JSON for AJAX or render template for regular request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'out_asset': currency(out_stock_balance),
            'transactions': transactions_data
        })
    else:
        context = {
            'out_stock': out_stock,
            'out_asset': out_stock_balance,
            'page':'outstock-report-opd2'
        }
        return render(request, 'OPD_pharm2/opd2_inventory.html', context)
    

@login_required(login_url='login')
def opd2_return_stock_report(request):
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
    returned_stock = ProductRequests.objects.filter(destination='opd2_pharm',
        created_date__gte=timezone.now() - time_delta
    )
    
    # Calculate aggregates
    returned_stock_balance = returned_stock.aggregate(total=Sum(ExpressionWrapper(F('price') * F('quantity'),output_field=DecimalField())))['total'] or 0

    
    # Prepare data for response
    transactions_data = [{
        'product_name': t.product_names,
        'price': currency(t.price),
        'quantity': t.quantity,
        'created_date': t.created_date.strftime('%Y-%m-%d %H:%M:%S'),
        'timesince': timesince(t.created_date),  
        'id': t.id
    } for t in returned_stock]
    
    # Return JSON for AJAX or render template for regular request
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'returned_asset': currency(returned_stock_balance),
            'transactions': transactions_data
        })
    else:
        context = {
            'returned_stock': returned_stock,
            'returned_asset': returned_stock_balance
        }
        return render(request, 'OPD_pharm2/opd2_inventory.html', context)
    

@login_required(login_url='login')
@transaction.atomic()
def update_opd2_stock(request, product_id):
    product = get_object_or_404(Opd2Drugs, id=product_id)
    sku = product.product_id
    expired_prod = Opd2Drugs.objects.filter(expiry_date__lt=today, id=product_id) 
    expiry_status = 0
    if expired_prod.exists():
        expiry_status = 1
    if request.method == 'POST':
        Opd2Drugs.objects.filter(id=product_id).update(manufacturing_date=request.POST.get('manufacturing_date'), expiry_date=request.POST.get('expiry_date'))
        messages.success(request,"Product's date successfully updated!")
    context = {
        'product': product,
        # 'form':form,
        'expiry_status':expiry_status,
        'page': 'stock-upd-opd2',
    }
    return render(request, 'OPD_pharm2/transactions.html', context)

# Requisitions

def opd2_requisitions(request):
    return render (request,'OPD_pharm2/opd2_requisition_form.html',{'page':'opd2-requisitions'})


@login_required(login_url='login')
@transaction.atomic()
def save_opd2_requisition_form(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            transactions = data.get("transactions", [])
            user = request.user  # staff who made the transaction

            for tx in transactions:
                product = Product.objects.get(id=tx["product_id"])

                # Save Transaction
                transaction = ProductRequests.objects.create(
                    product=product,
                    product_names=tx["product_names"],
                    quantity=int(tx["quantity"]),
                    price=float(tx["price"]),
                    source='opd2_pharm',
                    minimum_UoM=tx["minimum_UoM"],
                    staff=user
                )
            
            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
def manage_requested_opd2(request):
    page = 'manage-opd2-request'
    opd2_requests = ProductRequests.objects.filter(staff=request.user, source='opd2_pharm', status=0, created_date__gte=timezone.now() - timedelta(hours=24))

    context = {
        'opd2_requests': opd2_requests, 
        'page':page,
    }
    return render(request, 'OPD_pharm2/opd2_requests_review.html', context)


@login_required(login_url='login')
@transaction.atomic()
def delete_requested_opd2_products(request, product_id):
    try:
        request_record = ProductRequests.objects.get(id=product_id)
        drug = request_record.product  # This is from Drugs model

        #  delete the requested record
        request_record.delete()

        return JsonResponse({'success': True})
    except ProductRequests.DoesNotExist:
        return JsonResponse({'error': 'Product not found'}, status=404)


@login_required(login_url='login')
@require_POST
@transaction.atomic()
def edit_requested_opd2_products(request, product_id):
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


@login_required(login_url='login')
def history_of_requested_opd2_products(request):
    page = 'history-of-opd2-requests'
    opd2_request_history = ProductRequests.objects.filter(source='opd2_pharm')

    context = {
        'opd2_request_history': opd2_request_history, 
        'page':page,
    }
    return render(request, 'OPD_pharm2/opd2_requests_review.html', context)


@login_required(login_url='login')
@transaction.atomic()     
def barcodeScan(request):
    return render(request, 'OPD_pharm2/barcode_scanner.html')


# Beginning of untouched OPD2 requests: From OPD Pharmacy 2 to Inventory
@login_required(login_url='login')
def inventory_requests_to_opd2(request):
    get_inventory_requests = ProductRequests.objects.filter(source='inventory', destination='opd2_pharm', status=0)
    contxt = {
        'get_inventory_requests':get_inventory_requests,
        'page':'opd2-inventory-requests',
    }
    return render(request, 'OPD_pharm2/opd2_request_from_inventory.html', contxt)

@login_required(login_url='login')
@csrf_exempt
def opd2_approve_inventory_request(request, pk):
    if request.method == "POST":
        try:
            with transaction.atomic():
                req = ProductRequests.objects.get(pk=pk)

                # 1. Find matching ipdDrugs by product_name
                try:
                    opd2_drug = Opd2Drugs.objects.get(product_name=req.product.product_name)
                except Opd2Drugs.DoesNotExist:
                    return JsonResponse({
                        "success": False,
                        "error": f"No matching Drugs found for product {req.product.product_name}"
                    })

                # Prevent insufficient stock
                if opd2_drug.stock < req.quantity:
                    return JsonResponse({
                        "success": False,
                        "error": f"Insufficient stock! Only {opd2_drug.stock} left."
                    })
                # 2. Record into Transaction (linked to Product)
                txn = Transaction.objects.create(
                    product=req.product,
                    quantity=req.quantity,
                    transaction_type="PURCHASE",
                    destination='inventory',
                    staff=request.user
                )


                # 3. Record into DrugsUpdate
                Opd2DrugsUpdate.objects.create(
                    product=opd2_drug,        
                    quantity=req.quantity,
                    transaction_type="SALE",
                    destination="inventory",
                    staff=request.user,
                    transaction_id=txn.id
                )

                # 4. Update Product stock
                product = req.product
                product.stock = max(0, product.stock + req.quantity)
                product.status = product.stock - product.low_stock_threshold
                product.save()

                # 5. Update ProductRequest
                req.staff2 = request.user.fullname
                req.status = 1
                req.save()

                # 6 update Drugs
                opd2_drug.stock -= req.quantity
                opd2_drug.status = opd2_drug.stock - opd2_drug.low_stock_threshold
                opd2_drug.save()

            return JsonResponse({"success": True})

        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})

    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@csrf_exempt
def opd2_approve_all_inventory_requests(request):
    if request.method == "POST":
        try:
            with transaction.atomic():
                pending_requests = ProductRequests.objects.filter(
                    source='inventory', status=0
                )

                for req in pending_requests:
                    product = req.product

                    try:
                        opd2_drug = Opd2Drugs.objects.get(product_name=req.product.product_name)
                    except Opd2Drugs.DoesNotExist:
                        return JsonResponse({
                            "success": False,
                            "error": f"No matching Drugs found for product {req.product.product_name}"
                        })

                    # Check stock availability before approving
                    if opd2_drug.stock < req.quantity:
                        return JsonResponse({
                            "success": False,
                            "error": f"Insufficient stock for {product.product_name}"
                        })

                    # 1. Record into Transaction
                    txn = Transaction.objects.create(
                        product=product,
                        quantity=req.quantity,
                        transaction_type="PURCHASE",
                        destination='inventory',
                        staff=request.user
                    )


                    # 2. Record into DrugsUpdate
                    Opd2DrugsUpdate.objects.create(
                        product=opd2_drug,        
                        quantity=req.quantity,
                        transaction_type="SALE",
                        destination="inventory",
                        staff=request.user,
                        transaction_id=txn.id
                    )


                    # 3. Update stock
                    opd2_drug.stock = max(0, opd2_drug.stock - req.quantity)    
                    opd2_drug.status = opd2_drug.stock - opd2_drug.low_stock_threshold
                    opd2_drug.save()

                    # 4. Update ProductRequest
                    req.staff2 = request.user.fullname
                    req.status = 1
                    req.save()

                    # 5 update Drugs
                    product.stock += req.quantity
                    product.status = product.stock - product.low_stock_threshold
                    product.save()

            return JsonResponse({"success": True})
        except Exception as e:
            return JsonResponse({"success": False, "error": str(e)})
    return JsonResponse({"success": False, "error": "Invalid request"})


@login_required(login_url='login')
@csrf_exempt
@transaction.atomic()
def opd2_decline_inventory_request(request, pk):
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


@login_required(login_url='login')
def request_history_to_opd2(request):
    opd2_history = ProductRequests.objects.filter(source='inventory',destination='opd2_pharm')
    page = 'history-of-inventory-requests-to-opd2'
    contxt = {
        'opd2_history':opd2_history,
        'page':page,
        }
    return render(request,'OPD_pharm2/opd2_request_from_inventory.html',contxt)

# End of untouched opd2 requests: From OPD Pharmacy 2 to Inventory
 

 # Patient waiting List
def fetch_opd2pharm_queue(request):
    queue = OPD2AdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24)
    ).select_related('patient', 'staff').order_by('patient_id', '-created_date')
    
    data = []
    seen_patients = set()
    
    for record in queue:
        patient = record.patient
        if not patient or patient.id in seen_patients:
            continue
            
        seen_patients.add(patient.id)
        data.append({
            'patient_id': patient.id,
            'name': f"{patient.surname} {patient.other_name} {patient.first_name}",
            'hospital_number': f"{patient.hospital_number}",
            'category': f"{patient.category}",
            'plan': f"{patient.plan}",
            'attendant': f"{record.staff.fullname}" if record.staff else "N/A",
            'created_date': record.created_date.strftime('%Y-%m-%d %H:%M'),
        })

    return JsonResponse({
        'data': data,
        'count': len(data)
    })


def load_opd2pharm_queue(request):
    page = 'opd2-queue'
    context = {
        'page':page
    }
    return render(request,'OPD_pharm2/opd2_queue_pharm.html',context)

def opd2pharm_waiting_count(request):
    count = OPD2AdministeredDrugs.objects.filter(
        pharm_waiting_status=0,
        billing_waiting_status=0,
        created_date__gte=timezone.now() - timedelta(hours=24),
        patient__isnull=False  # Exclude records without patients
    ).values('patient').distinct().count()

    return JsonResponse({'count': count})

# Dispense the prescribed drugs

@login_required
def opd2_doctor_prescriptions(request, patient_id):
    # Filter drugs where pharm_waiting_status = 0 (pending pharmacy approval)
    patient = get_object_or_404(PatientProfile, id=patient_id)
    prescribed_drugs = OPD2AdministeredDrugs.objects.filter(
        patient_id=patient_id,
        pharm_waiting_status=0
    ).select_related('product')

    context = {
        'prescribed_drugs': prescribed_drugs,
        'patient_id': patient_id,
        'patient':patient,
        'page':'opd2-doctor-prescriptions'
    }
    return render(request, 'OPD_pharm2/opd2_prescribed_drugs.html', context)

@csrf_exempt  
@login_required
def opd2_approve_prescription(request):
    print("Approve endpoint called")  
    print(f"Request method: {request.method}")  
    print(f"Request POST data: {request.POST}")  
    
    if request.method == 'POST':
        try:
            # Try to get data from JSON if not in POST
            try:
                data = json.loads(request.body)
                prescription_id = data.get('prescription_id')
            except:
                prescription_id = request.POST.get('prescription_id')
            
            print(f"Prescription ID: {prescription_id}")  
            
            if not prescription_id:
                return JsonResponse({
                    'success': False,
                    'message': 'No prescription ID provided'
                }, status=400)
            
            prescription = get_object_or_404(OPD2AdministeredDrugs, id=prescription_id)
            print(f"Found prescription: {prescription}")  
            
            # Update pharm_waiting_status to 1 (approved)
            prescription.pharm_waiting_status = 1
            prescription.pharm_staff = request.user.fullname
            prescription.save()
            
            print("Prescription saved successfully")  
            
            return JsonResponse({
                'success': True,
                'message': 'Prescription approved successfully'
            })
        except Exception as e:
            print(f"Error in approve_prescription: {str(e)}")  
            import traceback
            traceback.print_exc()  # Print full traceback to console
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            }, status=500)
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

@csrf_exempt  
@login_required
def opd2_decline_prescription(request):
    print("Decline endpoint called")  
    print(f"Request method: {request.method}")  
    
    if request.method == 'POST':
        try:
            # Try to get data from JSON if not in POST
            try:
                data = json.loads(request.body)
                prescription_id = data.get('prescription_id')
            except:
                prescription_id = request.POST.get('prescription_id')
            
            print(f"Prescription ID: {prescription_id}")  
            
            if not prescription_id:
                return JsonResponse({
                    'success': False,
                    'message': 'No prescription ID provided'
                }, status=400)
            
            prescription = get_object_or_404(OPD2AdministeredDrugs, id=prescription_id)
            print(f"Found prescription: {prescription}")  
            
            # Get quantity to return to stock
            quantity_to_return = prescription.quantity
            print(f"Quantity to return: {quantity_to_return}")  
            
            # Update drug stock if product exists
            if prescription.product:
                drug = prescription.product
                print(f"Drug before update - Stock: {drug.stock}")  
                drug.stock += quantity_to_return
                drug.save()
                print(f"Drug after update - Stock: {drug.stock}")  
            
            # Delete the prescription record
            prescription_id_for_response = prescription.id
            prescription.delete()
            print("Prescription deleted successfully")  
            
            return JsonResponse({
                'success': True,
                'message': 'Prescription declined and stock updated',
                'prescription_id': prescription_id_for_response
            })
        except Exception as e:
            print(f"Error in decline_prescription: {str(e)}")  
            import traceback
            traceback.print_exc()  # Print full traceback to console
            return JsonResponse({
                'success': False,
                'message': f'Error: {str(e)}'
            }, status=500)
    return JsonResponse({'success': False, 'message': 'Invalid request method'}, status=400)

@login_required
def opd2_dispense_history(request, patient_id):
    page = 'opd2-dispense'
    # Filter drugs where pharm_waiting_status = 0 (pending pharmacy approval)
    patient = get_object_or_404(PatientProfile, id=patient_id)
    dispensed_drugs = OPD2AdministeredDrugs.objects.filter(
        patient_id=patient_id,
        pharm_waiting_status=1
    ).select_related('product')

    context = {
        'dispensed_drugs': dispensed_drugs,
        'patient_id': patient_id,
        'page':page,
        'patient':patient,
    }
    return render(request, 'OPD_pharm2/opd2_prescribed_drugs.html', context)


@login_required
def opd2_download_prescriptions_today(request, patient_id):
    page = 'opd2_download_prescription_today'
    patient = get_object_or_404(PatientProfile, id=patient_id)
    dispensed_drugs = OPD2AdministeredDrugs.objects.filter(
        patient=patient,
        pharm_waiting_status=1,
        created_date__gte=timezone.now() - timedelta(hours=24)
    )

    context = {
        'dispensed_drugs_today': dispensed_drugs,
        'page':page,
        'patient':patient,
        'date_printed': timezone.now()
    }
    return render(request, 'OPD_pharm2/opd2_download_prescriptions.html', context)

@login_required
def opd2_download_prescriptions(request, patient_id):
    page = 'opd2_download_prescription'
    patient = get_object_or_404(PatientProfile, id=patient_id)
    dispensed_drugs = OPD2AdministeredDrugs.objects.filter(
        patient=patient,
        pharm_waiting_status=1
    )

    context = {
        'dispensed_drugs': dispensed_drugs,
        'page':page,
        'patient':patient,
        'date_printed': timezone.now()
    }
    return render(request, 'OPD_pharm2/opd2_download_prescriptions.html', context)


def generate_opd2_prescription_pdf(patient, records, request):
    """Generate PDF for opd presriptions using reportlab"""
    buffer = BytesIO()
    
    doc = SimpleDocTemplate(buffer, pagesize=A4, 
                           rightMargin=36, leftMargin=36,
                           topMargin=50, bottomMargin=50)
    
    styles = getSampleStyleSheet()
    story = []
    
    cell_style = ParagraphStyle(
        'CellStyle',
        parent=styles['Normal'],
        fontSize=9,
        leading=11,
        wordWrap='CJK'  # Better wrapping
    )
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=16,
        textColor=colors.HexColor('#2c3e50'),
        alignment=1,
        spaceAfter=30
    )
    
    header_style = ParagraphStyle(
        'CustomHeader',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#7f8c8d'),
        alignment=1,
        spaceAfter=20
    )
    
    story.append(Paragraph("ISALU HOSPITALS LIMITED", title_style))
    story.append(Paragraph("Email: it@isaluhospitals.com | Phone: 08099902223", header_style))
    story.append(Spacer(1, 20))
    
    patient_data = [
        ['Patient Name:', patient.get_full_name(), 'Hospital #:', patient.hospital_number],
        ['Sponsor:', patient.plan.plan if patient.plan else 'N/A', 'Plan Type:', patient.category.category if patient.category else 'N/A'],
        ['Gender:', patient.gender or 'N/A', 'Age:', str(patient.get_age) if patient.get_age is not None else 'N/A'],
        ['Address:', patient.address or 'N/A', 'Phone:', patient.phone_number or 'N/A'],
    ]
    
    patient_table = Table(patient_data, colWidths=[100, 150, 100, 150])
    patient_table.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#2c3e50')),
        ('TEXTCOLOR', (2, 0), (2, -1), colors.HexColor('#2c3e50')),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))
    story.append(patient_table)
    story.append(Spacer(1, 20))
    
    story.append(Paragraph("DRUG PRESCRIPTIONS", title_style))
    story.append(Spacer(1, 10))
    
    if records:
        # Header row
        table_data = [['S/N', 'Medications', 'Instructions']]
        
        # Wrap long text in Paragraph so it actually wraps in the cell
        for idx, record in enumerate(records, 1):
            table_data.append([
                str(idx),
                Paragraph(str(record.get('test', 'N/A')), cell_style),      # Medications 
                Paragraph(str(record.get('result', 'N/A')), cell_style),   # Instructions 
            ])
        
        result_table = Table(table_data, colWidths=[35, 180, 308])
        result_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#34495e')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'LEFT'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 11),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.HexColor('#f8f9fa')),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#dee2e6')),
            ('FONTNAME', (0, 1), (-1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 1), (-1, -1), 9),
            ('TOPPADDING', (0, 1), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 8),
            ('ALIGN', (0, 1), (0, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'TOP'),  
            ('LEFTPADDING', (0, 0), (-1, -1), 6),
            ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ]))
        
        story.append(result_table)
        story.append(Spacer(1, 20))
        
        staff_name = "Unknown"
        if hasattr(request, 'user') and request.user.is_authenticated:
            staff_name = request.user.fullname
        
        story.append(Paragraph(f"Prepared by: {staff_name}", styles['Normal']))
        story.append(Spacer(1, 30))
        
        footer_style = ParagraphStyle('Footer', parent=styles['Normal'], fontSize=8, 
                                     textColor=colors.HexColor('#95a5a6'), alignment=1)
        current_datetime = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        story.append(Paragraph(f"Generated on: {current_datetime}", footer_style))
    
    doc.build(story)
    buffer.seek(0)
    return buffer


@csrf_exempt  
def send_opd2_prescription_email(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    try:
        data = json.loads(request.body)
        patient_id = data.get('patient_id')
        records = data.get('records', [])
        message = data.get('message', '')
        
        if not records:
            return JsonResponse({'success': False, 'error': 'No records selected'}, status=400)
        
        patient = PatientProfile.objects.get(id=patient_id)
        
        # Generate PDF 
        pdf_buffer = generate_opd2_prescription_pdf(patient, records, request)
        
        # Build email body
        current_time = time.localtime()  
        date_str = time.strftime("%Y-%m-%d", current_time)
        time_str = time.strftime("%Y%m%d_%H%M%S", current_time)
        datetime_str = time.strftime("%Y-%m-%d %H:%M:%S", current_time)
        
        email_body = f"""
            ISALU HOSPITALS LIMITED
            Email: it@isaluhospitals.com | Phone: 08099902223

            Dear {patient.get_full_name()},

            Please find attached your drug prescriptions as requested.

            {'Additional Message: ' + message if message else ''}

            Results Summary:
            - Total Drugs: {len(records)}
            - Date Generated: {datetime_str}

            For any questions or concerns, please contact our Department of Outpatient Pharmacy.

            Best regards,
            Department of Inpatient Pharmacy
            ISALU HOSPITALS LIMITED
        """
        
        email = EmailMessage(
            subject=f'Drug Prescriptions for {patient.get_full_name()} - {date_str}',
            body=email_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[patient.email_address],
            reply_to=['it@isaluhospitals.com'],
        )
        
        # Attach the PDF
        filename = f'prescriptions_{patient.hospital_number}_{time_str}.pdf'
        email.attach(filename, pdf_buffer.getvalue(), 'application/pdf')
        
        email.send()
        
        return JsonResponse({
            'success': True, 
            'message': f'Drug Prescriptions sent to {patient.email_address}'
        })
        
    except PatientProfile.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Patient not found'}, status=404)
    except Exception as e:
        import traceback
        print("FULL ERROR:", traceback.format_exc())
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
    

def opd2_pharm_complete(request):
    page = 'opd2-completed'
    latest_per_patient = (
        OPD2AdministeredDrugs.objects
        .exclude(pharm_waiting_status=0)
        .filter(
            billing_waiting_status=0,
            created_date__gte=timezone.now() - timedelta(hours=24),
        )
        .values('patient_id')
        .annotate(latest_id=Max('id'))
        .values_list('latest_id', flat=True)
    )

    queue = (
        OPD2AdministeredDrugs.objects
        .filter(id__in=latest_per_patient)
        .select_related('patient')
        .order_by('-created_date')
    )
    
    context = {
        'queue':queue,
        'page':page,
        'counts':queue.count()
    }
    return render(request, 'OPD_pharm2/opd2_queue_pharm.html', context)

def opdpharm2_patient_profile(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    context = {
        'patient': patient,
        'page': 'opd2-patient-profile'
    }
    return render(request,'OPD_pharm2/opd2_operations_profile.html',context)