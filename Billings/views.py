from django.shortcuts import render, redirect, get_object_or_404
from django.conf import settings
from django.contrib import messages
from django.db import transaction
from inventory.decorators import department_required
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from datetime import datetime, timedelta, date, time
from django.db.models import Q, Sum, F, Case, When, Value, DecimalField, Max
from decimal import Decimal
from django.utils import timezone
import uuid 
import json
from .models import TransactionUpdate, Invoice, Receipt, Deposit, Refund
from patients.models import PatientProfile
from queue_operations.models import GetRegistrationFee,NurseWaitingList,OtherService
from IPD.models import AdmissionFee, AdmissionTable
from radio_lab.models import RadiologyLab
from IPD_pharm.models import IPDAdministeredDrugs
from IPD_pharm2.models import IPD2AdministeredDrugs
from IPD_pharm3.models import IPD3AdministeredDrugs
from OPD_pharm.models import OPDAdministeredDrugs
from OPD_pharm2.models import OPD2AdministeredDrugs
from .forms import DepositForm, RefundForm 
from reportlab.lib.units import inch
import qrcode
from io import BytesIO
import openpyxl
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, A4, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
import io
from django.views.decorators.csrf import csrf_exempt
from reportlab.pdfgen import canvas
from django.template.loader import render_to_string
from django.core.mail import EmailMessage
from django.views.decorators.http import require_POST
from collections import defaultdict
from haystack.query import SearchQuerySet
from openpyxl.styles import Font, Alignment, PatternFill
from openpyxl.utils import get_column_letter

today = date.today()
now = timezone.localtime(timezone.now())
time_threshold = timezone.now() - timedelta(hours=24)

import logging
logger = logging.getLogger(__name__)


def _apply_date_filter(queryset, request, date_field):
    """
    Apply a date range filter. Defaults to the last 24 hours if
    neither `date_from` nor `date_to` are provided.
    """
    date_from = request.GET.get('date_from', '').strip()
    date_to = request.GET.get('date_to', '').strip()

    logger.info(f"[date-filter] field={date_field} from={date_from!r} to={date_to!r}")

    if date_from or date_to:
        if date_from:
            try:
                d_from = datetime.strptime(date_from, '%Y-%m-%d').date()
                start = datetime.combine(d_from, time.min)
                if timezone.is_naive(start):
                    start = timezone.make_aware(start)
                queryset = queryset.filter(**{f'{date_field}__gte': start})
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid date_from '{date_from}': {e}")

        if date_to:
            try:
                d_to = datetime.strptime(date_to, '%Y-%m-%d').date()
                end = datetime.combine(d_to, time.max)
                if timezone.is_naive(end):
                    end = timezone.make_aware(end)
                queryset = queryset.filter(**{f'{date_field}__lte': end})
            except (ValueError, TypeError) as e:
                logger.warning(f"Invalid date_to '{date_to}': {e}")
    else:
        cutoff = timezone.now() - timedelta(hours=24)
        queryset = queryset.filter(**{f'{date_field}__gte': cutoff})

    logger.info(f"[date-filter] resulting SQL: {queryset.query}")
    return queryset


@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_transactions_all(request):
    page = 'awaiting-bills-all'
    awaiting_bills = TransactionUpdate.objects.filter(completed=0)
    # For awaiting bills
    awaiting_bills = _apply_date_filter(awaiting_bills, request, 'created_date')
    awaiting_bills = awaiting_bills.order_by('-created_date')

    context = {
        'awaiting_bills': awaiting_bills,
        'page': page,
    }
    return render(request, 'Billings/transactions_all.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_partially_paid_transactions_all(request):
    page = 'partially_paid-bills-all'

    # Base queryset of ALL partially paid records (completed=2)
    base_qs = TransactionUpdate.objects.filter(completed=2)
    base_qs = _apply_date_filter(base_qs, request, 'receipt_given_date')

    # Get the latest transaction per patient from the *filtered* set
    latest_tx_ids = (
        base_qs
        .values('patient')
        .annotate(latest_id=Max('id'))
        .values_list('latest_id', flat=True)
    )

    partially_paid_bills = (
        TransactionUpdate.objects.filter(id__in=latest_tx_ids)
        .select_related('patient', 'patient__category', 'patient__plan')
        .order_by('-receipt_given_date')
    )

    context = {
        'partially_paid_bills': partially_paid_bills,
        'page': page,
    }
    return render(request, 'Billings/transactions_all.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_completed_transactions_all(request):
    page = 'completed-bills-all'

    base_qs = TransactionUpdate.objects.filter(completed=1)
    base_qs = _apply_date_filter(base_qs, request, 'receipt_given_date')

    latest_tx_ids = (
        base_qs
        .values('patient')
        .annotate(latest_id=Max('id'))
        .values_list('latest_id', flat=True)
    )

    completed_bills = (
        TransactionUpdate.objects.filter(id__in=latest_tx_ids)
        .select_related('patient', 'patient__category', 'patient__plan')
        .order_by('-receipt_given_date')
    )

    context = {
        'completed_bills': completed_bills,
        'page': page,
    }
    return render(request, 'Billings/transactions_all.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_transactions_table_all(request):
    page = 'transaction-table-all'
    transaction_tables = TransactionUpdate.objects.all()
    transaction_tables = _apply_date_filter(transaction_tables, request, 'created_date')
    transaction_tables = transaction_tables.order_by('-receipt_given_date')

    context = {
        'transaction_tables': transaction_tables,
        'page': page,
    }
    return render(request, 'Billings/transactions_all.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_billings(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Only show records that are NOT paid and NOT cleared
    registration_fee = GetRegistrationFee.objects.filter(patient=patient, completed=0)
    consultation_fee = NurseWaitingList.objects.filter(patient=patient, completed=0)
    laboratory_fee = RadiologyLab.objects.filter(patient=patient, item_type='L', completed=0)
    radiology_fee = RadiologyLab.objects.filter(patient=patient, item_type='R', completed=0)
    ipdmedication_fee = IPDAdministeredDrugs.objects.filter(patient=patient, completed=0)
    ipd2medication_fee = IPD2AdministeredDrugs.objects.filter(patient=patient, completed=0)
    ipd3medication_fee = IPD3AdministeredDrugs.objects.filter(patient=patient, completed=0)
    opdmedication_fee = OPDAdministeredDrugs.objects.filter(patient=patient, completed=0)
    opd2medication_fee = OPD2AdministeredDrugs.objects.filter(patient=patient, completed=0)
    other_services_fee = OtherService.objects.filter(patient=patient, completed=0)
    admission_fee = AdmissionFee.objects.filter(patient=patient, completed=0)
    
    # Among these completed=0 records, find which ones already have an invoice
    # Invoice.completed=0 means invoice exists but no receipt yet
    invoiced_items = Invoice.objects.filter(
        patient=patient, 
        completed=0  
    ).values_list('original_source_model', 'original_source_id')
    
    # Set for template lookup: {"NurseWaitingList,12", "AdmissionFee,5", ...}
    invoiced_set = set([f"{model},{obj_id}" for model, obj_id in invoiced_items])

    deposits = Deposit.objects.filter(patient=patient)
    total = deposits.aggregate(total_amount=Sum('amount'))
    total_deposits = total['total_amount'] or 0

    can_reset_invoice = TransactionUpdate.objects.filter(
        patient=patient,
        invoice_ids__isnull=False,  
        receipt_ids__isnull=True     
    ).exists()

    context = {
        'patient':patient,
        'registration_fee':registration_fee,
        'consultation_fee':consultation_fee,
        'laboratory_fee':laboratory_fee,
        'radiology_fee':radiology_fee,
        'ipdmedication_fee':ipdmedication_fee,
        'ipd2medication_fee':ipd2medication_fee,
        'ipd3medication_fee':ipd3medication_fee,
        'opdmedication_fee':opdmedication_fee,
        'opd2medication_fee':opd2medication_fee,
        'other_services_fee':other_services_fee,
        'admission_fee':admission_fee,
        'current_user': request.user,
        'patient_category_name': patient.category,
        'total_deposits':total_deposits,
        'can_reset_invoice':can_reset_invoice,
        'invoiced_set': invoiced_set,
    }
    return render(request, 'Billings/create_bills.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def create_invoice(request, patient_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)

    patient = get_object_or_404(PatientProfile, id=patient_id)
    staff = request.user

    data = json.loads(request.body)
    selected_items_data = data.get('selected_items', [])
    pin_code = data.get('pin_code')
    global_payment_option = data.get('payment_option') or data.get('payment_type')
    # if not global_payment_option and selected_items_data:
    #     global_payment_option = selected_items_data[0].get('payment_option')

    # if global_payment_option:
    #     global_payment_option = str(global_payment_option).strip()

    # ALLOWED_PAYMENT_OPTIONS = ['Cash','Claim','Transfer','POS','Cheque','Bank Deposit','Staff Salary','Other','Capitation']

    # if not global_payment_option:
    #     return JsonResponse({'status': 'error', 'message': 'Payment Option is required. Please select a payment option.'}, status=400)

    # --- Allowed options ---
    ALLOWED_PAYMENT_OPTIONS = [
        'Cash', 'Claim', 'Transfer', 'POS', 
        'Cheque', 'Bank Deposit', 'Staff Salary', 'Other',
        'Capitation' # keep for backward compatibility
    ]

    # --- PIN Auth ---
    if not pin_code:
        return JsonResponse({'status': 'error', 'message': 'PIN code is required.'}, status=400)
    try:
        if staff.pin != int(pin_code):
            return JsonResponse({'status': 'error', 'message': 'Incorrect PIN input.'}, status=403)
    except (ValueError, TypeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid PIN format.'}, status=400)

    if not selected_items_data:
        return JsonResponse({'status': 'error', 'message': 'No items selected.'}, status=400)

    # ---  Payment Option Validation ---
    if not global_payment_option or str(global_payment_option).strip() == "":
        return JsonResponse({'status': 'error', 'message': 'Payment Option is required. Please select a payment option.'}, status=400)
    
    if global_payment_option not in ALLOWED_PAYMENT_OPTIONS:
        return JsonResponse({'status': 'error', 'message': f'Invalid Payment Option: {global_payment_option}'}, status=400)

    # Outstanding invoice check
    outstanding_transaction = TransactionUpdate.objects.select_for_update().filter(
        patient=patient, invoice_ids__isnull=False, receipt_ids__isnull=True,
    ).first()
    if outstanding_transaction:
        return JsonResponse({
            'status': 'error',
            'message': f'An outstanding invoice ({outstanding_transaction.invoice_ids}) needs to be cleared first.'
        }, status=403)

    total_invoiced_items = len(selected_items_data)
    total_available_items = (
        GetRegistrationFee.objects.filter(patient=patient, completed=0).count() +
        NurseWaitingList.objects.filter(patient=patient, completed=0).count() +
        RadiologyLab.objects.filter(patient=patient, completed=0).count() +
        IPDAdministeredDrugs.objects.filter(patient=patient, completed=0).count() +
        IPD2AdministeredDrugs.objects.filter(patient=patient, completed=0).count() +
        IPD3AdministeredDrugs.objects.filter(patient=patient, completed=0).count() +
        OPDAdministeredDrugs.objects.filter(patient=patient, completed=0).count() +
        OPD2AdministeredDrugs.objects.filter(patient=patient, completed=0).count() +
        OtherService.objects.filter(patient=patient, completed=0).count() +
        AdmissionFee.objects.filter(patient=patient, completed=0).count()
    )

    transaction_qs = TransactionUpdate.objects.select_for_update().filter(
        patient=patient, invoice_ids__isnull=True, receipt_ids__isnull=True,
    ).order_by('-updated_date')
    
    transaction_to_operate_on = transaction_qs.first()
    create_new = transaction_to_operate_on is None
    if transaction_to_operate_on and transaction_qs.count() > 1:
        transaction_qs.exclude(pk=transaction_to_operate_on.pk).delete()

    invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
    total_amount = 0.0
    invoices_to_create = []

    try:
        for item_data in selected_items_data:
            payment_option = global_payment_option or item_data.get('payment_option')
            
            if not payment_option:
                return JsonResponse({'status': 'error', 'message': 'Payment Option is required for all items.'}, status=400)

            price = float(item_data.get('total'))

            invoices_to_create.append(Invoice(
                patient=patient,
                invoice_number=invoice_number,
                product=item_data.get('product'),
                qty=item_data.get('qty'),
                discount=item_data.get('discount', 0),
                price=price, # price as total amount after discount
                payment_option=payment_option, 
                category=patient.category,
                staff=staff,
                completed=0,
                original_source_model=item_data.get('original_model'),
                original_source_id=item_data.get('original_id'),
            ))
            total_amount += price
    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error processing items: {str(e)}'}, status=500)

    Invoice.objects.bulk_create(invoices_to_create)

    if create_new:
        TransactionUpdate.objects.create(
            patient=patient, invoice_ids=invoice_number,
            invoice_raised=total_amount, staff=staff,
            updated_date=timezone.now(),
            total_available_items=total_available_items,
            total_invoiced_items=total_invoiced_items,
        )
    else:
        transaction_to_operate_on.invoice_ids = invoice_number
        transaction_to_operate_on.invoice_raised = total_amount
        transaction_to_operate_on.staff = staff
        transaction_to_operate_on.updated_date = timezone.now()
        transaction_to_operate_on.total_available_items = total_available_items
        transaction_to_operate_on.total_invoiced_items = total_invoiced_items
        transaction_to_operate_on.save()

    return JsonResponse({'status': 'success', 'message': f'Invoice {invoice_number} created.', 'invoice_number': invoice_number})


@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def reset_invoice(request, patient_id):
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)

    if not request.user.is_authenticated:
        return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=401)

    patient = get_object_or_404(PatientProfile, id=patient_id)
    staff = request.user

    data = json.loads(request.body)
    pin_code = data.get('pin_code')

    if not pin_code:
        return JsonResponse({'status': 'error', 'message': 'PIN code is required.'}, status=400)
    try:
        if staff.pin != int(pin_code):
            return JsonResponse({'status': 'error', 'message': 'Incorrect PIN input.'}, status=403)
    except (ValueError, TypeError, AttributeError):
        return JsonResponse({'status': 'error', 'message': 'Invalid PIN format or user PIN not set.'}, status=400)

    # --- Find outstanding invoice with lock ---
    # Don't filter by completed, and handle duplicates
    transaction_qs = TransactionUpdate.objects.select_for_update().filter(
        patient=patient,
        invoice_ids__isnull=False,
        receipt_ids__isnull=True,
    ).order_by('-updated_date')

    if not transaction_qs.exists():
        return JsonResponse({
            'status': 'error',
            'message': 'No outstanding invoice found to reset for this patient. It might already be paid or cleared.'
        }, status=404)

    transaction_to_reset = transaction_qs.first()
    invoice_number_to_reset = transaction_to_reset.invoice_ids

    # If duplicates, keep only the latest one we are resetting
    if transaction_qs.count() > 1:
        transaction_qs.exclude(pk=transaction_to_reset.pk).delete()

    invoice_items_to_revert = Invoice.objects.filter(
        patient=patient,
        invoice_number=invoice_number_to_reset,
        completed=0  # only reset unbilled invoices
    )

    if not invoice_items_to_revert.exists():
        # Fallback: try without completed filter
        invoice_items_to_revert = Invoice.objects.filter(
            patient=patient,
            invoice_number=invoice_number_to_reset,
        )
        if not invoice_items_to_revert.exists():
            return JsonResponse({
                'status': 'error',
                'message': f'No invoice items found for {invoice_number_to_reset}.'
            }, status=404)

    try:
        model_mapping = {
            'GetRegistrationFee': GetRegistrationFee,
            'NurseWaitingList': NurseWaitingList,
            'AdmissionFee': AdmissionFee,
            'RadiologyLab': RadiologyLab,
            'IPDAdministeredDrugs': IPDAdministeredDrugs,
            'IPD2AdministeredDrugs': IPD2AdministeredDrugs,
            'IPD3AdministeredDrugs': IPD3AdministeredDrugs,
            'OPDAdministeredDrugs': OPDAdministeredDrugs,
            'OPD2AdministeredDrugs': OPD2AdministeredDrugs,
            'OtherService': OtherService,
        }

        for item in invoice_items_to_revert:
            if item.original_source_model and item.original_source_id:
                model_class = model_mapping.get(item.original_source_model)
                if model_class:
                    model_class.objects.filter(id=item.original_source_id).update(completed=0)
            # delete invoice row
            item.delete()

        # Reset the TransactionUpdate back to open state
        transaction_to_reset.invoice_ids = None
        transaction_to_reset.invoice_raised = 0
        transaction_to_reset.receipt_ids = None
        transaction_to_reset.receipt_given = 0
        transaction_to_reset.staff = staff
        transaction_to_reset.updated_date = timezone.now()
        if hasattr(transaction_to_reset, 'completed'):
            transaction_to_reset.completed = 0
        transaction_to_reset.save()

        return JsonResponse({
            'status': 'success', 
            'message': f'Invoice {invoice_number_to_reset} successfully reset.'
        })

    except Exception as e:
        return JsonResponse({'status': 'error', 'message': f'Error during reset: {str(e)}'}, status=500)


@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def clear_transactions(request, patient_id):
    if request.method == 'POST':
        # Ensure user is authenticated
        if not request.user.is_authenticated:
            return JsonResponse({'status': 'error', 'message': 'Authentication required.'}, status=401)

        patient = get_object_or_404(PatientProfile, id=patient_id)
        staff = request.user

        data = json.loads(request.body)
        unchecked_items_data = data.get('unchecked_items', [])
        pin_code = data.get('pin_code')

        # --- PIN Authentication ---
        if not pin_code:
            return JsonResponse({'status': 'error', 'message': 'PIN code is required.'}, status=400)
        try:
            if staff.pin != int(pin_code):
                return JsonResponse({'status': 'error', 'message': 'Incorrect PIN input.'}, status=403)
        except (ValueError, TypeError):
            return JsonResponse({'status': 'error', 'message': 'Invalid PIN format or user PIN not set.'}, status=400)
        except AttributeError:
            return JsonResponse({'status': 'error', 'message': 'User does not have a PIN set or it is inaccessible.'}, status=500)

        message = "Transactions cleared successfully."

        # Case 1: Unchecked records exist (meaning some records were not invoiced)
        if unchecked_items_data:
            model_mapping = {
                'GetRegistrationFee': GetRegistrationFee,
                'NurseWaitingList': NurseWaitingList,
                'AdmissionFee': AdmissionFee,
                'RadiologyLab': RadiologyLab,
                'IPDAdministeredDrugs': IPDAdministeredDrugs,
                'IPD2AdministeredDrugs': IPD2AdministeredDrugs,
                'IPD3AdministeredDrugs': IPD3AdministeredDrugs,
                'OPDAdministeredDrugs': OPDAdministeredDrugs,
                'OPD2AdministeredDrugs': OPD2AdministeredDrugs,
                'OtherService': OtherService,
            }
            
            try:
                for item_data in unchecked_items_data:
                    original_id = item_data.get('original_id')
                    original_model = item_data.get('original_model')

                    if original_id and original_model:
                        model_class = model_mapping.get(original_model)
                        if model_class:
                            model_class.objects.filter(id=original_id).update(completed=2) # Set completed=2 for unchecked
                        else:
                            print(f"Warning: Unknown model type '{original_model}' for ID {original_id}. Update skipped.")
            except Exception as e:
                return JsonResponse({'status': 'error', 'message': f'Error updating individual records: {str(e)}'}, status=500)
            message = "Unchecked transactions marked as cleared."
        else:
            message = "No unchecked individual transactions to clear, updating TransactionUpdate status."

        # Update ALL relevant TransactionUpdate records for the patient ---
        try:

            updated_count = TransactionUpdate.objects.filter(
                patient=patient,
                # receipt_ids__isnull=True # Target records that haven't been receipted yet
            ).update(
                completed=1, 
                staff=staff, 
                updated_date=timezone.now() 
            )
            
            if updated_count == 0:
                print(f"No existing TransactionUpdate records found or updated for patient {patient.id} with receipt_ids__isnull=True.")

            else:
                print(f"Updated {updated_count} TransactionUpdate records for patient {patient.id}.")

        except Exception as e:
            return JsonResponse({'status': 'error', 'message': f'Error updating TransactionUpdate records: {str(e)}'}, status=500)
        
        return JsonResponse({'status': 'success', 'message': message})
    
    return JsonResponse({'status': 'error', 'message': 'Invalid request method.'}, status=405)



@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_invoice(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    # Get ccount balance
    deposits = Deposit.objects.filter(patient=patient)
    total = deposits.aggregate(total_amount=Sum('amount'))
    total_deposits = total['total_amount'] or 0
     
    distinct_invoices = Invoice.objects.filter(patient=patient).values(
    'invoice_number'
        ).annotate(
            latest_date=Max('created_date'),
            staff_name=Max('staff__fullname'),
        ).order_by('-latest_date')

    # Creating a dictionary to store processed invoice items for each invoice number
    invoice_data = {}
    
    # Process each distinct invoice
    for inv in distinct_invoices:
        invoice_number = inv['invoice_number']
        
        # Get all items for this specific invoice number
        invoice_items = Invoice.objects.filter(
            patient=patient, 
            invoice_number=invoice_number,
            # completed=1
        ).order_by('created_date')
        
        processed_items = []
        total_amount = 0
        
        for item in invoice_items:
            total_amount += item.price
            
            original_rate = 0
            discount_amount = 0

            if item.qty > 0:
                discount_factor = (1 - item.discount / 100.0)
                if discount_factor != 0:
                    original_rate = item.price / (item.qty * discount_factor)
                    discount_amount = original_rate * item.qty * (item.discount / 100.0)
                else:
                    if item.price == 0 and item.discount == 100:
                        original_rate = 0
                        discount_amount = 0
                    else:
                        original_rate = 0
                        discount_amount = 0

            item.calculated_original_rate = original_rate
            item.calculated_discount_amount = discount_amount
            processed_items.append(item)
        
        # Store processed data for this invoice
        invoice_data[invoice_number] = {
            'items': processed_items,
            'total_amount': total_amount,
            'net_bill_amount': total_amount,
            'created_date': inv['latest_date'],
            'staff_name': inv['staff_name']
        }

    context = {
        'patient': patient,
        'distinct_invoices': distinct_invoices,
        'total_deposits':total_deposits,
        'invoice_data': invoice_data,
    }
    return render(request, 'Billings/total_invoice.html', context)


@csrf_exempt
@csrf_exempt
def save_signature(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        invoice_number = data.get('invoice_number')
        signer_name = data.get('signer_name')
        signature_data = data.get('signature_data')
        
        return JsonResponse({'success': True, 'message': 'Signature saved successfully'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@csrf_exempt
def send_qr_code(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        invoice_number = data.get('invoice_number')
        email = data.get('email')
        
        try:
            # Get invoice data
            invoices = Invoice.objects.filter(invoice_number=invoice_number)
            if not invoices.exists():
                return JsonResponse({'success': False, 'message': 'Invoice not found'})
            
            patient = invoices.first().patient
            total_amount = sum(invoice.price for invoice in invoices)
            created_date = invoices.first().created_date
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            
            qr_data = f"""
            Invoice #{invoice_number}
            Patient: {patient.get_full_name()}
            Hospital Number: {patient.hospital_number}
            Total Amount: ₦{total_amount}
            Date: {created_date.strftime('%Y-%m-%d %H:%M')}
            ISALU HOSPITALS LIMITED
            """
            
            qr.add_data(qr_data)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Save QR code to bytes
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            # Create email with attachment
            from django.core.mail import EmailMultiAlternatives
            from email.mime.image import MIMEImage
            
            subject = f'QR Code for Invoice #{invoice_number}'
            
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        line-height: 1.6;
                        color: #333;
                        max-width: 600px;
                        margin: 0 auto;
                        padding: 20px;
                    }}
                    .header {{
                        text-align: center;
                        padding: 20px;
                        background-color: #f8f9fa;
                        border-radius: 10px;
                        margin-bottom: 20px;
                    }}
                    .header h2 {{
                        color: #007bff;
                        margin: 0;
                    }}
                    .invoice-details {{
                        background-color: #fff;
                        border: 1px solid #ddd;
                        border-radius: 10px;
                        padding: 20px;
                        margin: 20px 0;
                    }}
                    .qr-container {{
                        text-align: center;
                        margin: 30px 0;
                        padding: 20px;
                        background-color: #f8f9fa;
                        border-radius: 10px;
                    }}
                    .qr-container img {{
                        max-width: 200px;
                        height: auto;
                        border: 1px solid #ddd;
                        padding: 10px;
                        background-color: white;
                    }}
                    .footer {{
                        text-align: center;
                        margin-top: 30px;
                        padding: 20px;
                        font-size: 12px;
                        color: #666;
                        border-top: 1px solid #eee;
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>ISALU HOSPITALS LIMITED</h2>
                    <p>Email: it@isaluhospitals.com | Phone: 08099902223</p>
                </div>
                
                <div class="invoice-details">
                    <h3 style="color: #007bff;">Invoice QR Code</h3>
                    <p><strong>Invoice Number:</strong> #{invoice_number}</p>
                    <p><strong>Patient Name:</strong> {patient.get_full_name()}</p>
                    <p><strong>Hospital Number:</strong> {patient.hospital_number}</p>
                    <p><strong>Total Amount:</strong> ₦{total_amount:,.2f}</p>
                    <p><strong>Date:</strong> {created_date.strftime('%d %B %Y %H:%M')}</p>
                </div>
                
                <div class="qr-container">
                    <h4>Scan this QR Code for Invoice Verification</h4>
                    <img src="cid:invoice_qr_code" alt="QR Code for Invoice #{invoice_number}">
                    <p><small>Scan this QR code to verify your invoice</small></p>
                </div>
                
                <div class="footer">
                    <p>This is an automated message from ISALU HOSPITALS LIMITED.</p>
                    <p>Please keep this invoice for your records.</p>
                </div>
            </body>
            </html>
            """
            
            # Create email with attachment
            email_message = EmailMultiAlternatives(
                subject=subject,
                body=f"Please find attached the QR code for Invoice #{invoice_number}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email]
            )
            
            # Attach HTML content
            email_message.attach_alternative(html_content, "text/html")
            
            # Attach QR code image as inline attachment
            img_data = buffer.getvalue()
            mime_image = MIMEImage(img_data)
            mime_image.add_header('Content-ID', '<invoice_qr_code>')
            mime_image.add_header('Content-Disposition', 'inline', filename=f'invoice_{invoice_number}_qr.png')
            email_message.attach(mime_image)
            
            # Also attach QR code as a downloadable file
            email_message.attach(f'invoice_{invoice_number}_qr.png', img_data, 'image/png')
            
            # Send email
            email_message.send()
            
            buffer.close()
            
            return JsonResponse({'success': True, 'message': f'QR Code sent successfully to {email}'})
            
        except Exception as e:
            print(f"Error sending QR code email: {str(e)}")
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})



def download_invoice(request, invoice_number, format):
    # Fetch invoice data
    invoices = Invoice.objects.filter(invoice_number=invoice_number)
    patient = invoices.first().patient if invoices.exists() else None
    
    if format == 'pdf':
        # Create a file-like buffer to receive PDF data
        buffer = io.BytesIO()
        
        # Create the PDF object, using the buffer as its "file"
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
        
        # Container for the 'Flowable' objects
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=TA_CENTER,
            spaceAfter=12
        )
        center_style = ParagraphStyle(
            'Center',
            parent=styles['Normal'],
            alignment=TA_CENTER,
            spaceAfter=6
        )
        right_style = ParagraphStyle(
            'Right',
            parent=styles['Normal'],
            alignment=TA_RIGHT,
            spaceAfter=6
        )
        normal_style = styles['Normal']
        
        # Hospital Header
        elements.append(Paragraph("ISALU HOSPITALS LIMITED", title_style))
        elements.append(Paragraph("Email: it@isaluhospitals.com", center_style))
        elements.append(Paragraph("Phone: 08099902223", center_style))
        elements.append(Spacer(1, 12))
        
        # Invoice Meta
        elements.append(Paragraph(f"BILL #: <b>{invoice_number}</b>", right_style))
        elements.append(Paragraph(f"{datetime.now().strftime('%d %B %Y %H:%M')}", right_style))
        elements.append(Spacer(1, 12))
        
        # Patient Information
        if patient:
            patient_info = f"""
            <b>PATIENT INFORMATION:</b><br/>
            Name: <b>{patient.get_full_name()}</b> [{patient.hospital_number}]<br/>
            Sponsor: <b>{patient.plan.plan if patient.plan else 'N/A'}</b><br/>
            Plan Type: <b>{patient.category.category if patient.category else 'N/A'}</b><br/>
            Policy Number: <b>{patient.insurance_policy_number or 'NIL'}</b><br/>
            Address: <b>{patient.address or 'N/A'}</b><br/>
            Phone: <b>{patient.phone_number or 'N/A'}</b><br/>
            Gender: <b>{patient.gender or 'N/A'}</b>
            """
            elements.append(Paragraph(patient_info, normal_style))
            elements.append(Spacer(1, 20))
        
        # Invoice Title
        elements.append(Paragraph("INVOICE", title_style))
        elements.append(Spacer(1, 12))
        
        # Table Data
        table_data = [['S/N', 'Description', 'Qty', 'Rate (₦)', 'Discount (%)', 'Amount (₦)']]
        total_amount = 0
        
        for idx, item in enumerate(invoices, 1):
            # Calculate original rate
            original_rate = 0
            if item.qty > 0:
                discount_factor = (1 - item.discount / 100.0)
                if discount_factor != 0:
                    original_rate = item.price / (item.qty * discount_factor)
            
            table_data.append([
                str(idx),
                item.product[:30] + '...' if len(item.product) > 30 else item.product,
                str(item.qty),
                f"{original_rate:.2f}",
                f"{item.discount:.2f}%",
                f"{item.price:.2f}"
            ])
            total_amount += item.price
        
        # Create table
        table = Table(table_data, colWidths=[0.5*inch, 2.5*inch, 0.5*inch, 1*inch, 1*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('ALIGN', (2, 1), (2, -1), 'CENTER'),  # Qty column
            ('ALIGN', (3, 1), (5, -1), 'RIGHT'),   # Rate, Discount, Amount columns
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 20))
        
        # Totals
        totals_data = [
            ['Total:', f'₦{total_amount:.2f}'],
            ['Total Bill Amount:', f'₦{total_amount:.2f}'],
            ['Net Bill Amount:', f'₦{total_amount:.2f}']
        ]
        
        totals_table = Table(totals_data, colWidths=[2*inch, 1.5*inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'RIGHT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
            ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
        ]))
        
        elements.append(totals_table)
        
        # Build PDF
        doc.build(elements)
        
        # Get the value of the buffer
        pdf = buffer.getvalue()
        buffer.close()
        
        # Create response
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="invoice_{invoice_number}.pdf"'
        response.write(pdf)
        return response
    
    elif format == 'excel':
        # Generate Excel
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="invoice_{invoice_number}.xlsx"'
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Invoice #{invoice_number}"
        
        # Add headers
        headers = ['Description', 'Quantity', 'Rate', 'Discount', 'Amount']
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
        
        # Add data
        for row, item in enumerate(invoices, 2):
            ws.cell(row=row, column=1, value=item.product)
            ws.cell(row=row, column=2, value=item.qty)
            ws.cell(row=row, column=3, value=float(item.price / item.qty))
            ws.cell(row=row, column=4, value=item.discount)
            ws.cell(row=row, column=5, value=float(item.price))
        
        wb.save(response)
        return response
    
    return HttpResponse('Invalid format')



def generate_receipt_number():
    return f"RCPT-{uuid.uuid4().hex[:8].upper()}"

@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def create_receipt(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    total_deposits = 0
    if patient.plan.plan == 'Family':
        # Extract the family prefix
        family_prefix = patient.hospital_number[:-2]

        # Filter deposits where the hospital number starts with the family prefix
        family_deposits = Deposit.objects.filter(
            patient__hospital_number__startswith=family_prefix
        )

        # Calculate total family balance
        total_deposits = family_deposits.aggregate(
            total=Sum('amount')
        )['total'] or 0

    else:
        deposits = Deposit.objects.filter(patient=patient)
        total = deposits.aggregate(total_amount=Sum('amount'))
        total_deposits = total['total_amount'] or 0

    transaction_qs = TransactionUpdate.objects.select_for_update().filter(
        patient=patient,
        invoice_ids__isnull=False,
        receipt_ids__isnull=True
    ).order_by('-updated_date')

    if not transaction_qs.exists():
        return render(request, 'Billings/create_receipt.html', {
            'patient': patient,
            'cleared_invoices': [],
            'invoice_number_to_receipt': 'N/A',
            'bill_payable_amount': 0,
            'total_deposits': total_deposits,
            'original_payment_option': None,
            'error_message': 'No outstanding invoice found for this patient to generate a receipt.'
        })

    transaction_for_receipt = transaction_qs.first()
    
    # Clean duplicates if any
    if transaction_qs.count() > 1:
        transaction_qs.exclude(pk=transaction_for_receipt.pk).delete()

    invoice_number_to_receipt = transaction_for_receipt.invoice_ids
    bill_payable_amount = transaction_for_receipt.invoice_raised 

    cleared_invoices = Invoice.objects.filter(patient=patient, invoice_number=invoice_number_to_receipt)

    # - Capture payment option from invoice --
    original_payment_option = None
    if cleared_invoices.exists():
        # All items in one invoice should have same payment_option, take first
        original_payment_option = cleared_invoices.first().payment_option
    
    # original_payment_option = cleared_invoices.values('payment_option').annotate(c=Count('id')).order_by('-c').first()['payment_option']

    processed_invoices = []
    for item in cleared_invoices:
        original_rate = 0.0
        if item.qty > 0:
            discount_factor = (1.0 - float(item.discount) / 100.0)
            if discount_factor != 0:
                original_rate = float(item.price) / (float(item.qty) * discount_factor)
        item.calculated_original_rate = original_rate
        processed_invoices.append(item)
    
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            amount_paid = float(data.get("amount_paid", 0))
            remarks = data.get("remarks", "")
            invoice_number_from_post = data.get("invoice_number") 
            payment_type = data.get("payment_type") or original_payment_option or "Other"
            pin_code = data.get("pin_code")
            process_fund = data.get("process_fund")

            # PIN
            if not pin_code:
                return JsonResponse({"status": "error", "message": "PIN code is required"})
            try:
                if request.user.pin != int(pin_code):
                    return JsonResponse({"status": "error", "message": "Invalid PIN"})
            except:
                return JsonResponse({"status": "error", "message": "Invalid PIN format"})

            try:
                transaction = TransactionUpdate.objects.select_for_update().get(
                    patient=patient,
                    invoice_ids=invoice_number_from_post,
                    receipt_ids__isnull=True
                )
            except TransactionUpdate.DoesNotExist:
                return JsonResponse({"status": "error", "message": "Transaction not found or already receipted."})

            bill_payable = float(transaction.invoice_raised)
            is_hmo = patient.category.category == 'HMO' if patient.category else False
            
            if is_hmo:
                balance = 0
                deposit_amount_used = 0.0
                amount_paid = 0.0
                total_paid = 0.0
                payment_type = "HMO"
            else:
                current_deposit = family_deposits.aggregate(
                        total=Sum('amount')
                    )['total'] or 0
                
                deposit_amount_used = 0.0
                
                if process_fund == "fresh_payment":
                    if amount_paid <= 0:
                        return JsonResponse({"status": "error", "message": "Amount paid must be greater than 0 for Fresh Payment"})
                    balance = bill_payable - amount_paid
                elif process_fund == "my_deposit":
                    if current_deposit != bill_payable:
                        return JsonResponse({"status": "error", "message": "Error: Insufficient balance from patient's deposit"})
                    balance = 0
                    deposit_amount_used = bill_payable
                    amount_paid = 0
                    payment_type = "Deposit"
                elif process_fund == "deposit_and_fresh_payment":
                    if current_deposit == bill_payable:
                        deposit_amount_used = bill_payable
                        amount_paid = 0
                        balance = 0
                        payment_type = "Dep+Cash"
                    else:
                        deposit_amount_used = current_deposit
                        remaining = bill_payable - current_deposit
                        balance = remaining - amount_paid
                        payment_type = "Dep+Cash"
                        if amount_paid < remaining:
                            return JsonResponse({"status": "error", "message": f"Insufficient fresh payment. You need ₦{remaining:,.2f} more"})
                else:
                    return JsonResponse({"status": "error", "message": "Invalid fund processing method"})

                if balance != 0.00:
                    return JsonResponse({"status": "error", "message": "This account is not balanced"})
                total_paid = amount_paid + deposit_amount_used

            receipt_number = generate_receipt_number()
            Receipt.objects.create(
                patient=patient,
                invoice_number=invoice_number_from_post,
                receipt_number=receipt_number,
                remarks=remarks,
                total_price=total_paid,
                category=patient.category,
                staff=request.user,
                payment_type=original_payment_option
            )

            transaction.receipt_ids = receipt_number
            transaction.receipt_given = total_paid
            transaction.receipt_given_date = timezone.now()
            if transaction.total_available_items > 0 and transaction.total_invoiced_items == transaction.total_available_items:
                transaction.completed = 1
            else:
                transaction.completed = 2
            transaction.staff = request.user
            transaction.save()

            if not is_hmo and deposit_amount_used > 0:
                Deposit.objects.create(amount=-deposit_amount_used, payment_type="Withdrawal", patient=patient, staff=request.user)

            invoices_to_complete = Invoice.objects.filter(patient=patient, invoice_number=invoice_number_from_post)

            model_mapping = {
                'GetRegistrationFee': GetRegistrationFee, 'NurseWaitingList': NurseWaitingList,
                'AdmissionFee': AdmissionFee, 'RadiologyLab': RadiologyLab,
                'IPDAdministeredDrugs': IPDAdministeredDrugs, 'IPD2AdministeredDrugs': IPD2AdministeredDrugs,
                'IPD3AdministeredDrugs': IPD3AdministeredDrugs, 'OPDAdministeredDrugs': OPDAdministeredDrugs,
                'OPD2AdministeredDrugs': OPD2AdministeredDrugs, 'OtherService': OtherService,
            }
            admission_fee_found = False
            for item in invoices_to_complete:
                if item.original_source_id and item.original_source_model:
                    model_class = model_mapping.get(item.original_source_model)
                    if model_class:
                        model_class.objects.filter(id=item.original_source_id).update(completed=1)
                    if item.original_source_model == 'AdmissionFee':
                        admission_fee_found = True
            if admission_fee_found:
                AdmissionTable.objects.filter(patient=patient, bill_discharge_status=0).update(
                    bill_discharged=request.user.fullname, bill_discharge_status=1, bill_discharge_date=timezone.now()
                )
            invoices_to_complete.update(completed=1)
            return JsonResponse({"status": "success", "receipt_number": receipt_number})
            
        except Exception as e:
            return JsonResponse({"status": "error", "message": f"Server error: {str(e)}"})
    
    context = {
        'patient': patient,
        'total_deposits': total_deposits,
        'cleared_invoices': processed_invoices, 
        'invoice_number_to_receipt': invoice_number_to_receipt,
        'bill_payable_amount': bill_payable_amount,
        'is_hmo': patient.category.category == 'HMO' if patient.category else False,
        'original_payment_option': original_payment_option, 
    }
    return render(request, 'Billings/create_receipt.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def create_receipt_general(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)

    # Get account balance from Deposit model
    deposits = Deposit.objects.filter(patient=patient)
    total = deposits.aggregate(total_amount=Sum('amount'))
    total_deposits = total['total_amount'] or 0

    try:
        transaction_for_receipt = TransactionUpdate.objects.get(
            patient=patient,
            invoice_ids__isnull=False,
            receipt_ids__isnull=True
        )
        invoice_number_to_receipt = transaction_for_receipt.invoice_ids
        bill_payable_amount = transaction_for_receipt.invoice_raised 

    except TransactionUpdate.DoesNotExist:
        return render(request, 'Billings/create_receipt.html', {
            'patient': patient,
            'cleared_invoices': [],
            'invoice_number_to_receipt': 'N/A',
            'bill_payable_amount': 0,
            'total_deposits': total_deposits,
            'error_message': 'No outstanding invoice found for this patient to generate a receipt.'
        })
    except TransactionUpdate.MultipleObjectsReturned:
        return render(request, 'Billings/create_receipt.html', {
            'patient': patient,
            'cleared_invoices': [],
            'invoice_number_to_receipt': 'N/A',
            'bill_payable_amount': 0,
            'total_deposits': total_deposits,
            'error_message': 'Multiple outstanding invoices found for this patient. Please contact support.'
        })

    cleared_invoices = Invoice.objects.filter(patient=patient, invoice_number=invoice_number_to_receipt)
    
    original_payment_option = None
    if cleared_invoices.exists():
        original_payment_option = cleared_invoices.first().payment_option

    processed_invoices = []
    for item in cleared_invoices:
        original_rate = 0.0
        if item.qty > 0:
            discount_factor = (1.0 - float(item.discount) / 100.0)
            if discount_factor != 0:
                original_rate = float(item.price) / (float(item.qty) * discount_factor)
        item.calculated_original_rate = original_rate
        processed_invoices.append(item)
    

    if request.method == "POST":
        try:
            data = json.loads(request.body)

            amount_paid = float(data.get("amount_paid", 0))
            remarks = data.get("remarks", "")
            invoice_number_from_post = data.get("invoice_number") 
            payment_type = data.get("payment_type") or "Other"  
            pin_code = data.get("pin_code")
            process_fund = data.get("process_fund")

            # PIN AUTHENTICATION
            if not pin_code:
                return JsonResponse({"status": "error", "message": "PIN code is required"})
            try:
                if request.user.pin != int(pin_code):
                    return JsonResponse({"status": "error", "message": "Invalid PIN"})
            except:
                return JsonResponse({"status": "error", "message": "Invalid PIN format"})

            # GET TRANSACTION
            try:
                transaction = TransactionUpdate.objects.get(
                    patient=patient,
                    invoice_ids=invoice_number_from_post,
                    receipt_ids__isnull=True
                )
            except TransactionUpdate.DoesNotExist:
                return JsonResponse({"status": "error", "message": "Transaction not found or already receipted."})

            bill_payable = float(transaction.invoice_raised)
            
            # Get fresh deposit balance to avoid race conditions
            current_deposit = Deposit.objects.filter(patient=patient).aggregate(Sum('amount'))['amount__sum'] or 0

            # FUND PROCESSING LOGIC
            deposit_amount_used = 0.0
            
            if process_fund == "fresh_payment":
                # Case I: Fresh Payment only
                if amount_paid <= 0:
                    return JsonResponse({"status": "error", "message": "Amount paid must be greater than 0 for Fresh Payment"})
                balance = bill_payable - amount_paid
                    
            elif process_fund == "my_deposit":
                # Case II: From deposit only
                if current_deposit < bill_payable:
                    return JsonResponse({
                        "status": "error", 
                        "message": "Error: Insufficient balance from patient's deposit, try other method of fund processing"
                    })
                balance = 0
                deposit_amount_used = bill_payable
                amount_paid = 0
                payment_type = "Deposit"
                
            elif process_fund == "deposit_and_fresh_payment":
                # Case III: Deposit + Fresh Payment
                if current_deposit == bill_payable:
                    deposit_amount_used = bill_payable
                    amount_paid = 0
                    balance = 0
                    payment_type = "Deposit + Cash"
                else:
                    deposit_amount_used = current_deposit
                    remaining = bill_payable - current_deposit
                    balance = remaining - amount_paid
                    payment_type = "Deposit + Cash"
                    if amount_paid < remaining:
                        return JsonResponse({
                            "status": "error",
                            "message": f"Insufficient fresh payment. You need ₦{remaining:,.2f} more to balance the account"
                        })
            else:
                return JsonResponse({"status": "error", "message": "Invalid fund processing method selected"})

            # ACCOUNT MUST BE BALANCED
            if balance != 0.00:  # Allow 1 kobo rounding error
                return JsonResponse({"status": "error", "message": "This account is not balanced"})

            # CREATE RECEIPT
            receipt_number = generate_receipt_number()
            total_paid = amount_paid + deposit_amount_used

            Receipt.objects.create(
                patient=patient,
                invoice_number=invoice_number_from_post,
                receipt_number=receipt_number,
                remarks=remarks,
                total_price=total_paid,
                category=patient.category,
                staff=request.user,
                payment_type=original_payment_option
            )

            # UPDATE TRANSACTION
            transaction.receipt_ids = receipt_number
            transaction.receipt_given = total_paid
            transaction.receipt_given_date = timezone.now()

            if transaction.total_available_items > 0 and transaction.total_invoiced_items == transaction.total_available_items:
                transaction.completed = 1  # All selected -> fully paid
            else:
                transaction.completed = 2  # Partial selected -> marked as cleared
                
            transaction.staff = request.user
            transaction.save()

            # CREATE DEPOSIT ENTRY IF DEPOSIT WAS USED - NEGATED AMOUNT
            if deposit_amount_used > 0:
                Deposit.objects.create(
                    amount=-deposit_amount_used,  
                    payment_type="Withdrawal",
                    patient=patient,
                    staff=request.user,
                )

            invoices_to_complete = Invoice.objects.filter(
                patient=patient, 
                invoice_number=invoice_number_from_post,
            )

            model_mapping = {
                'GetRegistrationFee': GetRegistrationFee,
                'NurseWaitingList': NurseWaitingList,
                'AdmissionFee': AdmissionFee,
                'RadiologyLab': RadiologyLab,
                'IPDAdministeredDrugs': IPDAdministeredDrugs,
                'IPD2AdministeredDrugs': IPD2AdministeredDrugs,
                'IPD3AdministeredDrugs': IPD3AdministeredDrugs,
                'OPDAdministeredDrugs': OPDAdministeredDrugs,
                'OPD2AdministeredDrugs': OPD2AdministeredDrugs,
                'OtherService': OtherService,
            }

            admission_fee_found = False
            for item in invoices_to_complete:
                if item.original_source_id and item.original_source_model:
                    model_class = model_mapping.get(item.original_source_model)
                    if model_class:
                        model_class.objects.filter(id=item.original_source_id).update(completed=1)
                    
                    if item.original_source_model == 'AdmissionFee':
                        admission_fee_found = True
            
            # UPDATE AdmissionTable if AdmissionFee was part of invoice
            if admission_fee_found:
                AdmissionTable.objects.filter(
                    patient=patient,
                    bill_discharge_status=0 
                ).update(
                    bill_discharged=request.user.fullname, 
                    bill_discharge_status=1,
                    bill_discharge_date=timezone.now()
                )

            invoices_to_complete.update(completed=1)

            return JsonResponse({
                "status": "success",
                "receipt_number": receipt_number
            })
            
        except Exception as e:
            # catching the "unexpected error" and returns actual message
            print(f"ERROR in process_receipt: {str(e)}") 
            return JsonResponse({
                "status": "error",
                "message": f"Server error: {str(e)}"
            })
    
    context = {
        'patient': patient,
        'total_deposits': total_deposits,
        'cleared_invoices': processed_invoices, 
        'invoice_number_to_receipt': invoice_number_to_receipt,
        'bill_payable_amount': bill_payable_amount,
        'original_payment_option':original_payment_option
    }
    return render(request, 'Billings/create_receipt_general.html', context)


@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_receipt(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    # Get ccount balance
    deposits = Deposit.objects.filter(patient=patient)
    total = deposits.aggregate(total_amount=Sum('amount'))
    total_deposits = total['total_amount'] or 0

    # Get distinct receipts
    distinct_receipts = Receipt.objects.filter(patient=patient).values(
        'receipt_number'
    ).annotate(
        latest_date=Max('created_date'),
        staff_name=Max('staff__fullname'),
    ).order_by('-latest_date')
    
    # Get all receipts with their full details
    receipt_data = {}
    for receipt_entry in distinct_receipts:
        receipt_number = receipt_entry['receipt_number']
        
        # Get all receipt records for this receipt number
        receipts = Receipt.objects.filter(
            patient=patient,
            receipt_number=receipt_number
        ).order_by('created_date')
        
        # Get the invoice number from the first receipt
        invoice_number = receipts.first().invoice_number if receipts.exists() else None
        
        # Get invoice items if invoice number exists
        invoice_items = []
        total_amount = 0
        if invoice_number:
            invoice_items = Invoice.objects.filter(
                patient=patient,
                invoice_number=invoice_number,
            ).order_by('created_date')
            
            # Calculate total amount from receipts
            total_amount = receipts.first().total_price if receipts.exists() else 0
        
        # Process invoice items for display
        processed_items = []
        for item in invoice_items:
            original_rate = 0
            if item.qty > 0:
                discount_factor = (1 - item.discount / 100.0)
                if discount_factor != 0:
                    original_rate = item.price / (item.qty * discount_factor)
            
            item.calculated_original_rate = original_rate
            processed_items.append(item)
        
        # Store receipt data
        receipt_data[receipt_number] = {
            'items': processed_items,
            'total_amount': total_amount,
            'invoice_number': invoice_number,
            'created_date': receipt_entry['latest_date'],
            'staff_name': receipt_entry['staff_name'],
            'remarks': receipts.first().remarks if receipts.exists() else '',
            'payment_type': receipts.first().payment_type if receipts.exists() else ''
        }
    
    context = {
        'patient': patient,
        'total_deposits':total_deposits,
        'distinct_receipts': distinct_receipts,
        'receipt_data': receipt_data
    }
    return render(request, 'Billings/total_receipt.html', context)


@csrf_exempt
def save_receipt_signature(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        receipt_number = data.get('receipt_number')
        signer_name = data.get('signer_name')
        signature_data = data.get('signature_data')
        
        return JsonResponse({'success': True, 'message': 'Signature saved successfully'})
    return JsonResponse({'success': False, 'message': 'Invalid request'})

@csrf_exempt
def send_receipt_qr_code(request):
    if request.method == 'POST':
        data = json.loads(request.body)
        receipt_number = data.get('receipt_number')
        email = data.get('email')
        
        try:
            # Get receipt data
            receipt = Receipt.objects.filter(receipt_number=receipt_number).first()
            if not receipt:
                return JsonResponse({'success': False, 'message': 'Receipt not found'})
            
            patient = receipt.patient
            total_amount = receipt.total_price
            created_date = receipt.created_date
            
            # Generate QR code
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_H,
                box_size=10,
                border=4,
            )
            
            # Create QR code data with detailed information
            qr_data = f"""
            Receipt #{receipt_number}
            Patient: {patient.get_full_name()}
            Hospital Number: {patient.hospital_number}
            Amount: ₦{total_amount}
            Date: {created_date.strftime('%Y-%m-%d %H:%M')}
            ISALU HOSPITALS LIMITED
            """
            
            qr.add_data(qr_data)
            qr.make(fit=True)
            
            # Create QR code image
            img = qr.make_image(fill_color="black", back_color="white")
            
            # Save QR code to bytes
            buffer = BytesIO()
            img.save(buffer, format='PNG')
            buffer.seek(0)
            
            # Create email message with attachment
            from django.core.mail import EmailMultiAlternatives
            from email.mime.image import MIMEImage
            
            subject = f'QR Code for Receipt #{receipt_number}'
            
            # Create HTML email content with embedded QR code
            html_content = f"""
            <!DOCTYPE html>
            <html>
            <head>
                <meta charset="UTF-8">
                <meta name="viewport" content="width=device-width, initial-scale=1.0">
                <style>
                    body {{
                        font-family: Arial, sans-serif;
                        line-height: 1.6;
                        color: #333;
                        max-width: 600px;
                        margin: 0 auto;
                        padding: 20px;
                    }}
                    .header {{
                        text-align: center;
                        padding: 20px;
                        background-color: #f8f9fa;
                        border-radius: 10px;
                        margin-bottom: 20px;
                    }}
                    .header h2 {{
                        color: #28a745;
                        margin: 0;
                    }}
                    .receipt-details {{
                        background-color: #fff;
                        border: 1px solid #ddd;
                        border-radius: 10px;
                        padding: 20px;
                        margin: 20px 0;
                    }}
                    .receipt-details p {{
                        margin: 10px 0;
                    }}
                    .qr-container {{
                        text-align: center;
                        margin: 30px 0;
                        padding: 20px;
                        background-color: #f8f9fa;
                        border-radius: 10px;
                    }}
                    .qr-container img {{
                        max-width: 200px;
                        height: auto;
                        border: 1px solid #ddd;
                        padding: 10px;
                        background-color: white;
                    }}
                    .footer {{
                        text-align: center;
                        margin-top: 30px;
                        padding: 20px;
                        font-size: 12px;
                        color: #666;
                        border-top: 1px solid #eee;
                    }}
                    .button {{
                        display: inline-block;
                        padding: 10px 20px;
                        background-color: #28a745;
                        color: white;
                        text-decoration: none;
                        border-radius: 5px;
                        margin-top: 10px;
                    }}
                </style>
            </head>
            <body>
                <div class="header">
                    <h2>ISALU HOSPITALS LIMITED</h2>
                    <p>Email: it@isaluhospitals.com | Phone: 08099902223</p>
                </div>
                
                <div class="receipt-details">
                    <h3 style="color: #28a745;">Payment Receipt QR Code</h3>
                    <p><strong>Receipt Number:</strong> #{receipt_number}</p>
                    <p><strong>Patient Name:</strong> {patient.get_full_name()}</p>
                    <p><strong>Hospital Number:</strong> {patient.hospital_number}</p>
                    <p><strong>Total Amount:</strong> ₦{total_amount:,.2f}</p>
                    <p><strong>Payment Date:</strong> {created_date.strftime('%d %B %Y %H:%M')}</p>
                </div>
                
                <div class="qr-container">
                    <h4>Scan this QR Code for Receipt Verification</h4>
                    <img src="cid:receipt_qr_code" alt="QR Code for Receipt #{receipt_number}">
                    <p><small>Scan this QR code to verify your payment receipt</small></p>
                </div>
                
                <div class="footer">
                    <p>This is an automated message from ISALU HOSPITALS LIMITED.</p>
                    <p>Please keep this receipt for your records.</p>
                    <p>For any inquiries, please contact our billing department.</p>
                </div>
            </body>
            </html>
            """
            
            # Create email with attachment
            email_message = EmailMultiAlternatives(
                subject=subject,
                body=f"Please find attached the QR code for Receipt #{receipt_number}",
                from_email=settings.DEFAULT_FROM_EMAIL,
                to=[email]
            )
            
            # Attach HTML content
            email_message.attach_alternative(html_content, "text/html")
            
            # Attach QR code image as inline attachment
            img_data = buffer.getvalue()
            mime_image = MIMEImage(img_data)
            mime_image.add_header('Content-ID', '<receipt_qr_code>')
            mime_image.add_header('Content-Disposition', 'inline', filename=f'receipt_{receipt_number}_qr.png')
            email_message.attach(mime_image)
            
            # Also attach QR code as a downloadable file
            email_message.attach(f'receipt_{receipt_number}_qr.png', img_data, 'image/png')
            
            # Send email
            email_message.send()
            
            buffer.close()
            
            return JsonResponse({'success': True, 'message': f'QR Code sent successfully to {email}'})
            
        except Exception as e:
            print(f"Error sending QR code email: {str(e)}")
            return JsonResponse({'success': False, 'message': str(e)})
    
    return JsonResponse({'success': False, 'message': 'Invalid request'})


def download_receipt(request, receipt_number, format):
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch
    import io
    
    # Get receipt data
    receipts = Receipt.objects.filter(receipt_number=receipt_number)
    if not receipts.exists():
        return HttpResponse('Receipt not found')
    
    patient = receipts.first().patient
    invoice_number = receipts.first().invoice_number
    total_amount = receipts.first().total_price
    payment_type = receipts.first().payment_type
    remarks = receipts.first().remarks
    created_date = receipts.first().created_date
    
    # Get invoice items if invoice number exists
    invoice_items = []
    if invoice_number:
        invoice_items = Invoice.objects.filter(
            patient=patient,
            invoice_number=invoice_number,
            # completed=1
        )
    
    # Convert amount to words
    amount_in_words = number_to_words(int(total_amount)) + " Naira Only"
    
    if format == 'pdf':
        # Create PDF using ReportLab
        buffer = io.BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4, rightMargin=72, leftMargin=72, topMargin=72, bottomMargin=72)
        
        elements = []
        
        # Styles
        styles = getSampleStyleSheet()
        title_style = ParagraphStyle(
            'CustomTitle',
            parent=styles['Heading1'],
            fontSize=16,
            alignment=1,  # Center alignment
            spaceAfter=12
        )
        center_style = ParagraphStyle(
            'Center',
            parent=styles['Normal'],
            alignment=1,
            spaceAfter=6
        )
        right_style = ParagraphStyle(
            'Right',
            parent=styles['Normal'],
            alignment=2,  # Right alignment
            spaceAfter=6
        )
        normal_style = styles['Normal']
        bold_style = ParagraphStyle(
            'Bold',
            parent=styles['Normal'],
            fontName='Helvetica-Bold'
        )
        
        # Hospital Header
        elements.append(Paragraph("ISALU HOSPITALS LIMITED", title_style))
        elements.append(Paragraph("Email: it@isaluhospitals.com", center_style))
        elements.append(Paragraph("Phone: 08099902223", center_style))
        elements.append(Spacer(1, 12))
        
        # Receipt Meta
        elements.append(Paragraph(f"RECEIPT #: <b>{receipt_number}</b>", right_style))
        elements.append(Paragraph(f"INVOICE #: <b>{invoice_number or 'N/A'}</b>", right_style))
        elements.append(Paragraph(f"{created_date.strftime('%d %B %Y %H:%M')}", right_style))
        elements.append(Spacer(1, 12))
        
        # Patient Information
        patient_info = f"""
        <b>PATIENT INFORMATION:</b><br/>
        Name: <b>{patient.get_full_name()}</b> [{patient.hospital_number}]<br/>
        Sponsor: <b>{patient.plan.plan if patient.plan else 'N/A'}</b><br/>
        Plan Type: <b>{patient.category.category if patient.category else 'N/A'}</b><br/>
        Policy Number: <b>{patient.insurance_policy_number or 'NIL'}</b><br/>
        Address: <b>{patient.address or 'N/A'}</b><br/>
        Phone: <b>{patient.phone_number or 'N/A'}</b><br/>
        Gender: <b>{patient.gender or 'N/A'}</b>
        """
        elements.append(Paragraph(patient_info, normal_style))
        elements.append(Spacer(1, 12))
        
        # Payment Type
        elements.append(Paragraph(f"<b>Payment Type:</b> {payment_type or 'N/A'}", normal_style))
        elements.append(Spacer(1, 12))
        
        # Receipt Title
        elements.append(Paragraph("PAYMENT RECEIPT", title_style))
        elements.append(Spacer(1, 12))
        
        # Table Data
        if invoice_items:
            table_data = [['S/N', 'Description', 'Qty', 'Rate (#)', 'Discount (%)', 'Amount (#)']]
            
            for idx, item in enumerate(invoice_items, 1):
                # Calculate original rate
                original_rate = 0
                if item.qty > 0:
                    discount_factor = (1 - item.discount / 100.0)
                    if discount_factor != 0:
                        original_rate = item.price / (item.qty * discount_factor)
                
                table_data.append([
                    str(idx),
                    item.product[:40] + '...' if len(item.product) > 40 else item.product,
                    str(item.qty),
                    f"{original_rate:.2f}",
                    f"{item.discount:.2f}%",
                    f"{item.price:.2f}"
                ])
            
            # Create table
            table = Table(table_data, colWidths=[0.5*inch, 2.5*inch, 0.5*inch, 1*inch, 1*inch, 1*inch])
            table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 10),
                ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
                ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
                ('GRID', (0, 0), (-1, -1), 1, colors.black),
                ('ALIGN', (2, 1), (2, -1), 'CENTER'),
                ('ALIGN', (3, 1), (5, -1), 'RIGHT'),
            ]))
            
            elements.append(table)
            elements.append(Spacer(1, 20))
        else:
            elements.append(Paragraph("No items found for this receipt.", normal_style))
            elements.append(Spacer(1, 20))
        
        # Totals - Two Row Layout
        # Create a table for totals with two rows
        totals_data = [
            ['Total Amount Paid:', f'#{total_amount:.2f}'],
            ['Amount in Words:', amount_in_words]
        ]
        
        totals_table = Table(totals_data, colWidths=[1.5*inch, 4*inch])
        totals_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            # ('BACKGROUND', (0, 0), (-1, -1), colors.lightgrey),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        
        # Create a container to align the totals table to the right
        from reportlab.platypus import Table as TableContainer
        container = TableContainer([[totals_table]], colWidths=[5.5*inch])
        container.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, 0), 'RIGHT'),
        ]))
        
        elements.append(container)
        elements.append(Spacer(1, 12))
        
        # Remarks
        if remarks:
            remarks_paragraph = Paragraph(f"<b>Remarks:</b> {remarks}", normal_style)
            elements.append(remarks_paragraph)
        
        # Build PDF
        doc.build(elements)
        
        # Get PDF from buffer
        pdf = buffer.getvalue()
        buffer.close()
        
        response = HttpResponse(content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="receipt_{receipt_number}.pdf"'
        response.write(pdf)
        return response
    
    elif format == 'excel':
        # Generate Excel
        response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
        response['Content-Disposition'] = f'attachment; filename="receipt_{receipt_number}.xlsx"'
        
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = f"Receipt #{receipt_number}"
        
        # Add headers
        headers = ['Description', 'Quantity', 'Rate', 'Discount', 'Amount']
        for col, header in enumerate(headers, 1):
            ws.cell(row=1, column=col, value=header)
        
        # Add data
        for row, item in enumerate(invoice_items, 2):
            original_rate = 0
            if item.qty > 0:
                discount_factor = (1 - item.discount / 100.0)
                if discount_factor != 0:
                    original_rate = item.price / (item.qty * discount_factor)
            
            ws.cell(row=row, column=1, value=item.product)
            ws.cell(row=row, column=2, value=item.qty)
            ws.cell(row=row, column=3, value=float(original_rate))
            ws.cell(row=row, column=4, value=item.discount)
            ws.cell(row=row, column=5, value=float(item.price))
        
        # Add totals section
        total_row = len(invoice_items) + 2
        ws.cell(row=total_row, column=4, value="Total Amount Paid:")
        ws.cell(row=total_row, column=5, value=float(total_amount))
        
        total_row += 1
        ws.cell(row=total_row, column=4, value="Amount in Words:")
        ws.cell(row=total_row, column=5, value=amount_in_words)
        
        # Add remarks if exists
        if remarks:
            total_row += 1
            ws.cell(row=total_row, column=4, value="Remarks:")
            ws.cell(row=total_row, column=5, value=remarks)
        
        wb.save(response)
        return response
    
    return HttpResponse('Invalid format')

def number_to_words(n):
    """Convert number to words"""
    ones = ['', 'One', 'Two', 'Three', 'Four', 'Five', 'Six', 'Seven', 'Eight', 'Nine',
            'Ten', 'Eleven', 'Twelve', 'Thirteen', 'Fourteen', 'Fifteen', 'Sixteen',
            'Seventeen', 'Eighteen', 'Nineteen']
    
    tens = ['', '', 'Twenty', 'Thirty', 'Forty', 'Fifty', 'Sixty', 'Seventy', 'Eighty', 'Ninety']
    
    thousands = ['', 'Thousand', 'Million', 'Billion']
    
    if n == 0:
        return 'Zero'
    
    def convert_chunk(num):
        if num == 0:
            return ''
        
        words = []
        
        # Hundreds
        if num >= 100:
            words.append(ones[num // 100] + ' Hundred')
            num %= 100
        
        # Tens and ones
        if num >= 20:
            words.append(tens[num // 10])
            num %= 10
            if num > 0:
                words.append(ones[num])
        elif num > 0:
            words.append(ones[num])
        
        return ' '.join(words)
    
    result = []
    chunk_index = 0
    
    while n > 0:
        chunk = n % 1000
        if chunk != 0:
            chunk_words = convert_chunk(chunk)
            if chunk_index > 0:
                chunk_words += ' ' + thousands[chunk_index]
            result.insert(0, chunk_words)
        n //= 1000
        chunk_index += 1
    
    return ' '.join(result)
    

# --- Patient Detail Context Helper ---
def get_patient_context(patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    return {
        'patient': patient,
        'patient_id': patient_id, 
    }

# --- CREATE Deposit/Refund ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def create_deposit_refund(request, patient_id):
    patient_context = get_patient_context(patient_id)
    deposit_form = DepositForm()
    refund_form = RefundForm()
    if request.method == 'POST':
        if 'deposit_submit' in request.POST:
            deposit_form = DepositForm(request.POST)
            if request.user.pin == int(request.POST.get('pin_code')):
                if deposit_form.is_valid():
                    deposit = deposit_form.save(commit=False)
                    deposit.patient = patient_context['patient']
                    deposit.staff = request.user
                    deposit.save()
                    messages.success(request, 'Deposit created successfully!')
                    return redirect('list_deposits', patient_id=patient_id)
                else:
                    messages.error(request, 'Error creating deposit. Please check the form.') 
            else:
                messages.error(request, 'Incorrect Pin Supplied') 
        elif 'refund_submit' in request.POST:
            refund_form = RefundForm(request.POST)
            if request.user.pin == int(request.POST.get('pin_code')):
                confirm_invoice_id = Invoice.objects.filter(
                    patient=patient_context['patient'],
                    invoice_number=request.POST['invoice_id']
                    )
                if confirm_invoice_id.exists():
                    if request.POST['payment_to'] == 'hospital':
                        Deposit.objects.create(
                            invoice_id=request.POST['invoice_id'],
                            amount=request.POST['amount'],
                            payment_type=request.POST['payment_type'],
                            patient=patient_context['patient'],
                            staff=request.user,
                        )
                        Refund.objects.create(
                            invoice_id=request.POST['invoice_id'],
                            amount=request.POST['amount'],
                            payment_type=request.POST['payment_type'],
                            payment_to=request.POST['payment_to'],
                            patient=patient_context['patient'],
                            staff=request.user,
                        )
                        messages.success(request, 'Refund created successfully!')
                    elif request.POST['payment_to'] == 'personal':
                        if refund_form.is_valid():
                            refund = refund_form.save(commit=False)
                            refund.payment_to = request.POST['payment_to']
                            refund.patient = patient_context['patient']
                            refund.staff = request.user
                            refund.save()
                            messages.success(request, 'Refund created successfully!')
                            return redirect('list_refunds', patient_id=patient_id)
                        else:
                            messages.error(request, 'Error creating refund. Please check the form.')
                else:
                    messages.error(request, f'Error: The Invoice Number: [{request.POST['invoice_id']}] does not belong to this patient')
            else:
                messages.error(request, 'Incorrect Pin Supplied') 
        else:
            messages.error(request, 'Invalid form submission.')

    context = {
        **patient_context,
        'deposit_form': deposit_form,
        'refund_form': refund_form,
    }
    return render(request, 'Billings/Deposit_Refund/create_deposit_refund.html', context)

# --- LIST Deposits ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
def list_deposits(request, patient_id):
    patient_context = get_patient_context(patient_id)
    deposits = Deposit.objects.filter(patient=patient_context['patient']).order_by('-created_date')

    total_deposits = 0
    family_deposits = {}
    if patient_context['patient'].plan.plan == 'Family':
        # Extract the family prefix
        family_prefix = patient_context['patient'].hospital_number[:-2]

        # Filter deposits where the hospital number starts with the family prefix
        family_deposits = Deposit.objects.filter(
            patient__hospital_number__startswith=family_prefix
        )

        # Calculate total family balance
        total_deposits = family_deposits.aggregate(
            total=Sum('amount')
        )['total'] or 0

    else:
        total = deposits.aggregate(total_amount=Sum('amount'))
        # Accessing the value directly
        total_deposits = total['total_amount'] or 0
    

    
    context = {
        **patient_context,
        'deposits': deposits,
        'total_deposits':total_deposits,
        'family_deposits': family_deposits,

    }
    return render(request, 'Billings/Deposit_Refund/list_deposits.html', context)

# --- DETAIL/UPDATE Deposit ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def deposit_detail(request, patient_id, deposit_id):
    patient_context = get_patient_context(patient_id)
    deposit = get_object_or_404(Deposit, id=deposit_id, patient=patient_context['patient'])

    if request.method == 'POST':
        form = DepositForm(request.POST, instance=deposit)
        if form.is_valid():
            form.save()
            messages.success(request, 'Deposit updated successfully!')
            return redirect('list_deposits', patient_id=patient_id)
        else:
            messages.error(request, 'Error updating deposit. Please check the form.')
    else:
        form = DepositForm(instance=deposit)

    context = {
        **patient_context,
        'deposit': deposit,
        'form': form,
    }
    return render(request, 'Billings/Deposit_Refund/deposit_detail.html', context)


# --- DELETE Deposit ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
def delete_deposit(request, patient_id, deposit_id):
    patient_context = get_patient_context(patient_id)
    deposit = get_object_or_404(Deposit, id=deposit_id, patient=patient_context['patient'])

    if request.method == 'POST':
        if request.user.pin == int(request.POST.get('pin_code')):
            deposit.delete()
            messages.success(request, 'Deposit deleted successfully!')
            return redirect('list_deposits', patient_id=patient_id)
        else:
            messages.error(request, 'Incorrect Pin Supplied')
    
    context = {
        **patient_context,
        'deposit': deposit,
    }
    return render(request, 'Billings/Deposit_Refund/deposit_confirm_delete.html', context)


# --- LIST Refunds ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
def list_refunds(request, patient_id):
    patient_context = get_patient_context(patient_id)
    refunds = Refund.objects.filter(patient=patient_context['patient']).order_by('-created_date')
    total = refunds.aggregate(total_amount=Sum('amount'))
    # Accessing the value directly
    total_refunds = total['total_amount'] or 0
    
    context = {
        **patient_context,
        'refunds': refunds,
        'total_refunds':total_refunds,
    }
    return render(request, 'Billings/Deposit_Refund/list_refunds.html', context)


# --- DETAIL/UPDATE Refund ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
@transaction.atomic
def refund_detail(request, patient_id, refund_id):
    patient_context = get_patient_context(patient_id)
    refund = get_object_or_404(Refund, id=refund_id, patient=patient_context['patient'])

    if request.method == 'POST':
        form = RefundForm(request.POST, instance=refund)
        if form.is_valid():
            form.save()
            messages.success(request, 'Refund updated successfully!')
            return redirect('list_refunds', patient_id=patient_id)
        else:
            messages.error(request, 'Error updating refund. Please check the form.')
    else:
        form = RefundForm(instance=refund)

    context = {
        **patient_context,
        'refund': refund,
        'form': form,
    }
    return render(request, 'Billings/Deposit_Refund/refund_detail.html', context)


# --- DELETE Refund ---
@login_required
@department_required('Billings', 'Admin', 'CMD')
def delete_refund(request, patient_id, refund_id):
    patient_context = get_patient_context(patient_id)
    refund = get_object_or_404(Refund, id=refund_id, patient=patient_context['patient'])

    if request.method == 'POST':
        if request.user.pin == int(request.POST.get('pin_code')):
            if refund.payment_to != 'hospital':
                refund.delete()
                messages.success(request, 'Refund deleted successfully!')
                return redirect('list_refunds', patient_id=patient_id)
            else:
                refund.delete()
                Deposit.objects.get(invoice_id=refund.invoice_id).delete()
                messages.success(request, 'Refund deleted successfully!')
                return redirect('list_refunds', patient_id=patient_id)
        else:
            messages.error(request, 'Incorrect Pin Supplied')
    
    context = {
        **patient_context,
        'refund': refund,
    }
    return render(request, 'Billings/Deposit_Refund/refund_confirm_delete.html', context)


from django.db.models import Sum
from decimal import Decimal
from io import BytesIO
from django.template.loader import render_to_string
from xhtml2pdf import pisa

from django.core.mail import EmailMessage
from django.conf import settings

@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_statements(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)

    filter_type = request.GET.get('filter_type', 'all')
    specific_date = request.GET.get('specific_date', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    invoices = Invoice.objects.filter(patient=patient)

    if filter_type == 'date' and specific_date:
        try:
            specific_date_obj = datetime.strptime(specific_date, '%Y-%m-%d').date()
            start_dt = timezone.make_aware(datetime.combine(specific_date_obj, time.min))
            end_dt = timezone.make_aware(datetime.combine(specific_date_obj, time.max))
            invoices = invoices.filter(created_date__range=(start_dt, end_dt))
        except (ValueError, TypeError) as e:
            print(f"Date parsing error: {e}")
            
    elif filter_type == 'range' and date_from and date_to:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            start_dt = timezone.make_aware(datetime.combine(date_from_obj, time.min))
            end_dt = timezone.make_aware(datetime.combine(date_to_obj, time.max))
            invoices = invoices.filter(created_date__range=(start_dt, end_dt))
        except (ValueError, TypeError) as e:
            print(f"Date range parsing error: {e}")
    
    if filter_type != 'none':
        invoices = invoices.order_by('created_date')
        
        # Opening balance - INCLUDING REFUNDS (distinct invoice_numbers only)
        opening_balance = Decimal('0.00')
        if filter_type in ['date', 'range'] and invoices.exists():
            first_date = invoices.first().created_date
            prior_invoices = Invoice.objects.filter(patient=patient, created_date__lt=first_date).order_by('created_date')
            
            seen_prior_inv = set()
            for inv in prior_invoices:
                debit = Decimal(str(inv.price))
                credit = Decimal(str(inv.price)) if inv.completed == 1 else Decimal('0.00')
                
                # Refund only once per invoice_number
                refund = Decimal('0.00')
                if inv.invoice_number not in seen_prior_inv:
                    refund_total = Refund.objects.filter(invoice_id__iexact=inv.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
                    refund = Decimal(str(refund_total))
                    seen_prior_inv.add(inv.invoice_number)

                opening_balance = opening_balance + debit - credit + refund
        
        statement_data = []
        running_balance = opening_balance
        
        # Cache refunds and track seen invoice_numbers to avoid repeat
        refund_cache = {}
        seen_invoice_numbers = set()

        for invoice in invoices:
            debit = Decimal(str(invoice.price))
            if invoice.completed == 1:
                credit = Decimal(str(invoice.price))
                trans_type = "Receipt"
            else:
                credit = Decimal('0.00')
                trans_type = "Invoice"
            
            # GET REFUND ONCE PER INVOICE_NUMBER 
            if invoice.invoice_number not in refund_cache:
                rt = Refund.objects.filter(invoice_id__iexact=invoice.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
                refund_cache[invoice.invoice_number] = Decimal(str(rt))
            
            # Apply refund only on first line of that invoice_number
            if invoice.invoice_number not in seen_invoice_numbers:
                refund = refund_cache[invoice.invoice_number]
                seen_invoice_numbers.add(invoice.invoice_number)
            else:
                refund = Decimal('0.00')

            running_balance = running_balance + debit - credit + refund
            
            statement_data.append({
                'reference': invoice.invoice_number,
                'trans_date': invoice.created_date,
                'trans_type': trans_type,
                'details': invoice.product,
                'debit': debit,
                'credit': credit,
                'refund': refund,
                'rib': running_balance,
                'user': invoice.staff.fullname if invoice.staff else 'System',
                'completed': invoice.completed,
                'has_refund': refund > 0,
            })
        
        total_debits = sum(item['debit'] for item in statement_data)
        total_credits = sum(item['credit'] for item in statement_data)
        total_refunds = sum(refund_cache.values()) # DISTINCT total, not repeated
        balance_due = running_balance
        opening_balance_display = opening_balance
    else:
        statement_data = []
        total_debits = total_credits = balance_due = total_refunds = Decimal('0.00')
        opening_balance_display = Decimal('0.00')
    
    context = {
        'patient': patient,
        'statement_data': statement_data,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'total_refunds': total_refunds,
        'balance_due': balance_due,
        'opening_balance': opening_balance_display,
        'filter_type': filter_type,
        'date_from': date_from,
        'date_to': date_to,
        'specific_date': specific_date,
    }
    
    return render(request, 'Billings/statements.html', context)

@require_POST
def email_statement(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    if not patient.email_address:
        return JsonResponse({'success': False, 'error': 'No email address'})

    filter_type = request.POST.get('filter_type', 'all')
    specific_date = request.POST.get('specific_date', '')
    date_from = request.POST.get('date_from', '')
    date_to = request.POST.get('date_to', '')
    
    invoices = Invoice.objects.filter(patient=patient)
    
    if filter_type == 'date' and specific_date:
        specific_date_obj = datetime.strptime(specific_date, '%Y-%m-%d').date()
        start_dt = timezone.make_aware(datetime.combine(specific_date_obj, time.min))
        end_dt = timezone.make_aware(datetime.combine(specific_date_obj, time.max))
        invoices = invoices.filter(created_date__range=(start_dt, end_dt))
    elif filter_type == 'range' and date_from and date_to:
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
        start_dt = timezone.make_aware(datetime.combine(date_from_obj, time.min))
        end_dt = timezone.make_aware(datetime.combine(date_to_obj, time.max))
        invoices = invoices.filter(created_date__range=(start_dt, end_dt))
    
    invoices = invoices.order_by('created_date')

    # opening balance
    opening_balance = Decimal('0.00')
    if filter_type in ['date', 'range'] and invoices.exists():
        first_date = invoices.first().created_date
        prior_invoices = Invoice.objects.filter(patient=patient, created_date__lt=first_date)
        seen_prior = set()
        for inv in prior_invoices:
            debit = Decimal(str(inv.price))
            credit = Decimal(str(inv.price)) if inv.completed == 1 else Decimal('0.00')
            refund = Decimal('0.00')
            if inv.invoice_number not in seen_prior:
                rt = Refund.objects.filter(invoice_id__iexact=inv.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
                refund = Decimal(str(rt))
                seen_prior.add(inv.invoice_number)
            opening_balance += debit - credit + refund
    
    statement_data = []
    running_balance = opening_balance
    refund_cache = {}
    seen_invoice_numbers = set()
    
    for invoice in invoices:
        debit = Decimal(str(invoice.price))
        credit = Decimal(str(invoice.price)) if invoice.completed == 1 else Decimal('0.00')
        trans_type = "Receipt" if invoice.completed == 1 else "Invoice"

        if invoice.invoice_number not in refund_cache:
            rt = Refund.objects.filter(invoice_id__iexact=invoice.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
            refund_cache[invoice.invoice_number] = Decimal(str(rt))
        
        if invoice.invoice_number not in seen_invoice_numbers:
            refund = refund_cache[invoice.invoice_number]
            seen_invoice_numbers.add(invoice.invoice_number)
        else:
            refund = Decimal('0.00')

        running_balance += debit - credit + refund
        statement_data.append({
            'reference': invoice.invoice_number,
            'trans_date': invoice.created_date,
            'trans_type': trans_type,
            'details': invoice.product,
            'debit': debit,
            'credit': credit,
            'refund': refund,
            'rib': running_balance,
            'user': invoice.staff.fullname if invoice.staff else 'System',
        })
    
    total_debits = sum(item['debit'] for item in statement_data)
    total_credits = sum(item['credit'] for item in statement_data)
    total_refunds = sum(refund_cache.values())
    
    context = {
        'patient': patient,
        'statement_data': statement_data,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'total_refunds': total_refunds,
        'balance_due': running_balance,
        'opening_balance': opening_balance,
        'request': request,
    }

    html_string = render_to_string('Billings/statement_pdf.html', context)
    buffer = BytesIO()
    pisa_status = pisa.CreatePDF(html_string, dest=buffer)
    
    if pisa_status.err:
        return JsonResponse({'success': False, 'error': 'PDF generation failed'})

    email = EmailMessage(
        subject=f'Statement - {patient.get_full_name()}',
        body=f'Please find attached statement of account for {patient.get_full_name()} [{patient.hospital_number}]. Total Refunds: {total_refunds}',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[patient.email_address],
    )
    email.attach(f'statement_{patient.hospital_number}.pdf', buffer.getvalue(), 'application/pdf')

    try:
        email.send(fail_silently=False)
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})



@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_family_statements(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)

    # Get family prefix 
    hospital_no = patient.hospital_number or ''
    if '/' in hospital_no:
        family_prefix = hospital_no.split('/')[0]
    else:
        family_prefix = hospital_no[:-2] if len(hospital_no) > 2 else hospital_no

    # Check if it's really a family plan
    is_family = False
    if hasattr(patient, 'plan') and patient.plan and getattr(patient.plan, 'plan', '') == 'Family':
        is_family = True

    # Get all family members
    family_members = PatientProfile.objects.filter(
        hospital_number__istartswith=family_prefix
    ).order_by('hospital_number')

    if not family_members.exists():
        family_members = PatientProfile.objects.filter(id=patient_id)

    family_member_ids = list(family_members.values_list('id', flat=True))
    family_hospital_numbers = list(family_members.values_list('hospital_number', flat=True))

    filter_type = request.GET.get('filter_type', 'all')
    specific_date = request.GET.get('specific_date', '')
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')

    invoices = Invoice.objects.filter(patient_id__in=family_member_ids).select_related('patient')

    if filter_type == 'date' and specific_date:
        try:
            specific_date_obj = datetime.strptime(specific_date, '%Y-%m-%d').date()
            start_dt = timezone.make_aware(datetime.combine(specific_date_obj, time.min))
            end_dt = timezone.make_aware(datetime.combine(specific_date_obj, time.max))
            invoices = invoices.filter(created_date__range=(start_dt, end_dt))
        except:
            pass
    elif filter_type == 'range' and date_from and date_to:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            start_dt = timezone.make_aware(datetime.combine(date_from_obj, time.min))
            end_dt = timezone.make_aware(datetime.combine(date_to_obj, time.max))
            invoices = invoices.filter(created_date__range=(start_dt, end_dt))
        except:
            pass

    if filter_type!= 'none':
        invoices = invoices.order_by('created_date')

        # Opening Balance - DISTINCT invoice_numbers only
        opening_balance = Decimal('0.00')
        if filter_type in ['date', 'range'] and invoices.exists():
            first_date = invoices.first().created_date
            prior_invoices = Invoice.objects.filter(
                patient_id__in=family_member_ids,
                created_date__lt=first_date
            )
            seen_prior = set()
            for inv in prior_invoices:
                debit = Decimal(str(inv.price))
                credit = Decimal(str(inv.price)) if inv.completed == 1 else Decimal('0.00')
                refund = Decimal('0.00')
                if inv.invoice_number not in seen_prior:
                    rt = Refund.objects.filter(invoice_id__iexact=inv.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
                    refund = Decimal(str(rt))
                    seen_prior.add(inv.invoice_number)
                opening_balance += debit - credit + refund

        statement_data = []
        running_balance = opening_balance
        refund_cache = {}
        seen_invoice_numbers = set()

        for invoice in invoices:
            debit = Decimal(str(invoice.price))
            if invoice.completed == 1:
                credit = Decimal(str(invoice.price))
                trans_type = "Receipt"
            else:
                credit = Decimal('0.00')
                trans_type = "Invoice"

            if invoice.invoice_number not in refund_cache:
                rt = Refund.objects.filter(invoice_id__iexact=invoice.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
                refund_cache[invoice.invoice_number] = Decimal(str(rt))

            if invoice.invoice_number not in seen_invoice_numbers:
                refund = refund_cache[invoice.invoice_number]
                seen_invoice_numbers.add(invoice.invoice_number)
            else:
                refund = Decimal('0.00')

            running_balance += debit - credit + refund

            statement_data.append({
                'reference': invoice.invoice_number,
                'trans_date': invoice.created_date,
                'trans_type': trans_type,
                'patient_name': invoice.patient.get_full_name() if invoice.patient else 'N/A',
                'hospital_number': invoice.patient.hospital_number if invoice.patient else 'N/A',
                'details': invoice.product,
                'debit': debit,
                'credit': credit,
                'refund': refund,
                'rib': running_balance,
                'user': invoice.staff.fullname if invoice.staff else 'System',
                'has_refund': refund > 0,
            })

        total_debits = sum(item['debit'] for item in statement_data)
        total_credits = sum(item['credit'] for item in statement_data)
        total_refunds = sum(refund_cache.values())
        balance_due = running_balance
    else:
        statement_data = []
        total_debits = total_credits = balance_due = total_refunds = Decimal('0.00')
        opening_balance = Decimal('0.00')

    context = {
        'patient': patient,
        'family_members': family_members,
        'family_prefix': family_prefix,
        'is_family': is_family,
        'statement_data': statement_data,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'total_refunds': total_refunds,
        'balance_due': balance_due,
        'opening_balance': opening_balance,
        'filter_type': filter_type,
        'date_from': date_from,
        'date_to': date_to,
        'specific_date': specific_date,
    }
    return render(request, 'Billings/family_statements.html', context)

@require_POST
def email_family_statement(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    hospital_no = patient.hospital_number or ''
    family_prefix = hospital_no.split('/')[0] if '/' in hospital_no else hospital_no[:-2]

    family_members = PatientProfile.objects.filter(hospital_number__istartswith=family_prefix)
    family_member_ids = list(family_members.values_list('id', flat=True))

    filter_type = request.POST.get('filter_type', 'all')
    specific_date = request.POST.get('specific_date', '')
    date_from = request.POST.get('date_from', '')
    date_to = request.POST.get('date_to', '')

    invoices = Invoice.objects.filter(patient_id__in=family_member_ids).select_related('patient').order_by('created_date')

    if filter_type == 'date' and specific_date:
        d = datetime.strptime(specific_date, '%Y-%m-%d').date()
        invoices = invoices.filter(created_date__range=(timezone.make_aware(datetime.combine(d, time.min)), timezone.make_aware(datetime.combine(d, time.max))))
    elif filter_type == 'range' and date_from and date_to:
        d1 = datetime.strptime(date_from, '%Y-%m-%d').date()
        d2 = datetime.strptime(date_to, '%Y-%m-%d').date()
        invoices = invoices.filter(created_date__range=(timezone.make_aware(datetime.combine(d1, time.min)), timezone.make_aware(datetime.combine(d2, time.max))))

    opening_balance = Decimal('0.00')
    statement_data = []
    running_balance = opening_balance
    refund_cache = {}
    seen_invoice_numbers = set()

    for invoice in invoices:
        debit = Decimal(str(invoice.price))
        credit = Decimal(str(invoice.price)) if invoice.completed == 1 else Decimal('0.00')
        if invoice.invoice_number not in refund_cache:
            rt = Refund.objects.filter(invoice_id__iexact=invoice.invoice_number).aggregate(total=Sum('amount'))['total'] or 0
            refund_cache[invoice.invoice_number] = Decimal(str(rt))
        refund = refund_cache[invoice.invoice_number] if invoice.invoice_number not in seen_invoice_numbers else Decimal('0.00')
        if invoice.invoice_number not in seen_invoice_numbers:
            seen_invoice_numbers.add(invoice.invoice_number)
        running_balance += debit - credit + refund
        statement_data.append({
            'reference': invoice.invoice_number,
            'trans_date': invoice.created_date,
            'trans_type': "Receipt" if invoice.completed==1 else "Invoice",
            'patient_name': invoice.patient.get_full_name(),
            'hospital_number': invoice.patient.hospital_number,
            'details': invoice.product,
            'debit': debit, 'credit': credit, 'refund': refund, 'rib': running_balance,
            'user': invoice.staff.fullname if invoice.staff else 'System',
        })

    total_debits = sum(i['debit'] for i in statement_data)
    total_credits = sum(i['credit'] for i in statement_data)
    total_refunds = sum(refund_cache.values())

    context = {
        'patient': patient,
        'family_members': family_members,
        'family_prefix': family_prefix,
        'statement_data': statement_data,
        'total_debits': total_debits,
        'total_credits': total_credits,
        'total_refunds': total_refunds,
        'balance_due': running_balance,
        'opening_balance': opening_balance,
        'request': request
    }

    html_string = render_to_string('Billings/family_statement_pdf.html', context)
    buffer = BytesIO()
    pisa.CreatePDF(html_string, dest=buffer)

    # Email to principal (father /a)
    principal = patient
    to_email = principal.email_address 

    email = EmailMessage(
        subject=f'Family Statement - {family_prefix}',
        body=f'Family statement for the family of {patient.surname} [{family_prefix}]. Members: {", ".join([m.get_full_name() for m in family_members])}',
        from_email=settings.DEFAULT_FROM_EMAIL,
        to=[to_email] if to_email else [],
    )
    email.attach(f'family_statement_{family_prefix}.pdf', buffer.getvalue(), 'application/pdf')
    try:
        email.send()
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)})
       

@login_required
@department_required('Billings', 'Admin', 'CMD')
def get_summary(request, patient_id):
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get filter parameters
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    ignore_date = request.GET.get('ignore_date', 'off')
    filter_type = request.GET.get('filter_type', 'none')
    
    # Initializing all totals as Decimal
    cash_bills = Decimal('0.00')
    exception_bills = Decimal('0.00')
    claim_bills = Decimal('0.00')
    total_invoice = Decimal('0.00')
    payments_transfers = Decimal('0.00')
    transfers_refunds = Decimal('0.00')
    deposit = Decimal('0.00')
    balance = Decimal('0.00')
    
    # Checking if filter is applied
    filter_applied = False
    
    print("=" * 60)
    print("DEBUG: GET SUMMARY - EXCEPTION BILLS")
    print("=" * 60)
    print(f"Filter Type: {filter_type}")
    print(f"Date From: {date_from}")
    print(f"Date To: {date_to}")
    print(f"Ignore Date: {ignore_date}")
    print(f"Patient ID: {patient_id}")
    print("-" * 60)
    
    # Applying filters based on filter_type
    if filter_type == 'all':
        filter_applied = True
        print("✅ Filter: ALL RECORDS - No date filter")
        
    elif filter_type == 'range' and date_from and date_to:
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            print(f" Filter: DATE RANGE - From: {date_from_obj}, To: {date_to_obj}")
            filter_applied = True
        except (ValueError, TypeError) as e:
            print(f"Date parsing error: {e}")
            filter_applied = False
    else:
        print(f"No valid filter applied. filter_type: {filter_type}")
        filter_applied = False
    
    # If ignore_date is checked and filter is applied, show all records
    if ignore_date == 'on' and filter_applied:
        print(" Ignore date is ON - showing all records")
        filter_applied = True
    
    if filter_applied:
        print("-" * 60)
        print("CALCULATING TOTALS...")
        print("-" * 60)
        
        # Building date filter for all models
        date_filter = Q()
        if filter_type == 'range' and date_from and date_to and ignore_date != 'on':
            try:
                date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                from datetime import datetime as dt
                date_from_datetime = dt.combine(date_from_obj, dt.min.time())
                date_to_datetime = dt.combine(date_to_obj, dt.max.time())
                date_filter = Q(created_date__gte=date_from_datetime) & Q(created_date__lte=date_to_datetime)
                print(f"📅 Date filter: {date_from_datetime} to {date_to_datetime}")
            except (ValueError, TypeError) as e:
                print(f"❌ Date filter error: {e}")
        
        # Case 1: Cash Bills
        print("\n1. Calculating Cash Bills...")
        cash_bills_qs = Invoice.objects.filter(
            patient=patient
        ).exclude(
            payment_option='Claim'
        )
        
        if date_filter:
            cash_bills_qs = cash_bills_qs.filter(date_filter)
        
        print(f"   Cash Bills Query Count: {cash_bills_qs.count()}")
        cash_bills_total = cash_bills_qs.aggregate(Sum('price'))['price__sum']
        cash_bills = Decimal(str(cash_bills_total)) if cash_bills_total else Decimal('0.00')
        print(f"   Cash Bills Total: {cash_bills}")
        
        # Case 2: Claim Bills
        print("\n2. Calculating Claim Bills...")
        claim_bills_qs = Invoice.objects.filter(
            patient=patient,
            payment_option='Claim'
        )
        
        if date_filter:
            claim_bills_qs = claim_bills_qs.filter(date_filter)
        
        print(f"   Claim Bills Query Count: {claim_bills_qs.count()}")
        claim_bills_total = claim_bills_qs.aggregate(Sum('price'))['price__sum']
        claim_bills = Decimal(str(claim_bills_total)) if claim_bills_total else Decimal('0.00')
        print(f"   Claim Bills Total: {claim_bills}")
        
        # Case 3: Exception Bills 
        print("\n3. Calculating Exception Bills...")
        print("   Looking for records with completed=3 in the following models:")
        
        exception_bills_total = Decimal('0.00')
        
        exception_models = [
            {'model': 'IPDAdministeredDrugs', 'app': 'IPD_Pharm', 'field': 'rate'},
            {'model': 'IPD2AdministeredDrugs', 'app': 'IPD_Pharm2', 'field': 'rate'},
            {'model': 'IPD3AdministeredDrugs', 'app': 'IPD_Pharm3', 'field': 'rate'},
            {'model': 'OPDAdministeredDrugs', 'app': 'OPD_Pharm', 'field': 'rate'},
            {'model': 'OPD2AdministeredDrugs', 'app': 'OPD_Pharm2', 'field': 'rate'},
            {'model': 'RadiologyLab', 'app': 'radio_lab', 'field': 'rate'},
            {'model': 'NurseWaitingList', 'app': 'queue_operations', 'field': 'price'},
            {'model': 'OtherService', 'app': 'queue_operations', 'field': 'price'}
        ]
        
        for item in exception_models:
            model_name = item['model']
            app_name = item['app']
            field_name = item['field']
            
            try:
                from django.apps import apps
                # Using the correct app name for each model
                model = apps.get_model(app_name, model_name)
                print(f"   Checking {app_name}.{model_name}...")
                
                # Building queryset with filters
                qs = model.objects.filter(
                    patient=patient,
                    completed=3
                )
                
                # Apply date filter if not ignored and filter_type is range
                if filter_type == 'range' and date_from and date_to and ignore_date != 'on':
                    try:
                        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                        date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                        from datetime import datetime as dt
                        date_from_datetime = dt.combine(date_from_obj, dt.min.time())
                        date_to_datetime = dt.combine(date_to_obj, dt.max.time())
                        qs = qs.filter(created_date__gte=date_from_datetime, created_date__lte=date_to_datetime)
                        print(f"Applied date filter to {model_name}")
                    except (ValueError, TypeError) as e:
                        print(f"Date filter error for {model_name}: {e}")
                
                # Geting the count and sum
                count = qs.count()
                print(f"      Records found: {count}")
                
                if count > 0:
                    # I'm Debugging here: Showing sample records
                    sample_records = qs[:3]
                    for record in sample_records:
                        print(f"Sample: ID={record.id}, {field_name}={getattr(record, field_name, 0)}, created_date={record.created_date}")
                
                total = qs.aggregate(Sum(field_name))[f'{field_name}__sum']
                if total:
                    exception_bills_total += Decimal(str(total))
                    print(f"{model_name}: Count={count}, Total={total}")
                else:
                    print(f"{model_name}: Count={count}, Total=0")
                    
            except LookupError as e:
                print(f"Model {app_name}.{model_name} not found: {e}")
            except Exception as e:
                print(f"Error processing {app_name}.{model_name}: {e}")
        
        exception_bills = exception_bills_total
        print(f" Exception Bills Total: {exception_bills}")
        
        # Case 4: Total Invoice
        print("\n4. Calculating Total Invoice...")
        total_invoice_qs = Invoice.objects.filter(patient=patient)
        
        if date_filter:
            total_invoice_qs = total_invoice_qs.filter(date_filter)
        
        print(f"   Total Invoice Query Count: {total_invoice_qs.count()}")
        total_invoice_total = total_invoice_qs.aggregate(Sum('price'))['price__sum']
        total_invoice = Decimal(str(total_invoice_total)) if total_invoice_total else Decimal('0.00')
        print(f"   Total Invoice: {total_invoice}")
        
        # Case 5: Payments / Transfers
        print("\n5. Calculating Payments/Transfers...")
        payments_transfers_qs = Receipt.objects.filter(patient=patient)
        
        if date_filter:
            payments_transfers_qs = payments_transfers_qs.filter(date_filter)
        
        print(f"Payments/Transfers Query Count: {payments_transfers_qs.count()}")
        payments_transfers_total = payments_transfers_qs.aggregate(Sum('total_price'))['total_price__sum']
        payments_transfers = Decimal(str(payments_transfers_total)) if payments_transfers_total else Decimal('0.00')
        print(f"   Payments/Transfers: {payments_transfers}")
        
        # Case 6: Deposit
        print("\n6. Calculating Deposit...")
        deposit_qs = Deposit.objects.filter(patient=patient)
        
        if date_filter:
            deposit_qs = deposit_qs.filter(date_filter)
        
        print(f"Deposit Query Count: {deposit_qs.count()}")
        deposit_total = deposit_qs.aggregate(Sum('amount'))['amount__sum']
        deposit = Decimal(str(deposit_total)) if deposit_total else Decimal('0.00')
        print(f"   Deposit: {deposit}")
        
        # Case 7: Transfers / Refunds
        print("\n7. Calculating Transfers/Refunds...")
        transfers_refunds_qs = Refund.objects.filter(patient=patient)
        
        if date_filter:
            transfers_refunds_qs = transfers_refunds_qs.filter(date_filter)
        
        print(f" Transfers/Refunds Query Count: {transfers_refunds_qs.count()}")
        transfers_refunds_total = transfers_refunds_qs.aggregate(Sum('amount'))['amount__sum']
        transfers_refunds = Decimal(str(transfers_refunds_total)) if transfers_refunds_total else Decimal('0.00')
        print(f"Transfers/Refunds: {transfers_refunds}")
        
        # Case 8: Balance
        balance = total_invoice - payments_transfers - transfers_refunds - deposit
        print(f"\nBalance: {balance}")
        print("=" * 60)
    
    context = {
        'patient': patient,
        'cash_bills': cash_bills,
        'exception_bills': exception_bills,
        'claim_bills': claim_bills,
        'total_invoice': total_invoice,
        'payments_transfers': payments_transfers,
        'transfers_refunds': transfers_refunds,
        'deposit': deposit,
        'balance': balance,
        'filter_type': filter_type,
        'date_from': date_from,
        'date_to': date_to,
        'ignore_date': ignore_date,
        'filter_applied': filter_applied,
        'debug_info': {
            'filter_type': filter_type,
            'date_from': date_from,
            'date_to': date_to,
            'ignore_date': ignore_date,
            'cash_bills_count': cash_bills_qs.count() if filter_applied else 0,
            'claim_bills_count': claim_bills_qs.count() if filter_applied else 0,
            'total_invoice_count': total_invoice_qs.count() if filter_applied else 0,
            'payments_transfers_count': payments_transfers_qs.count() if filter_applied else 0,
            'deposit_count': deposit_qs.count() if filter_applied else 0,
            'transfers_refunds_count': transfers_refunds_qs.count() if filter_applied else 0,
            'exception_bills': str(exception_bills),
        }
    }
    
    return render(request, 'Billings/summary.html', context)


def export_summary_excel(request, patient_id):
    """Export summary to Excel"""
    patient = get_object_or_404(PatientProfile, id=patient_id)
    
    # Get filter parameters
    date_from = request.GET.get('date_from', '')
    date_to = request.GET.get('date_to', '')
    ignore_date = request.GET.get('ignore_date', 'off')
    filter_type = request.GET.get('filter_type', 'none')
    
    # Build date filter
    date_filter = Q()
    if filter_type == 'range' and date_from and date_to and ignore_date != 'on':
        try:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            from datetime import datetime as dt
            date_from_datetime = dt.combine(date_from_obj, dt.min.time())
            date_to_datetime = dt.combine(date_to_obj, dt.max.time())
            date_filter = Q(created_date__gte=date_from_datetime) & Q(created_date__lte=date_to_datetime)
        except (ValueError, TypeError):
            pass
    
    # Calculate all totals
    # Cash Bills
    cash_bills_qs = Invoice.objects.filter(
        patient=patient
    ).exclude(
        payment_option='Claim'
    )
    
    if date_filter:
        cash_bills_qs = cash_bills_qs.filter(date_filter)
    
    cash_bills_total = cash_bills_qs.aggregate(Sum('price'))['price__sum']
    cash_bills = Decimal(str(cash_bills_total)) if cash_bills_total else Decimal('0.00')
    
    # Claim Bills
    claim_bills_qs = Invoice.objects.filter(
        patient=patient,
        payment_option='Claim'
    )
    
    if date_filter:
        claim_bills_qs = claim_bills_qs.filter(date_filter)
    
    claim_bills_total = claim_bills_qs.aggregate(Sum('price'))['price__sum']
    claim_bills = Decimal(str(claim_bills_total)) if claim_bills_total else Decimal('0.00')
    
    # Exception Bills
    exception_bills_total = Decimal('0.00')
    
    exception_models = [
        {'model': 'IPDAdministeredDrugs', 'app': 'IPD_Pharm', 'field': 'rate'},
        {'model': 'IPD2AdministeredDrugs', 'app': 'IPD_Pharm2', 'field': 'rate'},
        {'model': 'IPD3AdministeredDrugs', 'app': 'IPD_Pharm3', 'field': 'rate'},
        {'model': 'OPDAdministeredDrugs', 'app': 'OPD_Pharm', 'field': 'rate'},
        {'model': 'OPD2AdministeredDrugs', 'app': 'OPD_Pharm2', 'field': 'rate'},
        {'model': 'RadiologyLab', 'app': 'radio_lab', 'field': 'rate'},
        {'model': 'NurseWaitingList', 'app': 'queue_operations', 'field': 'price'},
        {'model': 'OtherService', 'app': 'queue_operations', 'field': 'price'}
    ]
    
    for item in exception_models:
        model_name = item['model']
        app_name = item['app']
        field_name = item['field']
        
        try:
            from django.apps import apps
            model = apps.get_model(app_name, model_name)
            
            qs = model.objects.filter(
                patient=patient,
                completed=3
            )
            
            if filter_type == 'range' and date_from and date_to and ignore_date != 'on':
                try:
                    date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
                    date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
                    from datetime import datetime as dt
                    date_from_datetime = dt.combine(date_from_obj, dt.min.time())
                    date_to_datetime = dt.combine(date_to_obj, dt.max.time())
                    qs = qs.filter(created_date__gte=date_from_datetime, created_date__lte=date_to_datetime)
                except (ValueError, TypeError):
                    pass
            
            total = qs.aggregate(Sum(field_name))[f'{field_name}__sum']
            if total:
                exception_bills_total += Decimal(str(total))
        except Exception as e:
            print(f"Error processing {app_name}.{model_name}: {e}")
    
    exception_bills = exception_bills_total
    
    # Total Invoice
    total_invoice_qs = Invoice.objects.filter(patient=patient)
    
    if date_filter:
        total_invoice_qs = total_invoice_qs.filter(date_filter)
    
    total_invoice_total = total_invoice_qs.aggregate(Sum('price'))['price__sum']
    total_invoice = Decimal(str(total_invoice_total)) if total_invoice_total else Decimal('0.00')
    
    # Payments / Transfers
    payments_transfers_qs = Receipt.objects.filter(patient=patient)
    
    if date_filter:
        payments_transfers_qs = payments_transfers_qs.filter(date_filter)
    
    payments_transfers_total = payments_transfers_qs.aggregate(Sum('total_price'))['total_price__sum']
    payments_transfers = Decimal(str(payments_transfers_total)) if payments_transfers_total else Decimal('0.00')
    
    # Deposit
    deposit_qs = Deposit.objects.filter(patient=patient)
    
    if date_filter:
        deposit_qs = deposit_qs.filter(date_filter)
    
    deposit_total = deposit_qs.aggregate(Sum('amount'))['amount__sum']
    deposit = Decimal(str(deposit_total)) if deposit_total else Decimal('0.00')
    
    # Transfers / Refunds
    transfers_refunds_qs = Refund.objects.filter(patient=patient)
    
    if date_filter:
        transfers_refunds_qs = transfers_refunds_qs.filter(date_filter)
    
    transfers_refunds_total = transfers_refunds_qs.aggregate(Sum('amount'))['amount__sum']
    transfers_refunds = Decimal(str(transfers_refunds_total)) if transfers_refunds_total else Decimal('0.00')
    
    # Balance
    balance = total_invoice - payments_transfers - transfers_refunds 
    
    # Create workbook
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Patient Summary"
    
    # Define styles
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="343a40", end_color="343a40", fill_type="solid")
    header_alignment = Alignment(horizontal="center", vertical="center")
    
    # Headers
    headers = ['Patient', 'Cash Bills', 'Exception Bills', 'Claim Bills', 
               'Total Invoice', 'Payments / Transfers', 'Deposit', 'Transfers / Refunds', 'Balance']
    
    for col, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
    
    # Get patient identifier
    patient_identifier = None
    if hasattr(patient, 'patient_id'):
        patient_identifier = patient.patient_id
    elif hasattr(patient, 'patient_code'):
        patient_identifier = patient.patient_code
    elif hasattr(patient, 'hospital_id'):
        patient_identifier = patient.hospital_id
    else:
        patient_identifier = patient.id
    
    # Create patient display name
    patient_name = f"{patient.surname} {patient.first_name}"
    if patient_identifier:
        patient_name += f" [{patient_identifier}]"
    
    # Data row
    row = 2
    ws.cell(row=row, column=1, value=patient_name)
    ws.cell(row=row, column=2, value=float(cash_bills))
    ws.cell(row=row, column=3, value=float(exception_bills))
    ws.cell(row=row, column=4, value=float(claim_bills))
    ws.cell(row=row, column=5, value=float(total_invoice))
    ws.cell(row=row, column=6, value=float(payments_transfers))
    ws.cell(row=row, column=7, value=float(deposit))
    ws.cell(row=row, column=8, value=float(transfers_refunds))
    ws.cell(row=row, column=9, value=float(balance))
    
    # Grand Total row
    row = 3
    grand_total_font = Font(bold=True)
    ws.cell(row=row, column=1, value='Grand Total').font = grand_total_font
    ws.cell(row=row, column=2, value=float(cash_bills)).font = grand_total_font
    ws.cell(row=row, column=3, value=float(exception_bills)).font = grand_total_font
    ws.cell(row=row, column=4, value=float(claim_bills)).font = grand_total_font
    ws.cell(row=row, column=5, value=float(total_invoice)).font = grand_total_font
    ws.cell(row=row, column=6, value=float(payments_transfers)).font = grand_total_font
    ws.cell(row=row, column=7, value=float(deposit)).font = grand_total_font
    ws.cell(row=row, column=8, value=float(transfers_refunds)).font = grand_total_font
    ws.cell(row=row, column=9, value=float(balance)).font = grand_total_font
    
    # Auto-adjust column widths
    for col in range(1, len(headers) + 1):
        column_letter = get_column_letter(col)
        ws.column_dimensions[column_letter].width = 20
    
    # Create response
    filename_identifier = patient_identifier if patient_identifier else patient.id
    response = HttpResponse(content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="patient_summary_{filename_identifier}_{datetime.now().strftime("%Y%m%d")}.xlsx"'
    
    wb.save(response)
    return response


@login_required
@department_required('Billings', 'Admin', 'CMD')
def transaction_day_book(request):
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    transaction_type = request.GET.get('type', 'All')
    patient_search = request.GET.get('patient', '')
    patient_type = request.GET.get('patient_type', 'All')
    service_type = request.GET.get('service_type', 'All')
    
    # Get current time in local timezone
    now = timezone.now()
    today = now.date()
    
    # Starting with all invoices
    invoices = Invoice.objects.filter(price__gt=0).select_related('patient', 'category', 'patient__plan')
    
    # Apply date filter
    if start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            start_datetime = timezone.make_aware(
                datetime.combine(start_date_obj, datetime.min.time())
            )
            end_datetime = timezone.make_aware(
                datetime.combine(end_date_obj, datetime.max.time())
            )
            
            invoices = invoices.filter(
                created_date__gte=start_datetime,
                created_date__lte=end_datetime
            )
        except ValueError:
            start_datetime = timezone.make_aware(
                datetime.combine(today, datetime.min.time())
            )
            end_datetime = timezone.make_aware(
                datetime.combine(today, datetime.max.time())
            )
            invoices = invoices.filter(
                created_date__gte=start_datetime,
                created_date__lte=end_datetime
            )
    else:
        # Default to today's records
        start_datetime = timezone.make_aware(
            datetime.combine(today, datetime.min.time())
        )
        end_datetime = timezone.make_aware(
            datetime.combine(today, datetime.max.time())
        )
        invoices = invoices.filter(
            created_date__gte=start_datetime,
            created_date__lte=end_datetime
        )
    
    # Apply category/type filter
    if transaction_type != 'All':
        try:
            invoices = invoices.filter(category__name__iexact=transaction_type)
        except:
            try:
                invoices = invoices.filter(category__title__iexact=transaction_type)
            except:
                try:
                    invoices = invoices.filter(category__category__iexact=transaction_type)
                except:
                    invoices = invoices.filter(category__iexact=transaction_type)
    
    # Apply patient search filter using Haystack
    if patient_search:
        # Search for patients matching the query
        search_results = SearchQuerySet().models(PatientProfile).filter(content=patient_search)
        patient_ids = [result.pk for result in search_results]
        
        if patient_ids:
            invoices = invoices.filter(patient__id__in=patient_ids)
        else:
            # If no results from search, try direct lookup
            invoices = invoices.filter(
                Q(patient__hospital_number__icontains=patient_search) |
                Q(patient__first_name__icontains=patient_search) |
                Q(patient__surname__icontains=patient_search)
            )
    
    # Apply patient type filter
    if patient_type != 'All':
        invoices = invoices.filter(patient__plan__plan__iexact=patient_type)
    
    # Apply service type filter
    if service_type != 'All':
        # Mapping service types to original_source_model values
        service_type_mapping = {
            'Registration': 'GetRegistrationFee',
            'Consultation': 'NurseWaitingList',
            'Medication': ['IPDAdministeredDrugs', 'IPD2AdministeredDrugs', 'IPD3AdministeredDrugs', 
                          'OPDAdministeredDrugs', 'OPD2AdministeredDrugs'],
            'Investigations': 'RadiologyLab',
            'Services': 'OtherService',
            'Admission': 'AdmissionFee',
            'Antenatal': 'AntenatalFee',  
        }
        
        mapping_value = service_type_mapping.get(service_type)
        if mapping_value:
            if isinstance(mapping_value, list):
                invoices = invoices.filter(original_source_model__in=mapping_value)
            else:
                invoices = invoices.filter(original_source_model=mapping_value)
    
    # Group invoices by invoice_number
    grouped_invoices = defaultdict(lambda: {
        'date': None,
        'patient': None,
        'patient_id': None,
        'details': set(),
        'total_revenue': 0,
        'collections': 0,
        'refunds': 0,
        'invoice_number': None
    })
    
    # Aggregate invoice data by invoice_number
    for invoice in invoices:
        inv_num = invoice.invoice_number
        
        if not grouped_invoices[inv_num]['invoice_number']:
            grouped_invoices[inv_num]['invoice_number'] = inv_num
            grouped_invoices[inv_num]['date'] = invoice.created_date
            
            # Get patient info
            if invoice.patient:
                patient_name = invoice.patient.get_full_name() if hasattr(invoice.patient, 'get_full_name') else f"{invoice.patient.surname} {invoice.patient.first_name}"
                patient_id = getattr(invoice.patient, 'hospital_number', 'N/A')
                patient_url = invoice.patient
                grouped_invoices[inv_num]['patient'] = patient_name
                grouped_invoices[inv_num]['patient_id'] = patient_id
                grouped_invoices[inv_num]['patient_url'] = patient_url
            else:
                grouped_invoices[inv_num]['patient'] = 'N/A'
                grouped_invoices[inv_num]['patient_id'] = 'N/A'
                grouped_invoices[inv_num]['patient_url'] = 'N/A'
        
        # Add details without duplication
        details = get_details_from_source_model(invoice.original_source_model)
        grouped_invoices[inv_num]['details'].add(details)
        
        # Sum up revenue for this invoice number
        grouped_invoices[inv_num]['total_revenue'] += invoice.price
    
    # Get collections and refunds for each invoice number
    for inv_num in grouped_invoices.keys():
        # Get total collections from Receipt model
        receipts = Receipt.objects.filter(invoice_number__iexact=inv_num)
        collections = receipts.aggregate(total=Sum('total_price'))['total'] or 0
        grouped_invoices[inv_num]['collections'] = collections
        
        # Get total refunds from Refund model
        refunds = Refund.objects.filter(invoice_id__iexact=inv_num)
        refund_amount = refunds.aggregate(total=Sum('amount'))['total'] or 0
        grouped_invoices[inv_num]['refunds'] = refund_amount
    
    # Prepare the final day book entries
    day_book_entries = []
    total_revenues = 0
    total_collections = 0
    total_refunds = 0
    total_balance = 0
    
    for inv_num, data in grouped_invoices.items():
        # Calculate balance
        balance = data['total_revenue'] - data['collections']
        
        # Convert details set to sorted list and join with comma
        details_list = sorted(list(data['details']))
        details_text = ', '.join(details_list)
        
        entry = {
            'date': data['date'].strftime('%d %b %Y') if data['date'] else '',
            'patient': data['patient'],
            'patient_id': data['patient_id'],
            'patient_url': data['patient_url'],
            'details': details_text,
            'details_list': details_list,
            'revenue': data['total_revenue'],
            'collections': data['collections'],
            'settled': 0,
            'refunds': data['refunds'],
            'balance': balance,
            'invoice_number': inv_num,
        }
        
        day_book_entries.append(entry)
        
        # Update totals
        total_revenues += data['total_revenue']
        total_collections += data['collections']
        total_refunds += data['refunds']
        total_balance += balance
    
    # Sort by date (newest first)
    day_book_entries.sort(key=lambda x: x['date'], reverse=True)
    
    # Get distinct patient types for filter dropdown
    patient_types = PatientProfile.objects.filter(
        plan__plan__isnull=False
    ).values_list('plan__plan', flat=True).distinct()
    patient_types = [pt for pt in patient_types if pt]  
    patient_types = sorted(set(patient_types))
    
    context = {
        'day_book_entries': day_book_entries,
        'total_revenues': total_revenues,
        'total_collections': total_collections,
        'total_refunds': total_refunds,
        'total_balance': total_balance,
        'start_date': start_date or today.strftime('%Y-%m-%d'),
        'end_date': end_date or today.strftime('%Y-%m-%d'),
        'transaction_type': transaction_type,
        'patient_search': patient_search,
        'patient_type': patient_type,
        'service_type': service_type,
        'patient_types': patient_types,
        'current_date': timezone.now(),
        'has_data': len(day_book_entries) > 0,
        'entries_count': len(day_book_entries),
    }
    
    return render(request, 'Billings/day_book.html', context)


def get_details_from_source_model(source_model):
    """Helper function to map original_source_model to Details field"""
    if not source_model:
        return 'Services'
    
    medication_models = [
        'IPDAdministeredDrugs', 'IPD2AdministeredDrugs', 
        'IPD3AdministeredDrugs', 'OPDAdministeredDrugs', 
        'OPD2AdministeredDrugs'
    ]
    
    source_model_lower = source_model.lower()
    
    if source_model in medication_models:
        return 'Medication'
    elif source_model == 'RadiologyLab' or source_model_lower == 'radiologylab':
        return 'Investigations'
    elif source_model == 'NurseWaitingList' or source_model_lower == 'nursewaitinglist':
        return 'Consultation'
    elif source_model == 'OtherService' or source_model_lower == 'otherservice':
        return 'Services'
    elif source_model == 'AdmissionFee' or source_model_lower == 'admissionfee':
        return 'Admission'
    elif source_model == 'GetRegistrationFee' or source_model_lower == 'getregistrationfee':
        return 'Registration'
    else:
        return 'Services'


def patient_search_api(request):
    query = request.GET.get('q', '')
    
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    # Haystack for search
    search_results = SearchQuerySet().models(PatientProfile).filter(content=query)[:10]
    
    results = []
    for result in search_results:
        patient = result.object
        results.append({
            'id': patient.id,
            'full_name': patient.get_full_name(),
            'hospital_number': getattr(patient, 'hospital_number', ''),
            'first_name': patient.first_name,
            'surname': patient.surname,
        })
    
    # If no results from Haystack, try direct lookup
    if not results:
        direct_results = PatientProfile.objects.filter(
            Q(hospital_number__icontains=query) |
            Q(first_name__icontains=query) |
            Q(surname__icontains=query)
        )[:10]
        
        for patient in direct_results:
            results.append({
                'id': patient.id,
                'full_name': patient.get_full_name(),
                'hospital_number': getattr(patient, 'hospital_number', ''),
                'first_name': patient.first_name,
                'surname': patient.surname,
            })
    
    return JsonResponse({'results': results})
