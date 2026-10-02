from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from inventory.decorators import department_required
from xhtml2pdf import pisa
from django.template.loader import get_template
from datetime import datetime, time, timedelta
from io import BytesIO
from django.utils.timezone import make_aware
from users.models import User
from patients.models import PatientPlan, PatientCategory, PatientProfile
from queue_operations.models import NurseWaitingList, DoctorWaitingList, PatientEncounter
from Billings.models import Invoice, Receipt, Refund
from IPD.models import AdmissionTable, Ward
from django.db.models import Sum, Q, F
import openpyxl
import re
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
from collections import defaultdict
import logging
from django.utils.timezone import timedelta
from django.apps import apps

logger = logging.getLogger(__name__)

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def ambulatory_patient_report(request):
    # Clear the download flag so it doesn't show every page load
    if request.session.get('show_success_after_download'):
        del request.session['show_success_after_download']
    # Check if user actually clicked "Generate" 
    if request.GET.get('generate'):
        date_from = request.GET.get('date_from', '').strip()
        date_to = request.GET.get('date_to', '').strip()
        sponsor_id = request.GET.get('sponsor', '').strip()
        patient_type = request.GET.get('patient_type', '').strip()
        registrar_id = request.GET.get('registrar', '').strip()
        orientation = request.GET.get('orientation', 'Landscape')
        destination = request.GET.get('destination', 'MS Excel')

        patients = PatientProfile.objects.filter(active=1).exclude(created_date__isnull=True)

        # Applying filters only when they have values
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        sponsor_id = request.GET.get('sponsor')
        patient_type = request.GET.get('patient_type')
        registrar_id = request.GET.get('registrar')

        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            start_dt = make_aware(datetime.combine(date_from_obj, time.min))
            patients = patients.filter(created_date__gte=start_dt)

        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            end_dt = make_aware(datetime.combine(date_to_obj, time.max))
            patients = patients.filter(created_date__lte=end_dt)

        if sponsor_id and sponsor_id not in ['', 'None']:
            patients = patients.filter(plan_id=int(sponsor_id))
        if patient_type and patient_type not in ['', 'None']:
            patients = patients.filter(category_id=int(patient_type))
        if registrar_id and registrar_id not in ['', 'None']:
            patients = patients.filter(created_by_id=int(registrar_id))

        print("Final count:", patients.count()) # should be 33 now

        patients = patients.select_related('plan', 'category', 'created_by').order_by('-created_date')

        if not patients.exists():
            messages.error(request, 'No records found for the selected filters.')
            return redirect('ambulatory_report')

        # Generate filename with filter date
        today_str = datetime.now().strftime('%Y%m%d')
        date_filter_str = ''
        if date_from and date_to:
            date_filter_str = f"_{date_from}_to_{date_to}"
        elif date_from:
            date_filter_str = f"_from_{date_from}"
        elif date_to:
            date_filter_str = f"_to_{date_to}"

        filename = f"ISALU_HOSPITALS_ambulatory_patient_registration_filtered_date{date_filter_str}_{today_str}"

        if destination == 'MS Excel':
            messages.success(request, f'Report generated successfully! {patients.count()} records exported.')
            response = generate_excel_report(patients, filename, orientation)
            request.session['show_success_after_download'] = True
            return response
        else:
            messages.success(request, f'PDF generated! {patients.count()} records exported.')
            return generate_pdf_report(request, patients, filename, orientation)

    # Load filter dropdowns
    context = {
        'sponsors': PatientPlan.objects.all(),
        'patient_types': PatientCategory.objects.all(),
        'registrars': User.objects.filter(is_active=True, patientprofile__isnull=False).distinct()
    }
    return render(request, 'Reporting/ambulatory_report_registration.html', context)

def generate_excel_report(patients, filename, orientation):
    wb = Workbook()
    ws = wb.active
    ws.title = "Ambulatory Patients"

    # Page setup
    if orientation == 'Landscape':
        ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    else:
        ws.page_setup.orientation = ws.ORIENTATION_PORTRAIT
    ws.page_setup.paperSize = ws.PAPERSIZE_A4

    # Header styling
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")

    headers = [
        'S/N', 'UPI', 'Hospital Number', 'Title', 'Surname', 'First Name',
        'Middle Name', 'Full Name', 'Phone', 'Email', 'Address', 'Sponsor',
        'Patient Type', 'Gender', 'Date of Birth', 'Marital Status',
        'Next of Kin', 'Next of Kin Relationship', 'Next of Kin Phone',
        'Registered By', 'Registered At'
    ]

    ws.append(headers)
    for cell in ws[1]:
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')

    # Data rows
    for idx, patient in enumerate(patients, start=1):
        # Title logic: Mr / Mrs / Miss
        if patient.gender == 'Male':
            title = 'Mr.'
        elif patient.gender == 'Female' and patient.patient_type == 'Married':
            title = 'Mrs'
        else:
            title = 'Miss'

        row = [
            idx, # S/N
            patient.insurance_policy_number or '',
            patient.hospital_number or '',
            title,
            patient.surname,
            patient.first_name,
            patient.other_name or '',
            patient.get_full_name(),
            patient.phone_number,
            patient.email_address or '',
            patient.address or '',
            patient.plan.plan if patient.plan else '',
            patient.category.category if patient.category else '',
            patient.gender,
            patient.dob.strftime('%Y-%m-%d') if patient.dob else '',
            patient.patient_type or '',
            patient.full_name or '', # Next of Kin
            patient.relationship_to_patient or '',
            patient.phone_numbers or '',
            patient.created_by.fullname if patient.created_by else '',
            patient.created_date.strftime('%Y-%m-%d %H:%M') if patient.created_date else ''
        ]
        ws.append(row)

    # Auto-adjust column widths
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    # Save to response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response

def generate_pdf_report(request, patients, filename, orientation):
    template_path = 'Reporting/PDF/ambulatory_report_pdf.html'
    context = {
        'patients': patients,
        'orientation': orientation,
        'generated_date': datetime.now()
    }

    template = get_template(template_path)
    html = template.render(context)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="{filename}.pdf"'

    pisa_status = pisa.CreatePDF(html, dest=response)
    if pisa_status.err:
        return HttpResponse('PDF generation error')
    return response



@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def ambulatory_visit_report(request):
    if request.GET.get('generate'):
        # Get filters
        date_from = request.GET.get('date_from')
        date_to = request.GET.get('date_to')
        if not date_from:
            messages.error(request, 'Please select a "Date From" to generate the report.')
            return redirect('ambulatory_visit_report')
        
        sponsor_id = request.GET.get('sponsor')
        patient_type_id = request.GET.get('patient_type')
        purpose = request.GET.get('purpose', '').strip()
        visit_type = request.GET.get('visit_type', '').strip()
        registrar_id = request.GET.get('registrar')
        orientation = request.GET.get('orientation', 'Landscape')
        
        # Base: NurseWaitingList = 1 visit record
        visits = NurseWaitingList.objects.select_related(
            'patient', 'patient__plan', 'patient__category', 'patient__created_by'
        ).exclude(created_date__isnull=True)

        # Date filter on visit date
        if date_from:
            date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
            start_dt = make_aware(datetime.combine(date_from_obj, time.min))
            visits = visits.filter(created_date__gte=start_dt)

        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            end_dt = make_aware(datetime.combine(date_to_obj, time.max))
            visits = visits.filter(created_date__lte=end_dt)

        # Patient filters
        if sponsor_id and sponsor_id not in ['', 'None']:
            visits = visits.filter(patient__plan_id=int(sponsor_id))
        if patient_type_id and patient_type_id not in ['', 'None']:
            visits = visits.filter(patient__category_id=int(patient_type_id))
        if registrar_id and registrar_id not in ['', 'None']:
            visits = visits.filter(attendant_id=int(registrar_id))

        # Visit filters
        if purpose:
            visits = visits.filter(purpose__icontains=purpose)
        if visit_type:
            visits = visits.filter(visit_type=visit_type)

        visits = visits.order_by(F('created_date').desc(nulls_last=True))

        if not visits.exists():
            messages.error(request, 'No visits found for the selected filters.')
            return redirect('ambulatory_visit_report')

        # Filename
        today_str = datetime.now().strftime('%Y%m%d')
        date_filter_str = ''
        if date_from and date_to:
            date_filter_str = f"_{date_from}_to_{date_to}"
        filename = f"ISALU_HOSPITALS_ambulatory_visit_report_filtered_date{date_filter_str}_{today_str}"

        return generate_ambulatory_excel_v2(visits, filename, orientation)

    context = {
        'sponsors': PatientPlan.objects.all(),
        'patient_types': PatientCategory.objects.all(),
        'registrars': User.objects.filter(
            is_active=True, 
            nursewaitinglist__isnull=False
        ).distinct().order_by('fullname'),
        'visit_types': NurseWaitingList.VISIT_TYPE_CHOICES,
        'purposes': NurseWaitingList.objects.values_list('purpose', flat=True).distinct().order_by('purpose')
    }
    return render(request, 'Reporting/ambulatory_visit_filter.html', context)

def strip_bracket_content(text):
    if not text:
        return ''
    return re.sub(r'\s*\(.*?\)', '', text).strip()



def generate_ambulatory_excel_v2(visits, filename, orientation):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Ambulatory Visits"

    headers = [
        'S/N', 'Hospital Number', 'UPI', 'Title', 'Surname', 'First Name', 'Middle Name',
        'Full Name', 'Phone', 'Email', 'Address', 'Sponsor', 'Patient Type', 'Gender',
        'Date of Birth', 'Marital Status', 'Purpose', 'Visit type', 'Diagnosis',
        'Examinations', 'Presenting Complaints', 'History of present Illness',
        'Visit Date', 'Visit Time', 'Visited Department', 'Clinicians', 'Attendant'
    ]
    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = openpyxl.styles.PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        cell.alignment = Alignment(horizontal="center")

    for idx, visit in enumerate(visits, start=1):
        patient = visit.patient
        if not patient:
            continue

        # Title logic
        if patient.gender == 'Male':
            title = 'Mr.'
        elif patient.gender == 'Female' and patient.patient_type == 'Married':
            title = 'Mrs'
        else:
            title = 'Miss'

        # Time window: same day + next day to catch late entries
        start_window = make_aware(datetime.combine(visit.created_date.date(), time.min))
        end_window = start_window + timedelta(days=1, hours=23, minutes=59)

        # 1. PatientEncounter: get first encounter AFTER nurse visit within 2 days
        encounter = PatientEncounter.objects.filter(
            patient=patient,
            created_at__gte=visit.created_date, # after nurse saw patient
            created_at__lte=end_window # within ~2 days
        ).order_by('created_at').first()

        # 2. DoctorWaitingList: get all doctors linked to this patient within window
        # check completed_by exists
        doctor_entries = DoctorWaitingList.objects.filter(
            patient=patient,
            created_date__gte=start_window,
            created_date__lte=end_window
        ).exclude(completed_by__isnull=True).exclude(completed_by='').values_list('completed_by', flat=True)

        clinicians_str = ', '.join(sorted(set(filter(None, doctor_entries))))

        row = [
            idx,
            patient.hospital_number or '',
            patient.insurance_policy_number or '',
            title,
            patient.surname,
            patient.first_name,
            patient.other_name or '',
            patient.get_full_name(),
            patient.phone_number,
            patient.email_address or '',
            patient.address or '',
            patient.plan.plan if patient.plan else '',
            patient.category.category if patient.category else '',
            patient.gender,
            patient.dob.strftime('%Y-%m-%d') if patient.dob else '',
            patient.patient_type or '',
            visit.purpose or '',
            visit.visit_type or '',
            encounter.diagnosis if encounter else '',
            encounter.comments_on_diagnosis if encounter else '',
            encounter.chief_complaint if encounter else '',
            encounter.history_of_present_illness if encounter else '',
            visit.created_date.strftime('%Y-%m-%d'),
            visit.created_date.strftime('%H:%M'),
            strip_bracket_content(visit.purpose),
            clinicians_str,
            visit.attendant.fullname or '',
        ]
        ws.append(row)

    # Auto-width same as before
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response

TRANSACTION_TYPE_MAP = {
    'OtherService': 'Service',
    'AntenatalFee': 'Antenatal',
    'NurseWaitingList': 'Consultation',
    'RegistrationFee': 'Registration',
    'AdmissionFee': 'Admission',
    'RadiologyLab': 'TestGroup',
    'IPDAdministeredDrugs': 'Item/Medication',
    'IPD2AdministeredDrugs': 'Item/Medication',
    'IPD3AdministeredDrugs': 'Item/Medication',
    'OPDAdministeredDrugs': 'Item/Medication',
    'OPD2AdministeredDrugs': 'Item/Medication',
}

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def billing_invoice_listing(request):
    if request.GET.get('generate'):
        date_from = request.GET.get('date_from')
        if not date_from:
            messages.error(request, 'Please select a "Date From" to generate the report.')
            return redirect('billing_invoice_listing')

        date_to = request.GET.get('date_to')
        sponsor_id = request.GET.get('sponsor')
        patient_type_id = request.GET.get('patient_type')
        transaction_type = request.GET.get('transaction_type', '').strip()
        payment_type = request.GET.get('payment_type', '').strip()
        billing_officer_id = request.GET.get('billing_officer')
        orientation = request.GET.get('orientation', 'Landscape')

        # Base: Invoice
        invoices = Invoice.objects.select_related(
            'patient', 'patient__plan', 'patient__category', 'staff'
        ).exclude(created_date__isnull=True).exclude(patient__isnull=True)

        # Date filters on Invoice.created_date
        date_from_obj = datetime.strptime(date_from, '%Y-%m-%d').date()
        start_dt = make_aware(datetime.combine(date_from_obj, time.min))
        invoices = invoices.filter(created_date__gte=start_dt)

        if date_to:
            date_to_obj = datetime.strptime(date_to, '%Y-%m-%d').date()
            end_dt = make_aware(datetime.combine(date_to_obj, time.max))
            invoices = invoices.filter(created_date__lte=end_dt)

        # Patient filters
        if sponsor_id and sponsor_id not in ['', 'None']:
            invoices = invoices.filter(patient__plan_id=int(sponsor_id))
        if patient_type_id and patient_type_id not in ['', 'None']:
            invoices = invoices.filter(patient__category_id=int(patient_type_id))

        # Invoice filters
        if payment_type:
            invoices = invoices.filter(payment_option__iexact=payment_type)
        if billing_officer_id and billing_officer_id not in ['', 'None']:
            invoices = invoices.filter(staff_id=int(billing_officer_id))

        # Transaction Type filter - reverse map the display name to model names
        if transaction_type and transaction_type!= 'All':
            models_for_type = [k for k, v in TRANSACTION_TYPE_MAP.items() if v == transaction_type]
            invoices = invoices.filter(original_source_model__in=models_for_type)

        invoices = invoices.order_by(F('created_date').desc(nulls_last=True))

        if not invoices.exists():
            messages.error(request, 'No invoices found for the selected filters.')
            return redirect('billing_invoice_listing')

        today_str = datetime.now().strftime('%Y%m%d')
        date_filter_str = f"_{date_from}"
        if date_to:
            date_filter_str += f"_to_{date_to}"
        filename = f"ISALU_HOSPITALS_billing_invoice_listing_filtered_date{date_filter_str}_{today_str}"

        return generate_invoice_excel(invoices, filename, orientation)

    context = {
        'sponsors': PatientPlan.objects.all(),
        'patient_types': PatientCategory.objects.all(),
        'billing_officers': User.objects.filter(
            is_active=True, invoice__isnull=False
        ).distinct().order_by('fullname'),
        'transaction_types': ['All'] + sorted(set(TRANSACTION_TYPE_MAP.values())),
        'payment_types': Invoice.objects.values_list('payment_option', flat=True)
                        .exclude(payment_option__isnull=True).exclude(payment_option='')
                        .distinct().order_by('payment_option')
    }
    return render(request, 'Reporting/billing_invoice_filter.html', context)


def generate_invoice_excel(invoices, filename, orientation):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Invoice Listing"

    headers = [
        'S/N', 'Hospital Number', 'Title', 'Surname', 'First Name', 'Middle Name',
        'Full Name', 'UPI', 'Phone', 'Email', 'Address', 'Sponsor', 'Patient Type',
        'Gender', 'Date of Birth', 'Marital Status', 'Transaction Date',
        'Transaction Description', 'Transaction Type', 'Payment Type', 'Currency',
        'Amount', 'Allocated', 'Outstanding', 'Created Date & Time', 'Created By'
    ]
    ws.append(headers)

    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = openpyxl.styles.PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        cell.alignment = Alignment(horizontal="center")

    for idx, inv in enumerate(invoices, start=1):
        patient = inv.patient

        if patient.gender == 'Male':
            title = 'Mr.'
        elif patient.gender == 'Female' and patient.patient_type == 'Married':
            title = 'Mrs'
        else:
            title = 'Miss'

        txn_type = TRANSACTION_TYPE_MAP.get(inv.original_source_model, inv.original_source_model or '')

        amount = float(inv.price or 0) # ensure float for formatting
        if inv.payment_option and inv.payment_option.lower() == 'claim':
            allocated = 0.00
        elif inv.completed == 1:
            allocated = float(amount)
        else:
            allocated = 0.00

        outstanding = allocated - amount

        row = [
            idx,
            patient.hospital_number or '',
            title,
            patient.surname,
            patient.first_name,
            patient.other_name or '',
            patient.get_full_name(),
            patient.insurance_policy_number or '',
            patient.phone_number,
            patient.email_address or '',
            patient.address or '',
            patient.plan.plan if patient.plan else '',
            patient.category.category if patient.category else '',
            patient.gender,
            patient.dob.strftime('%Y-%m-%d') if patient.dob else '',
            patient.patient_type or '',
            inv.created_date.strftime('%Y-%m-%d'),
            inv.product or '',
            txn_type,
            inv.payment_option or '',
            'NGN',
            amount, # Col V
            allocated, # Col W
            outstanding, # Col X
            inv.created_date.strftime('%Y-%m-%d %H:%M:%S'),
            inv.staff.fullname if inv.staff else ''
        ]
        ws.append(row)

        # Applyinging money format to Amount, Allocated, Outstanding columns
        current_row = ws.max_row
        ws[f'V{current_row}'].number_format = '#,##0.00' # Amount
        ws[f'W{current_row}'].number_format = '#,##0.00' # Allocated
        ws[f'X{current_row}'].number_format = '#,##0.00' # Outstanding

    # Auto-width
    for column in ws.columns:
        max_length = 0
        column_letter = column[0].column_letter
        for cell in column:
            try:
                if len(str(cell.value)) > max_length:
                    max_length = len(str(cell.value))
            except:
                pass
        adjusted_width = min(max_length + 2, 50)
        ws.column_dimensions[column_letter].width = adjusted_width

    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}.xlsx"'
    wb.save(response)
    return response


logger = logging.getLogger(__name__)


@login_required
@department_required('Reporting', 'Admin', 'CMD')
def transaction_book_report(request):
    """Generate Transaction Book Report with filters"""
    
    # Checking for an export request (form submission)
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    sponsor = request.GET.get('sponsor', 'All')
    patient_type = request.GET.get('patient_type', 'All')
    payment_type = request.GET.get('payment_type', 'All')
    billing_officer = request.GET.get('billing_officer', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # If no date range, default to today
    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    
    # Get unique sponsors from PatientPlan model
    sponsors = PatientPlan.objects.filter(
        plan__isnull=False
    ).exclude(plan='').values_list('plan', flat=True).distinct().order_by('plan')
    sponsors = [s for s in sponsors if s]  # Remove empty values
    
    # Get unique patient types from PatientCategory model
    patient_types = PatientCategory.objects.filter(
        category__isnull=False
    ).exclude(category='').values_list('category', flat=True).distinct().order_by('category')
    patient_types = [pt for pt in patient_types if pt]  # Removing empty values
    
    # Get unique payment options from Invoice model
    payment_options = Invoice.objects.filter(
        payment_option__isnull=False
    ).exclude(payment_option='').values_list('payment_option', flat=True).distinct().order_by('payment_option')
    payment_options = [po for po in payment_options if po]  # Removing empty values
    
    # Get unique billing officers from User model (via Invoice staff)
    billing_officer_ids = Invoice.objects.filter(
        staff__isnull=False
    ).values_list('staff__id', flat=True).distinct()
    
    billing_officers = User.objects.filter(
        id__in=billing_officer_ids
    ).values_list('id', 'fullname').distinct().order_by('fullname')
    
    billing_officers = [
        {'id': uid, 'fullname': f"{fullname}".strip() or 'Unknown'}
        for uid, fullname in billing_officers
    ]
    
    # If no billing officers found, add a placeholder
    if not billing_officers:
        billing_officers = [{'id': '', 'fullname': 'No officers found'}]
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'sponsor': sponsor,
        'patient_type': patient_type,
        'payment_type': payment_type,
        'billing_officer': billing_officer,
        'sponsors': sponsors,
        'patient_types': patient_types,
        'payment_options': payment_options,
        'billing_officers': billing_officers,
        'orientation': orientation,
        'destination': destination,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/transaction_book.html', context)


def generate_export(request, context):
    """Generate Excel or PDF export"""
    
    # Build the queryset with filters
    invoices = get_filtered_invoices(context)
    
    # Log the count for debugging
    logger.info(f"Found {invoices.count()} invoices matching filters")
    
    if invoices.count() == 0:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    # Group by invoice number
    grouped_data = group_invoices_by_patient(invoices)
    
    logger.info(f"Grouped into {len(grouped_data)} transactions")
    
    # Prepare export data
    export_data = prepare_export_data(grouped_data)
    
    logger.info(f"Prepared {len(export_data)} rows for export")
    
    if len(export_data) == 0:
        return HttpResponse("No valid patient data found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_to_excel(export_data, context)
    
    # Generate PDF 
    else:
        return export_to_pdf(export_data, context)


def get_filtered_invoices(context):
    """Applying all filters to the Invoice queryset"""
    
    invoices = Invoice.objects.filter(price__gt=0).select_related(
        'patient', 'patient__plan', 'patient__category', 'staff'
    )
    
    # Date filter
    start_date = context.get('start_date')
    end_date = context.get('end_date')
    
    if start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            start_datetime = datetime.combine(start_date_obj, datetime.min.time())
            end_datetime = datetime.combine(end_date_obj, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                start_datetime = timezone.make_aware(start_datetime)
                end_datetime = timezone.make_aware(end_datetime)
            
            invoices = invoices.filter(
                created_date__isnull=False,
                created_date__gte=start_datetime,
                created_date__lte=end_datetime
            )
            logger.info(f"Date filter applied: {start_date} to {end_date}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    else:
        today = timezone.now().date()
        start_datetime = datetime.combine(today, datetime.min.time())
        end_datetime = datetime.combine(today, datetime.max.time())
        
        if timezone.is_aware(timezone.now()):
            start_datetime = timezone.make_aware(start_datetime)
            end_datetime = timezone.make_aware(end_datetime)
        
        invoices = invoices.filter(
            created_date__isnull=False,
            created_date__gte=start_datetime,
            created_date__lte=end_datetime
        )
        logger.info(f"Default date filter applied: today ({today})")
    
    # Sponsor filter - using patient__plan__plan
    sponsor = context.get('sponsor')
    if sponsor and sponsor != 'All':
        invoices = invoices.filter(patient__plan__plan=sponsor)
        logger.info(f"Sponsor filter applied: {sponsor}")
    
    # Patient Type filter - using patient__category__category
    patient_type = context.get('patient_type')
    if patient_type and patient_type != 'All':
        invoices = invoices.filter(patient__category__category=patient_type)
        logger.info(f"Patient Type filter applied: {patient_type}")
    
    # Payment Type filter
    payment_type = context.get('payment_type')
    if payment_type and payment_type != 'All':
        invoices = invoices.filter(payment_option=payment_type)
        logger.info(f"Payment Type filter applied: {payment_type}")
    
    # Billing Officer filter
    billing_officer = context.get('billing_officer')
    if billing_officer and billing_officer != 'All' and billing_officer != '':
        try:
            invoices = invoices.filter(staff__id=int(billing_officer))
            logger.info(f"Billing Officer filter applied: {billing_officer}")
        except ValueError:
            pass
    
    return invoices


def group_invoices_by_patient(invoices):
    """Group invoices by patient and invoice number"""
    
    grouped = defaultdict(lambda: {
        'patient': None,
        'invoices': [],
        'total_revenue': 0,
        'total_collections': 0,
        'total_refunds': 0,
        'balance': 0,
        'billing_officer': None,
        'invoice_numbers': set(),
    })
    
    # Get all unique invoice numbers from the queryset
    invoice_numbers = list(invoices.values_list('invoice_number', flat=True).distinct())
    
    if not invoice_numbers:
        return grouped
    
    # Bulk fetch collections for all invoice numbers at once
    collections_data = Receipt.objects.filter(
        invoice_number__in=invoice_numbers
    ).values('invoice_number').annotate(
        total=Sum('total_price')
    )
    
    collections_map = {
        item['invoice_number']: item['total'] or 0 
        for item in collections_data
    }
    
    # Bulk fetch refunds for all invoice numbers at once
    refunds_data = Refund.objects.filter(
        invoice_id__in=invoice_numbers
    ).values('invoice_id').annotate(
        total=Sum('amount')
    )
    
    refunds_map = {
        item['invoice_id']: item['total'] or 0 
        for item in refunds_data
    }
    
    # Group invoices
    for invoice in invoices:
        if not invoice.patient:
            continue
            
        key = f"{invoice.patient_id}_{invoice.invoice_number}"
        
        if not grouped[key]['patient']:
            grouped[key]['patient'] = invoice.patient
            grouped[key]['billing_officer'] = invoice.staff
        
        grouped[key]['invoices'].append(invoice)
        grouped[key]['total_revenue'] += invoice.price
        grouped[key]['invoice_numbers'].add(invoice.invoice_number)
    
    # Calculate collections and refunds per group (once per invoice number)
    for key, data in grouped.items():
        total_collections = 0
        total_refunds = 0
        
        for inv_num in data['invoice_numbers']:
            total_collections += collections_map.get(inv_num, 0)
            total_refunds += refunds_map.get(inv_num, 0)
        
        data['total_collections'] = total_collections
        data['total_refunds'] = total_refunds
        data['balance'] = data['total_revenue'] - total_collections
    
    return grouped


def prepare_export_data(grouped_data):
    """Prepare data for export with all required fields"""
    
    export_rows = []
    serial_no = 1
    
    for key, data in grouped_data.items():
        patient = data['patient']
        invoices = data['invoices']
        
        if not patient:
            continue
        
        # Get patient title
        title = get_patient_title(patient)
        
        # Initialize service columns
        investigations = []
        services_procedures = []
        registrations = []
        consultations = []
        admissions = []
        medications = []
        
        # Track invoice and receipt info
        invoice_ids = []
        receipt_ids = []
        transaction_dates = []
        
        # Track payment types (collect unique payment options)
        payment_types = []
        
        # Collect all products by type
        for invoice in invoices:
            product = invoice.product or ''
            source_model = invoice.original_source_model or ''
            
            if source_model == 'RadiologyLab':
                if product and product not in investigations:
                    investigations.append(product)
            elif source_model in ['OtherService', 'AntenatalFee']:
                if product and product not in services_procedures:
                    services_procedures.append(product)
            elif source_model == 'RegistrationFee':
                if product and product not in registrations:
                    registrations.append(product)
            elif source_model == 'NurseWaitingList':
                if product and product not in consultations:
                    consultations.append(product)
            elif source_model == 'AdmissionFee':
                if product and product not in admissions:
                    admissions.append(product)
            elif source_model in ['IPDAdministeredDrugs', 'IPD2AdministeredDrugs', 
                                  'IPD3AdministeredDrugs', 'OPDAdministeredDrugs', 
                                  'OPD2AdministeredDrugs']:
                if product and product not in medications:
                    medications.append(product)
            
            # Collect invoice info
            if invoice.invoice_number and invoice.invoice_number not in invoice_ids:
                invoice_ids.append(invoice.invoice_number)
            
            # Collect payment type
            if invoice.payment_option and invoice.payment_option not in payment_types:
                payment_types.append(invoice.payment_option)
            
            # Get receipt info for this invoice
            receipts = Receipt.objects.filter(invoice_number__iexact=invoice.invoice_number)
            for receipt in receipts:
                if receipt.receipt_number and receipt.receipt_number not in receipt_ids:
                    receipt_ids.append(receipt.receipt_number)
            
            # Get transaction date
            if invoice.created_date:
                date_str = invoice.created_date.strftime('%d-%m-%Y %H:%M')
                if date_str not in transaction_dates:
                    transaction_dates.append(date_str)
        
        # Join products with semicolon
        investigations_str = '; '.join(investigations)
        services_str = '; '.join(services_procedures)
        registrations_str = '; '.join(registrations)
        consultations_str = '; '.join(consultations)
        admissions_str = '; '.join(admissions)
        medications_str = '; '.join(medications)
        
        # Join invoice/receipt info with semicolon
        invoice_ids_str = '; '.join(invoice_ids)
        receipt_ids_str = '; '.join(receipt_ids)
        transaction_dates_str = '; '.join(transaction_dates)
        payment_types_str = '; '.join(payment_types)
        
        # Get billing officer name
        billing_officer = data['billing_officer']
        billing_officer_name = f"{billing_officer.fullname}".strip() if billing_officer and hasattr(billing_officer, 'fullname') else ''
        
        # Build row
        row = {
            'sn': serial_no,
            'hospital_number': patient.hospital_number or '',
            'title': title,
            'surname': patient.surname or '',
            'first_name': patient.first_name or '',
            'middle_name': patient.other_name or '',
            'full_name': patient.get_full_name() or '',
            'upi': getattr(patient, 'insurance_policy_number', '') or '',
            'phone': patient.phone_number or '',
            'email': patient.email_address or '',
            'address': patient.address or '',
            'sponsor': getattr(patient.plan, 'plan', '') if patient.plan else '',
            'patient_type': getattr(patient.category, 'category', '') if patient.category else '',
            'gender': patient.gender or '',
            'dob': patient.dob.strftime('%d-%m-%Y') if patient.dob else '',
            'marital_status': patient.patient_type or '',
            'investigations': investigations_str,
            'services_procedures': services_str,
            'registration': registrations_str,
            'consultation': consultations_str,
            'admission': admissions_str,
            'medications': medications_str,
            'invoice_id': invoice_ids_str,
            'receipt_id': receipt_ids_str,
            'transaction_date': transaction_dates_str,
            'payment_type': payment_types_str,  
            'revenue': data['total_revenue'],
            'collections': data['total_collections'],
            'refunds': data['total_refunds'],
            'balance': data['balance'],
            'billing_officer': billing_officer_name,
        }
        
        export_rows.append(row)
        serial_no += 1
    
    return export_rows

def get_patient_title(patient):
    """Get appropriate title based on gender and marital status"""
    if not patient:
        return ''
    if patient.gender and patient.gender.lower() == 'male':
        return 'Mr.'
    elif patient.gender and patient.gender.lower() == 'female':
        if patient.patient_type and patient.patient_type.lower() == 'married':
            return 'Mrs.'
        else:
            return 'Miss.'
    return ''


def export_to_excel(export_data, context):
    """Export data to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Transaction Book"
    
    # Defining headers and their column widths
    headers = [
        ('S/N', 8),
        ('Hospital Number', 18),
        ('Title', 10),
        ('Surname', 20),
        ('First Name', 20),
        ('Middle Name', 20),
        ('Full Name', 30),
        ('UPI', 15),
        ('Phone', 15),
        ('Email', 25),
        ('Address', 35),
        ('Sponsor', 15),
        ('Patient Type', 15),
        ('Gender', 10),
        ('Date of Birth', 15),
        ('Marital Status', 15),
        ('Investigations', 40),
        ('Services/Procedures', 40),
        ('Registration', 40),
        ('Consultation', 40),
        ('Admission', 40),
        ('Item/Medications', 40),
        ('Invoice ID', 20),
        ('Receipt ID', 20),
        ('Transaction Date', 20),
        ('Payment Type', 20),  
        ('Revenue (₦)', 15),
        ('Collections (₦)', 15),
        ('Refunds (₦)', 15),
        ('Balance (₦)', 15),
        ('Billing Officer', 20),
    ]
    
    # Applying headers
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="366092", end_color="366092", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Applying data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_data['sn'],
            row_data['hospital_number'],
            row_data['title'],
            row_data['surname'],
            row_data['first_name'],
            row_data['middle_name'],
            row_data['full_name'],
            row_data['upi'],
            row_data['phone'],
            row_data['email'],
            row_data['address'],
            row_data['sponsor'],
            row_data['patient_type'],
            row_data['gender'],
            row_data['dob'],
            row_data['marital_status'],
            row_data['investigations'],
            row_data['services_procedures'],
            row_data['registration'],
            row_data['consultation'],
            row_data['admission'],
            row_data['medications'],
            row_data['invoice_id'],
            row_data['receipt_id'],
            row_data['transaction_date'],
            row_data['payment_type'],  # NEW: Add payment type data
            row_data['revenue'],
            row_data['collections'],
            row_data['refunds'],
            row_data['balance'],
            row_data['billing_officer'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (columns 27, 28, 29, 30 after adding payment type)
            if col in [27, 28, 29, 30]:  # Revenue, Collections, Refunds, Balance columns
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Adding borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Generate filename
    start_date = context.get('start_date', '')
    end_date = context.get('end_date', '')
    filename = f"ISALU_HOSPITALS_transaction_book_details_{start_date}_to_{end_date}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_to_pdf(export_data, context):
    """Export data to PDF (placeholder for now)"""
    return HttpResponse("PDF export coming soon...")


# Exception models configuration
EXCEPTION_MODELS = [
    {'model': 'IPDAdministeredDrugs', 'app': 'IPD_Pharm', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'IPD2AdministeredDrugs', 'app': 'IPD_Pharm2', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'IPD3AdministeredDrugs', 'app': 'IPD_Pharm3', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'OPDAdministeredDrugs', 'app': 'OPD_Pharm', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'OPD2AdministeredDrugs', 'app': 'OPD_Pharm2', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'RadiologyLab', 'app': 'radio_lab', 'staff_field': 'staff', 'transaction_type': 'Investigations', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'NurseWaitingList', 'app': 'queue_operations', 'staff_field': 'attendant', 'transaction_type': 'Consultation', 'description_field': 'purpose', 'amount_field': 'price'},
    {'model': 'OtherService', 'app': 'queue_operations', 'staff_field': 'provider', 'transaction_type': 'Services/Procedures', 'description_field': 'purpose', 'amount_field': 'price'},
]


@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def exception_bills_report(request):
    """Generate Exception Bills Report (completed == 3)"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    sponsor = request.GET.get('sponsor', 'All')
    patient_type = request.GET.get('patient_type', 'All')
    transaction_type = request.GET.get('transaction_type', 'All')
    patient_search = request.GET.get('patient_search', '')
    patient_id = request.GET.get('patient_id', '')  # Get patient ID
    staff_name = request.GET.get('staff_name', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # If no date range, default to today
    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    
    # Get filter options for dropdowns
    sponsors = PatientPlan.objects.filter(
        plan__isnull=False
    ).exclude(plan='').values_list('plan', flat=True).distinct().order_by('plan')
    sponsors = [s for s in sponsors if s]
    
    patient_types = PatientCategory.objects.filter(
        category__isnull=False
    ).exclude(category='').values_list('category', flat=True).distinct().order_by('category')
    patient_types = [pt for pt in patient_types if pt]
    
    # Get unique transaction types from the config
    transaction_types = sorted(set([item['transaction_type'] for item in EXCEPTION_MODELS]))
    
    # Get unique staff names from all exception models
    staff_names = get_unique_staff_names()
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'sponsor': sponsor,
        'patient_type': patient_type,
        'transaction_type': transaction_type,
        'patient_search': patient_search,
        'patient_id': patient_id,  
        'staff_name': staff_name,
        'sponsors': sponsors,
        'patient_types': patient_types,
        'transaction_types': transaction_types,
        'staff_names': staff_names,
        'orientation': orientation,
        'destination': destination,
        'exception_models': EXCEPTION_MODELS,  
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_exception_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/exception_bills.html', context)


def get_unique_staff_names():
    """Get unique staff names from all exception models"""
    staff_names = set()
    
    for config in EXCEPTION_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            staff_field = config['staff_field']
            
            # Get distinct staff IDs from the model
            staff_ids = model.objects.filter(
                completed=3
            ).values_list(f'{staff_field}__id', flat=True).distinct()
            
            # Get user fullnames
            users = User.objects.filter(id__in=staff_ids)
            for user in users:
                if user.fullname:
                    staff_names.add(user.fullname)
                    
        except Exception as e:
            logger.error(f"Error getting staff names from {config['app']}.{config['model']}: {e}")
            continue
    
    return sorted(list(staff_names))


def generate_exception_export(request, context):
    """Generate Excel or PDF export for Exception Bills"""
    
    # Build the queryset with filters
    exception_data = get_exception_data(context)
    
    if not exception_data:
        return HttpResponse("No exception bills found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_exception_to_excel(exception_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_exception_to_pdf(exception_data, context)


def get_exception_data(context):
    """Fetch data from all exception models with filters applied"""
    
    all_records = []
    start_date = context.get('start_date')
    end_date = context.get('end_date')
    sponsor = context.get('sponsor')
    patient_type = context.get('patient_type')
    transaction_type_filter = context.get('transaction_type')
    patient_search = context.get('patient_search', '')
    patient_id = context.get('patient_id', '')  # Get patient ID
    staff_name = context.get('staff_name')
    
    # Parse date range
    start_datetime = None
    end_datetime = None
    
    if start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            start_datetime = datetime.combine(start_date_obj, datetime.min.time())
            end_datetime = datetime.combine(end_date_obj, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                start_datetime = timezone.make_aware(start_datetime)
                end_datetime = timezone.make_aware(end_datetime)
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    
    # Iterate through each exception model
    for config in EXCEPTION_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            staff_field = config['staff_field']
            transaction_type = config['transaction_type']
            description_field = config['description_field']
            amount_field = config['amount_field']
            
            # Build base queryset 
            queryset = model.objects.filter(completed=3)
            
            # Apply date filter
            if start_datetime and end_datetime:
                queryset = queryset.filter(
                    created_date__isnull=False,
                    created_date__gte=start_datetime,
                    created_date__lte=end_datetime
                )
            
            # Apply transaction type filter
            if transaction_type_filter and transaction_type_filter != 'All':
                if transaction_type_filter != transaction_type:
                    continue  # Skip this model if transaction type doesn't match
            
            # Apply patient filter : Checking patient_id first, then patient_search
            if patient_id:
                # Filter by exact patient ID
                queryset = queryset.filter(patient__id=patient_id)
                logger.info(f"Filtering by patient ID: {patient_id}")
            elif patient_search:
                # Search by name or hospital number
                queryset = queryset.filter(
                    Q(patient__hospital_number__icontains=patient_search) |
                    Q(patient__first_name__icontains=patient_search) |
                    Q(patient__surname__icontains=patient_search)
                )
                logger.info(f"Filtering by patient search: {patient_search}")
            
            # Apply sponsor filter
            if sponsor and sponsor != 'All':
                queryset = queryset.filter(patient__plan__plan=sponsor)
            
            # Apply patient type filter
            if patient_type and patient_type != 'All':
                queryset = queryset.filter(patient__category__category=patient_type)
            
            # Apply staff filter
            if staff_name and staff_name != 'All':
                queryset = queryset.filter(**{f'{staff_field}__fullname': staff_name})
            
            # Select related fields for optimization
            queryset = queryset.select_related('patient', 'patient__plan', 'patient__category', staff_field)
            
            # Process each record
            for record in queryset:
                patient = record.patient
                if not patient:
                    continue
                
                # Get staff name
                staff = getattr(record, staff_field, None)
                staff_name_value = staff.fullname if staff else ''
                
                # Get amount
                amount = getattr(record, amount_field, 0) or 0
                
                # Get description
                description = getattr(record, description_field, '') or ''
                
                # Build row data
                row = {
                    'patient': patient,
                    'transaction_date': record.created_date,
                    'transaction_description': description,
                    'transaction_type': transaction_type,
                    'amount': amount,
                    'created_date_time': record.created_date,
                    'staff_name': staff_name_value,
                    'source_model': config['model'],
                    'source_app': config['app'],
                }
                
                all_records.append(row)
                
        except Exception as e:
            logger.error(f"Error processing {config['app']}.{config['model']}: {e}")
            continue
    
    # Sort by created date (newest first)
    all_records.sort(key=lambda x: x['created_date_time'], reverse=True)
    
    logger.info(f"Total records found: {len(all_records)}")
    return all_records


def export_exception_to_excel(export_data, context):
    """Export Exception Bills to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Exception Bills"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Hospital Number', 18),
        ('Title', 10),
        ('Surname', 20),
        ('First Name', 20),
        ('Middle Name', 20),
        ('Full Name', 30),
        ('UPI', 15),
        ('Phone', 15),
        ('Email', 25),
        ('Address', 35),
        ('Sponsor', 15),
        ('Patient Type', 15),
        ('Gender', 10),
        ('Date of Birth', 15),
        ('Marital Status', 15),
        ('Transaction Date', 18),
        ('Transaction Description', 40),
        ('Transaction Type', 20),
        ('Amount (₦)', 15),
        ('Created Date & Time', 20),
        ('Staff Name', 20),
    ]
    
    # Apply headers
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="8B0000", end_color="8B0000", fill_type="solid")  # Dark red for exception
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        patient = row_data['patient']
        
        # Get patient title
        title = get_patient_title(patient)
        
        row = [
            row_idx - 1,  # S/N
            patient.hospital_number or '',
            title,
            patient.surname or '',
            patient.first_name or '',
            patient.other_name or '',
            patient.get_full_name() or '',
            getattr(patient, 'insurance_policy_number', '') or '',
            patient.phone_number or '',
            patient.email_address or '',
            patient.address or '',
            getattr(patient.plan, 'plan', '') if patient.plan else '',
            getattr(patient.category, 'category', '') if patient.category else '',
            patient.gender or '',
            patient.dob.strftime('%d-%m-%Y') if patient.dob else '',
            patient.patient_type or '',
            row_data['transaction_date'].strftime('%d-%m-%Y') if row_data['transaction_date'] else '',
            row_data['transaction_description'],
            row_data['transaction_type'],
            row_data['amount'],
            row_data['created_date_time'].strftime('%d-%m-%Y %H:%M') if row_data['created_date_time'] else '',
            row_data['staff_name'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Amount column - 20)
            if col == 20:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Highlight exception rows in red (makes exceptions stand out)
    for row_idx in range(2, len(export_data) + 2):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color="FFF0F0", end_color="FFF0F0", fill_type="solid")
    
    # Generate filename
    start_date = context.get('start_date', '')
    end_date = context.get('end_date', '')
    filename = f"ISALU_HOSPITALS_exception_bill_transaction_listing_{start_date}_to_{end_date}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def get_patient_title(patient):
    """Get appropriate title based on gender and marital status"""
    if not patient:
        return ''
    if patient.gender and patient.gender.lower() == 'male':
        return 'Mr.'
    elif patient.gender and patient.gender.lower() == 'female':
        if patient.patient_type and patient.patient_type.lower() == 'married':
            return 'Mrs.'
        else:
            return 'Miss.'
    return ''


def export_exception_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def patient_search_api_report(request):
    """API endpoint for patient search with autocomplete"""
    query = request.GET.get('q', '').strip()
    
    # Return empty results if query is too short
    if len(query) < 2:
        return JsonResponse({'results': []})
    
    results = []
    
    # Try Haystack search first
    try:
        from haystack.query import SearchQuerySet
        search_results = SearchQuerySet().models(PatientProfile).filter(content=query)[:10]
        
        for result in search_results:
            try:
                patient = result.object
                results.append({
                    'id': patient.id,
                    'full_name': patient.get_full_name() or '',
                    'hospital_number': getattr(patient, 'hospital_number', '') or '',
                    'surname': patient.surname or '',
                    'first_name': patient.first_name or '',
                })
            except Exception as e:
                logger.error(f"Error processing Haystack result: {e}")
                continue
                
    except Exception as e:
        logger.error(f"Haystack search error: {e}")
        # Fallback to direct database search if Haystack fails
        try:
            direct_results = PatientProfile.objects.filter(
                Q(hospital_number__icontains=query) |
                Q(first_name__icontains=query) |
                Q(surname__icontains=query) |
                Q(surname__icontains=query) | 
                Q(first_name__icontains=query)
            )[:10]
            
            for patient in direct_results:
                results.append({
                    'id': patient.id,
                    'full_name': patient.get_full_name() or '',
                    'hospital_number': getattr(patient, 'hospital_number', '') or '',
                    'surname': patient.surname or '',
                    'first_name': patient.first_name or '',
                })
        except Exception as db_error:
            logger.error(f"Database fallback search error: {db_error}")
            return JsonResponse({'results': [], 'error': 'Search error'}, status=500)
    
    # If still no results, try a more flexible search
    if not results:
        try:
            # Try with more flexible matching
            flexible_results = PatientProfile.objects.filter(
                Q(hospital_number__icontains=query) |
                Q(first_name__icontains=query) |
                Q(surname__icontains=query)
            )[:10]
            
            for patient in flexible_results:
                # Check if already in results
                if not any(r['id'] == patient.id for r in results):
                    results.append({
                        'id': patient.id,
                        'full_name': patient.get_full_name() or '',
                        'hospital_number': getattr(patient, 'hospital_number', '') or '',
                        'surname': patient.surname or '',
                        'first_name': patient.first_name or '',
                    })
        except Exception as e:
            logger.error(f"Flexible search error: {e}")
    
    return JsonResponse({'results': results})



# Cancelled models configuration 
CANCELLED_MODELS = [
    {'model': 'IPDAdministeredDrugs', 'app': 'IPD_Pharm', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'IPD2AdministeredDrugs', 'app': 'IPD_Pharm2', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'IPD3AdministeredDrugs', 'app': 'IPD_Pharm3', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'OPDAdministeredDrugs', 'app': 'OPD_Pharm', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'OPD2AdministeredDrugs', 'app': 'OPD_Pharm2', 'staff_field': 'staff', 'transaction_type': 'Item/Medication', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'RadiologyLab', 'app': 'radio_lab', 'staff_field': 'staff', 'transaction_type': 'Investigations', 'description_field': 'item', 'amount_field': 'rate'},
    {'model': 'NurseWaitingList', 'app': 'queue_operations', 'staff_field': 'attendant', 'transaction_type': 'Consultation', 'description_field': 'purpose', 'amount_field': 'price'},
    {'model': 'OtherService', 'app': 'queue_operations', 'staff_field': 'provider', 'transaction_type': 'Services/Procedures', 'description_field': 'purpose', 'amount_field': 'price'},
    {'model': 'AdmissionFee', 'app': 'IPD', 'staff_field': 'staff', 'transaction_type': 'Admission', 'description_field': 'ward', 'amount_field': 'price'},
]



# CANCELLED TRANSACTIONS REPORT 

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def cancelled_transactions_report(request):
    """Generate Cancelled Transactions Report """
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    sponsor = request.GET.get('sponsor', 'All')
    patient_type = request.GET.get('patient_type', 'All')
    transaction_type = request.GET.get('transaction_type', 'All')
    patient_search = request.GET.get('patient_search', '')
    patient_id = request.GET.get('patient_id', '')
    staff_name = request.GET.get('staff_name', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # If no date range, default to today
    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    
    # Get filter options for dropdowns
    sponsors = PatientPlan.objects.filter(
        plan__isnull=False
    ).exclude(plan='').values_list('plan', flat=True).distinct().order_by('plan')
    sponsors = [s for s in sponsors if s]
    
    patient_types = PatientCategory.objects.filter(
        category__isnull=False
    ).exclude(category='').values_list('category', flat=True).distinct().order_by('category')
    patient_types = [pt for pt in patient_types if pt]
    
    # Get unique transaction types from the config
    transaction_types = sorted(set([item['transaction_type'] for item in CANCELLED_MODELS]))
    
    # Get unique staff names from all cancelled models
    staff_names = get_unique_staff_names_for_cancelled()
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'sponsor': sponsor,
        'patient_type': patient_type,
        'transaction_type': transaction_type,
        'patient_search': patient_search,
        'patient_id': patient_id,
        'staff_name': staff_name,
        'sponsors': sponsors,
        'patient_types': patient_types,
        'transaction_types': transaction_types,
        'staff_names': staff_names,
        'orientation': orientation,
        'destination': destination,
        'cancelled_models': CANCELLED_MODELS,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_cancelled_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/cancelled_transactions.html', context)


def get_unique_staff_names_for_cancelled():
    """Get unique staff names from all cancelled models"""
    staff_names = set()
    
    for config in CANCELLED_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            staff_field = config['staff_field']
            
            # Get distinct staff IDs from the model where completed == 2
            staff_ids = model.objects.filter(
                completed=2
            ).values_list(f'{staff_field}__id', flat=True).distinct()
            
            # Get user fullnames
            users = User.objects.filter(id__in=staff_ids)
            for user in users:
                if user.fullname:
                    staff_names.add(user.fullname)
                    
        except Exception as e:
            logger.error(f"Error getting staff names from {config['app']}.{config['model']}: {e}")
            continue
    
    return sorted(list(staff_names))


def generate_cancelled_export(request, context):
    """Generate Excel or PDF export for Cancelled Transactions"""
    
    # Build the queryset with filters
    cancelled_data = get_cancelled_data(context)
    
    if not cancelled_data:
        return HttpResponse("No cancelled transactions found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_cancelled_to_excel(cancelled_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_cancelled_to_pdf(cancelled_data, context)


def get_cancelled_data(context):
    """Fetch data from all cancelled models with filters applied (completed == 2)"""
    
    all_records = []
    start_date = context.get('start_date')
    end_date = context.get('end_date')
    sponsor = context.get('sponsor')
    patient_type = context.get('patient_type')
    transaction_type_filter = context.get('transaction_type')
    patient_search = context.get('patient_search', '')
    patient_id = context.get('patient_id', '')
    staff_name = context.get('staff_name')
    
    # Parse date range
    start_datetime = None
    end_datetime = None
    
    if start_date and end_date:
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d').date()
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
            
            start_datetime = datetime.combine(start_date_obj, datetime.min.time())
            end_datetime = datetime.combine(end_date_obj, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                start_datetime = timezone.make_aware(start_datetime)
                end_datetime = timezone.make_aware(end_datetime)
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    
    # Iterate through each cancelled model
    for config in CANCELLED_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            staff_field = config['staff_field']
            transaction_type = config['transaction_type']
            description_field = config['description_field']
            amount_field = config['amount_field']
            
            # Build base queryset - only completed == 2 (CANCELLED)
            queryset = model.objects.filter(completed=2)
            
            # Apply date filter
            if start_datetime and end_datetime:
                queryset = queryset.filter(
                    created_date__isnull=False,
                    created_date__gte=start_datetime,
                    created_date__lte=end_datetime
                )
            
            # Apply transaction type filter
            if transaction_type_filter and transaction_type_filter != 'All':
                if transaction_type_filter != transaction_type:
                    continue  # Skip this model if transaction type doesn't match
            
            # Apply patient filter
            if patient_id:
                queryset = queryset.filter(patient__id=patient_id)
            elif patient_search:
                queryset = queryset.filter(
                    Q(patient__hospital_number__icontains=patient_search) |
                    Q(patient__first_name__icontains=patient_search) |
                    Q(patient__surname__icontains=patient_search)
                )
            
            # Apply sponsor filter
            if sponsor and sponsor != 'All':
                queryset = queryset.filter(patient__plan__plan=sponsor)
            
            # Apply patient type filter
            if patient_type and patient_type != 'All':
                queryset = queryset.filter(patient__category__category=patient_type)
            
            # Apply staff filter
            if staff_name and staff_name != 'All':
                queryset = queryset.filter(**{f'{staff_field}__fullname': staff_name})
            
            # Select related fields for optimization
            queryset = queryset.select_related('patient', 'patient__plan', 'patient__category', staff_field)
            
            # For AdmissionFee, also select the ward
            if config['model'] == 'AdmissionFee':
                queryset = queryset.select_related('ward')
            
            # Process each record
            for record in queryset:
                patient = record.patient
                if not patient:
                    continue
                
                # Get staff name
                staff = getattr(record, staff_field, None)
                staff_name_value = staff.fullname if staff else ''
                
                # Get amount
                amount = getattr(record, amount_field, 0) or 0
                
                # Get description - handle ward foreign key for AdmissionFee
                if config['model'] == 'AdmissionFee':
                    ward = getattr(record, description_field, None)
                    description = ward.ward_name if ward else ''
                else:
                    description = getattr(record, description_field, '') or ''
                
                # Build row data
                row = {
                    'patient': patient,
                    'transaction_date': record.created_date,
                    'transaction_description': description,
                    'transaction_type': transaction_type,
                    'amount': amount,
                    'created_date_time': record.created_date,
                    'staff_name': staff_name_value,
                    'source_model': config['model'],
                    'source_app': config['app'],
                }
                
                all_records.append(row)
                
        except Exception as e:
            logger.error(f"Error processing {config['app']}.{config['model']}: {e}")
            continue
    
    # Sort by created date (newest first)
    all_records.sort(key=lambda x: x['created_date_time'], reverse=True)
    
    logger.info(f"Total cancelled records found: {len(all_records)}")
    return all_records


def export_cancelled_to_excel(export_data, context):
    """Export Cancelled Transactions to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Cancelled Transactions"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Hospital Number', 18),
        ('Title', 10),
        ('Surname', 20),
        ('First Name', 20),
        ('Middle Name', 20),
        ('Full Name', 30),
        ('UPI', 15),
        ('Phone', 15),
        ('Email', 25),
        ('Address', 35),
        ('Sponsor', 15),
        ('Patient Type', 15),
        ('Gender', 10),
        ('Date of Birth', 15),
        ('Marital Status', 15),
        ('Transaction Date', 18),
        ('Transaction Description', 40),
        ('Transaction Type', 20),
        ('Amount (₦)', 15),
        ('Created Date & Time', 20),
        ('Staff Name', 20),
    ]
    
    # Apply headers - using orange color for cancelled
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="FF8C00", end_color="FF8C00", fill_type="solid")  # Orange for cancelled
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        patient = row_data['patient']
        
        # Get patient title
        title = get_patient_title(patient)
        
        row = [
            row_idx - 1,  # S/N
            patient.hospital_number or '',
            title,
            patient.surname or '',
            patient.first_name or '',
            patient.other_name or '',
            patient.get_full_name() or '',
            getattr(patient, 'insurance_policy_number', '') or '',
            patient.phone_number or '',
            patient.email_address or '',
            patient.address or '',
            getattr(patient.plan, 'plan', '') if patient.plan else '',
            getattr(patient.category, 'category', '') if patient.category else '',
            patient.gender or '',
            patient.dob.strftime('%d-%m-%Y') if patient.dob else '',
            patient.patient_type or '',
            row_data['transaction_date'].strftime('%d-%m-%Y') if row_data['transaction_date'] else '',
            row_data['transaction_description'],
            row_data['transaction_type'],
            row_data['amount'],
            row_data['created_date_time'].strftime('%d-%m-%Y %H:%M') if row_data['created_date_time'] else '',
            row_data['staff_name'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Amount column - 20)
            if col == 20:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Highlight cancelled rows in light orange
    for row_idx in range(2, len(export_data) + 2):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color="FFF0D9", end_color="FFF0D9", fill_type="solid")
    
    # Generate filename
    start_date = context.get('start_date', '')
    end_date = context.get('end_date', '')
    filename = f"ISALU_HOSPITALS_cancelled_transactions_{start_date}_to_{end_date}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_cancelled_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


# helper function
def get_patient_title(patient):
    """Get appropriate title based on gender and marital status"""
    if not patient:
        return ''
    if patient.gender and patient.gender.lower() == 'male':
        return 'Mr.'
    elif patient.gender and patient.gender.lower() == 'female':
        if patient.patient_type and patient.patient_type.lower() == 'married':
            return 'Mrs.'
        else:
            return 'Miss.'
    return ''


@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def admission_records_report(request):
    """Generate Admission Records Report"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    start_date = request.GET.get('start_date')
    end_date = request.GET.get('end_date')
    admitted_by = request.GET.get('admitted_by', 'All')
    admission_date_from = request.GET.get('admission_date_from')
    admission_date_to = request.GET.get('admission_date_to')
    bed_allocated_by = request.GET.get('bed_allocated_by', 'All')
    discharged_by = request.GET.get('discharged_by', 'All')
    discharge_date_from = request.GET.get('discharge_date_from')
    discharge_date_to = request.GET.get('discharge_date_to')
    bill_cleared_by = request.GET.get('bill_cleared_by', 'All')
    cleared_date_from = request.GET.get('cleared_date_from')
    cleared_date_to = request.GET.get('cleared_date_to')
    ward_name = request.GET.get('ward_name', 'All')
    sponsor = request.GET.get('sponsor', 'All')
    patient_type = request.GET.get('patient_type', 'All')
    patient_search = request.GET.get('patient_search', '')
    patient_id = request.GET.get('patient_id', '')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # If no date range, default to today
    if not start_date or not end_date:
        today = timezone.now().date()
        start_date = today.strftime('%Y-%m-%d')
        end_date = today.strftime('%Y-%m-%d')
    
    # Get filter options for dropdowns
    sponsors = PatientPlan.objects.filter(
        plan__isnull=False
    ).exclude(plan='').values_list('plan', flat=True).distinct().order_by('plan')
    sponsors = [s for s in sponsors if s]
    
    patient_types = PatientCategory.objects.filter(
        category__isnull=False
    ).exclude(category='').values_list('category', flat=True).distinct().order_by('category')
    patient_types = [pt for pt in patient_types if pt]
    
    # Get unique doctors, nurses, and bill officers from AdmissionTable
    admitted_by_list = User.objects.filter(
        id__in=AdmissionTable.objects.filter(
            doctor_admitted__isnull=False
        ).values_list('doctor_admitted__id', flat=True).distinct()
    ).values_list('id', 'fullname').distinct().order_by('fullname')
    admitted_by_list = [{'id': uid, 'fullname': fullname} for uid, fullname in admitted_by_list if fullname]
    
    # Get unique nurses who allocated beds
    bed_allocated_by_list = AdmissionTable.objects.filter(
        nurse_admitted__isnull=False
    ).exclude(nurse_admitted='').values_list('nurse_admitted', flat=True).distinct().order_by('nurse_admitted')
    bed_allocated_by_list = [{'id': name, 'fullname': name} for name in bed_allocated_by_list if name]
    
    # Get unique doctors who discharged
    discharged_by_list = AdmissionTable.objects.filter(
        doctor_discharged__isnull=False
    ).exclude(doctor_discharged='').values_list('doctor_discharged', flat=True).distinct().order_by('doctor_discharged')
    discharged_by_list = [{'id': name, 'fullname': name} for name in discharged_by_list if name]
    
    # Get unique bill officers who cleared bills
    bill_cleared_by_list = AdmissionTable.objects.filter(
        bill_discharged__isnull=False
    ).exclude(bill_discharged='').values_list('bill_discharged', flat=True).distinct().order_by('bill_discharged')
    bill_cleared_by_list = [{'id': name, 'fullname': name} for name in bill_cleared_by_list if name]
    
    # Get unique wards
    wards = Ward.objects.all().values_list('ward_name', flat=True).distinct().order_by('ward_name')
    wards = [w for w in wards if w]
    
    context = {
        'start_date': start_date,
        'end_date': end_date,
        'admitted_by': admitted_by,
        'admission_date_from': admission_date_from,
        'admission_date_to': admission_date_to,
        'bed_allocated_by': bed_allocated_by,
        'discharged_by': discharged_by,
        'discharge_date_from': discharge_date_from,
        'discharge_date_to': discharge_date_to,
        'bill_cleared_by': bill_cleared_by,
        'cleared_date_from': cleared_date_from,
        'cleared_date_to': cleared_date_to,
        'ward_name': ward_name,
        'sponsor': sponsor,
        'patient_type': patient_type,
        'patient_search': patient_search,
        'patient_id': patient_id,
        'sponsors': sponsors,
        'patient_types': patient_types,
        'admitted_by_list': admitted_by_list,
        'bed_allocated_by_list': bed_allocated_by_list,
        'discharged_by_list': discharged_by_list,
        'bill_cleared_by_list': bill_cleared_by_list,
        'wards': wards,
        'orientation': orientation,
        'destination': destination,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_admission_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/admission_records.html', context)


def generate_admission_export(request, context):
    """Generate Excel or PDF export for Admission Records"""
    
    # Build the queryset with filters
    admission_data = get_admission_data(context)
    
    if not admission_data:
        return HttpResponse("No admission records found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_admission_to_excel(admission_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_admission_to_pdf(admission_data, context)


def get_admission_data(context):
    """Fetch admission records with filters applied"""
    
    all_records = []
    
    # Start with all admission records
    queryset = AdmissionTable.objects.select_related(
        'patient', 'patient__plan', 'patient__category', 'doctor_admitted'
    ).prefetch_related('bedallocation_set', 'bedallocation_set__ward', 'bedallocation_set__bed')
    
    # Apply date filter (admission date)
    admission_date_from = context.get('admission_date_from')
    admission_date_to = context.get('admission_date_to')
    
    if admission_date_from and admission_date_to:
        try:
            from_date = datetime.strptime(admission_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(admission_date_to, '%Y-%m-%d').date()
            to_date = to_date + timedelta(days=1)
            
            queryset = queryset.filter(
                doctor_admit_date__isnull=False,
                doctor_admit_date__date__gte=from_date,
                doctor_admit_date__date__lt=to_date
            )
        except ValueError:
            pass
    
    # Apply discharge date filter
    discharge_date_from = context.get('discharge_date_from')
    discharge_date_to = context.get('discharge_date_to')
    
    if discharge_date_from and discharge_date_to:
        try:
            from_date = datetime.strptime(discharge_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(discharge_date_to, '%Y-%m-%d').date()
            to_date = to_date + timedelta(days=1)
            
            queryset = queryset.filter(
                doctor_discharge_date__isnull=False,
                doctor_discharge_date__date__gte=from_date,
                doctor_discharge_date__date__lt=to_date
            )
        except ValueError:
            pass
    
    # Apply cleared date filter
    cleared_date_from = context.get('cleared_date_from')
    cleared_date_to = context.get('cleared_date_to')
    
    if cleared_date_from and cleared_date_to:
        try:
            from_date = datetime.strptime(cleared_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(cleared_date_to, '%Y-%m-%d').date()
            to_date = to_date + timedelta(days=1)
            
            queryset = queryset.filter(
                bill_discharge_date__isnull=False,
                bill_discharge_date__date__gte=from_date,
                bill_discharge_date__date__lt=to_date
            )
        except ValueError:
            pass
    
    # Apply admitted_by filter
    admitted_by = context.get('admitted_by')
    if admitted_by and admitted_by != 'All':
        queryset = queryset.filter(doctor_admitted__id=admitted_by)
    
    # Apply bed_allocated_by filter
    bed_allocated_by = context.get('bed_allocated_by')
    if bed_allocated_by and bed_allocated_by != 'All':
        queryset = queryset.filter(nurse_admitted=bed_allocated_by)
    
    # Apply discharged_by filter
    discharged_by = context.get('discharged_by')
    if discharged_by and discharged_by != 'All':
        queryset = queryset.filter(doctor_discharged=discharged_by)
    
    # Apply bill_cleared_by filter
    bill_cleared_by = context.get('bill_cleared_by')
    if bill_cleared_by and bill_cleared_by != 'All':
        queryset = queryset.filter(bill_discharged=bill_cleared_by)
    
    # Apply ward filter
    ward_name = context.get('ward_name')
    if ward_name and ward_name != 'All':
        queryset = queryset.filter(
            bedallocation__ward__ward_name=ward_name
        ).distinct()
    
    # Apply patient filter
    patient_search = context.get('patient_search', '')
    patient_id = context.get('patient_id', '')
    
    if patient_id:
        queryset = queryset.filter(patient__id=patient_id)
    elif patient_search:
        queryset = queryset.filter(
            Q(patient__hospital_number__icontains=patient_search) |
            Q(patient__first_name__icontains=patient_search) |
            Q(patient__surname__icontains=patient_search)
        )
    
    # Apply sponsor filter
    sponsor = context.get('sponsor')
    if sponsor and sponsor != 'All':
        queryset = queryset.filter(patient__plan__plan=sponsor)
    
    # Apply patient type filter
    patient_type = context.get('patient_type')
    if patient_type and patient_type != 'All':
        queryset = queryset.filter(patient__category__category=patient_type)
    
    # Order by admission date (newest first)
    queryset = queryset.order_by('-doctor_admit_date')
    
    logger.info(f"Found {queryset.count()} admission records")
    
    # Process each record
    for record in queryset:
        patient = record.patient
        if not patient:
            continue
        
        # Get the latest bed allocation for this admission
        bed_allocation = record.bedallocation_set.first()
        ward_name_value = ''
        bed_name_value = ''
        
        if bed_allocation:
            ward_name_value = bed_allocation.ward.ward_name if bed_allocation.ward else ''
            bed_name_value = bed_allocation.bed.bed_name if bed_allocation.bed else ''
        
        # Get doctor names
        doctor_admitted = record.doctor_admitted
        doctor_admitted_name = f"Dr. {doctor_admitted.fullname}" if doctor_admitted else ''
        
        # Get nurse name
        nurse_admitted_name = record.nurse_admitted or ''
        if nurse_admitted_name:
            nurse_admitted_name = f"Nurse {nurse_admitted_name}"
        
        # Get discharge doctor
        doctor_discharged_name = record.doctor_discharged or ''
        if doctor_discharged_name:
            doctor_discharged_name = f"Dr. {doctor_discharged_name}"
        
        # Get bill cleared by
        bill_cleared_name = record.bill_discharged or ''
        
        # Build row data
        row = {
            'patient': patient,
            'doctor_admitted_name': doctor_admitted_name,
            'doctor_admit_date': record.doctor_admit_date,
            'nurse_admitted_name': nurse_admitted_name,
            'nurse_admit_date': record.nurse_admit_date,
            'doctor_discharged_name': doctor_discharged_name,
            'doctor_discharge_date': record.doctor_discharge_date,
            'bill_cleared_name': bill_cleared_name,
            'bill_discharge_date': record.bill_discharge_date,
            'ward_name': ward_name_value,
            'bed_name': bed_name_value,
            'admission_record': record,
        }
        
        all_records.append(row)
    
    return all_records


def export_admission_to_excel(export_data, context):
    """Export Admission Records to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Admission Records"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Hospital Number', 18),
        ('Title', 10),
        ('Surname', 20),
        ('First Name', 20),
        ('Middle Name', 20),
        ('Full Name', 30),
        ('UPI', 15),
        ('Phone', 15),
        ('Email', 25),
        ('Address', 35),
        ('Sponsor', 15),
        ('Patient Type', 15),
        ('Gender', 10),
        ('Date of Birth', 15),
        ('Marital Status', 15),
        ('Admitted By', 25),
        ('Admission Date', 20),
        ('Bed Allocated By', 25),
        ('Allocation Date', 20),
        ('Discharged By', 25),
        ('Discharged Date', 20),
        ('Bill Cleared By', 25),
        ('Cleared Date', 20),
        ('Ward Name', 20),
        ('Bed Name', 20),
    ]
    
    # Apply headers - using blue theme for admission
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="1E88E5", end_color="1E88E5", fill_type="solid")  # Blue for admission
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        patient = row_data['patient']
        
        # Get patient title
        title = get_patient_title(patient)
        
        row = [
            row_idx - 1,  # S/N
            patient.hospital_number or '',
            title,
            patient.surname or '',
            patient.first_name or '',
            patient.other_name or '',
            patient.get_full_name() or '',
            getattr(patient, 'insurance_policy_number', '') or '',
            patient.phone_number or '',
            patient.email_address or '',
            patient.address or '',
            getattr(patient.plan, 'plan', '') if patient.plan else '',
            getattr(patient.category, 'category', '') if patient.category else '',
            patient.gender or '',
            patient.dob.strftime('%d-%m-%Y') if patient.dob else '',
            patient.patient_type or '',
            row_data['doctor_admitted_name'],
            row_data['doctor_admit_date'].strftime('%d-%m-%Y %H:%M') if row_data['doctor_admit_date'] else '',
            row_data['nurse_admitted_name'],
            row_data['nurse_admit_date'].strftime('%d-%m-%Y %H:%M') if row_data['nurse_admit_date'] else '',
            row_data['doctor_discharged_name'],
            row_data['doctor_discharge_date'].strftime('%d-%m-%Y %H:%M') if row_data['doctor_discharge_date'] else '',
            row_data['bill_cleared_name'],
            row_data['bill_discharge_date'].strftime('%d-%m-%Y %H:%M') if row_data['bill_discharge_date'] else '',
            row_data['ward_name'],
            row_data['bed_name'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Generate filename
    start_date = context.get('start_date', '')
    end_date = context.get('end_date', '')
    filename = f"ISALU_HOSPITALS_admission_records_{start_date}_to_{end_date}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_admission_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


# heloer functions

def get_patient_title(patient):
    """Get appropriate title based on gender and marital status"""
    if not patient:
        return ''
    if patient.gender and patient.gender.lower() == 'male':
        return 'Mr.'
    elif patient.gender and patient.gender.lower() == 'female':
        if patient.patient_type and patient.patient_type.lower() == 'married':
            return 'Mrs.'
        else:
            return 'Miss.'
    return ''


@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def deactivated_patients_report(request):
    """Generate Deactivated Patients Report"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    deactivated_date_from = request.GET.get('deactivated_date_from')
    deactivated_date_to = request.GET.get('deactivated_date_to')
    deactivated_by = request.GET.get('deactivated_by', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # Get filter options for dropdowns
    # Get unique users who have deactivated patients 
    deactivated_by_list = PatientProfile.objects.filter(
        active=0,
        deactivated_by__isnull=False
    ).exclude(deactivated_by='').values_list('deactivated_by', flat=True).distinct().order_by('deactivated_by')
    deactivated_by_list = [{'id': name, 'fullname': name} for name in deactivated_by_list if name]
    
    context = {
        'deactivated_date_from': deactivated_date_from,
        'deactivated_date_to': deactivated_date_to,
        'deactivated_by': deactivated_by,
        'deactivated_by_list': deactivated_by_list,
        'orientation': orientation,
        'destination': destination,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_deactivated_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/deactivated_patients.html', context)


def generate_deactivated_export(request, context):
    """Generate Excel or PDF export for Deactivated Patients"""
    
    # Build the queryset with filters
    deactivated_data = get_deactivated_data(context)
    
    if not deactivated_data:
        return HttpResponse("No deactivated patients found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_deactivated_to_excel(deactivated_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_deactivated_to_pdf(deactivated_data, context)


def get_deactivated_data(context):
    """Fetch deactivated patients with filters applied"""
    
    # Starting with all deactivated patients (active == 0)
    queryset = PatientProfile.objects.filter(
        active=0
    ).select_related('plan', 'category', 'created_by')
    
    # Apply deactivated date filter
    deactivated_date_from = context.get('deactivated_date_from')
    deactivated_date_to = context.get('deactivated_date_to')
    
    if deactivated_date_from and deactivated_date_to:
        try:
            from_date = datetime.strptime(deactivated_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(deactivated_date_to, '%Y-%m-%d').date()
            to_date = to_date + timedelta(days=1)
            
            queryset = queryset.filter(
                deactivated_date__isnull=False,
                deactivated_date__date__gte=from_date,
                deactivated_date__date__lt=to_date
            )
        except ValueError:
            pass
    
    # Apply deactivated_by filter (CharField - exact match)
    deactivated_by = context.get('deactivated_by')
    if deactivated_by and deactivated_by != 'All':
        queryset = queryset.filter(deactivated_by=deactivated_by)
    
    # Order by deactivated date (newest first)
    queryset = queryset.order_by('-deactivated_date')
    
    logger.info(f"Found {queryset.count()} deactivated patients")
    
    # Process each record
    all_records = []
    for patient in queryset:
        # Get patient title
        title = get_patient_title(patient)
        
        # Get created by name
        created_by = patient.created_by
        created_by_name = created_by.fullname if created_by else ''
        
        # Get deactivated by name (CharField)
        deactivated_by_name = patient.deactivated_by or ''
        
        # Build row data
        row = {
            'patient': patient,
            'title': title,
            'created_by': created_by_name,
            'created_date': patient.created_date,
            'deactivated_by': deactivated_by_name,
            'deactivated_date': patient.deactivated_date,
        }
        
        all_records.append(row)
    
    return all_records


def export_deactivated_to_excel(export_data, context):
    """Export Deactivated Patients to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Deactivated Patients"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Hospital Number', 18),
        ('Title', 10),
        ('Surname', 20),
        ('First Name', 20),
        ('Middle Name', 20),
        ('Full Name', 30),
        ('UPI', 15),
        ('Phone', 15),
        ('Email', 25),
        ('Address', 35),
        ('Sponsor', 15),
        ('Patient Type', 15),
        ('Gender', 10),
        ('Date of Birth', 15),
        ('Marital Status', 15),
        ('Account Created Date', 20),
        ('Account Created By', 25),
        ('Account Deactivated Date', 20),
        ('Account Deactivated By', 25),
    ]
    
    # Apply headers - using red theme for deactivated
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="DC3545", end_color="DC3545", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        patient = row_data['patient']
        
        row = [
            row_idx - 1,  # S/N
            patient.hospital_number or '',
            row_data['title'],
            patient.surname or '',
            patient.first_name or '',
            patient.other_name or '',
            patient.get_full_name() or '',
            getattr(patient, 'insurance_policy_number', '') or '',
            patient.phone_number or '',
            patient.email_address or '',
            patient.address or '',
            getattr(patient.plan, 'plan', '') if patient.plan else '',
            getattr(patient.category, 'category', '') if patient.category else '',
            patient.gender or '',
            patient.dob.strftime('%d-%m-%Y') if patient.dob else '',
            patient.patient_type or '',
            row_data['created_date'].strftime('%d-%m-%Y %H:%M') if row_data['created_date'] else '',
            row_data['created_by'],
            row_data['deactivated_date'].strftime('%d-%m-%Y %H:%M') if row_data['deactivated_date'] else '',
            row_data['deactivated_by'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Highlight deactivated rows in light red
    for row_idx in range(2, len(export_data) + 2):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color="FFE6E6", end_color="FFE6E6", fill_type="solid")
    
    # Generate filename
    deactivated_date_from = context.get('deactivated_date_from', '')
    deactivated_date_to = context.get('deactivated_date_to', '')
    
    if deactivated_date_from and deactivated_date_to:
        filename = f"ISALU_HOSPITALS_patients_deactivated_accounts_{deactivated_date_from}_to_{deactivated_date_to}.xlsx"
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        filename = f"ISALU_HOSPITALS_patients_deactivated_accounts_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_deactivated_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


# Expired Products Models Configuration - CORRECTED APP NAMES
PRODUCTS_MODELS = [
    {'model': 'Product', 'app': 'inventory', 'store_label': 'Main Store'},
    {'model': 'Drugs', 'app': 'IPD_pharm', 'store_label': 'IPD Pharmacy 1'},
    {'model': 'Ipd2Drugs', 'app': 'IPD_pharm2', 'store_label': 'IPD Pharmacy 2'},
    {'model': 'Ipd3Drugs', 'app': 'IPD_pharm3', 'store_label': 'IPD Pharmacy 3'},
    {'model': 'OpdDrugs', 'app': 'OPD_pharm', 'store_label': 'OPD Pharmacy 1'},
    {'model': 'Opd2Drugs', 'app': 'OPD_pharm2', 'store_label': 'OPD Pharmacy 2'},
]


@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def expired_products_report(request):
    """Generate Expired Products Report"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    expiry_date_from = request.GET.get('expiry_date_from')
    expiry_date_to = request.GET.get('expiry_date_to')
    store_label = request.GET.get('store_label', 'All')
    staff_name = request.GET.get('staff_name', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # Get filter options for dropdowns
    store_labels = sorted([model['store_label'] for model in PRODUCTS_MODELS])
    
    # Get unique staff names from all product models
    staff_names = get_unique_staff_names_for_products()
    
    context = {
        'expiry_date_from': expiry_date_from,
        'expiry_date_to': expiry_date_to,
        'store_label': store_label,
        'staff_name': staff_name,
        'store_labels': store_labels,
        'staff_names': staff_names,
        'orientation': orientation,
        'destination': destination,
        'products_models': PRODUCTS_MODELS,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_expired_products_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/expired_products.html', context)


def get_unique_staff_names_for_products():
    """Get unique staff names from all product models"""
    staff_names = set()
    
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            
            # Get distinct staff IDs from the model
            staff_ids = model.objects.filter(
                staff__isnull=False
            ).values_list('staff__id', flat=True).distinct()
            
            # Get user fullnames
            users = User.objects.filter(id__in=staff_ids)
            for user in users:
                if user.fullname:
                    staff_names.add(user.fullname)
                    
        except Exception as e:
            logger.error(f"Error getting staff names from {config['app']}.{config['model']}: {e}")
            continue
    
    return sorted(list(staff_names))


def generate_expired_products_export(request, context):
    """Generate Excel or PDF export for Expired Products"""
    
    # Build the queryset with filters
    expired_data = get_expired_products_data(context)
    
    if not expired_data:
        return HttpResponse("No expired products found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_expired_products_to_excel(expired_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_expired_products_to_pdf(expired_data, context)


def get_expired_products_data(context):
    """Fetch expired products from all store models with filters applied"""
    
    all_records = []
    today = timezone.now().date()
    
    # Get filter parameters
    expiry_date_from = context.get('expiry_date_from')
    expiry_date_to = context.get('expiry_date_to')
    store_label_filter = context.get('store_label')
    staff_name_filter = context.get('staff_name')
    
    # Parse expiry date range with timezone awareness
    expiry_from = None
    expiry_to = None
    
    if expiry_date_from:
        try:
            expiry_from = datetime.strptime(expiry_date_from, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    if expiry_date_to:
        try:
            expiry_to = datetime.strptime(expiry_date_to, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    # Log the filters for debugging
    logger.info(f"Expiry date filter - From: {expiry_from}, To: {expiry_to}")
    logger.info(f"Today's date: {today}")
    
    # Iterate through each product model
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            store_label = config['store_label']
            
            # Apply store label filter
            if store_label_filter and store_label_filter != 'All':
                if store_label_filter != store_label:
                    continue
            
            # Build base queryset - stock > 0 and expiry_date is not null
            queryset = model.objects.filter(
                stock__gt=0,
                expiry_date__isnull=False
            )
            

            queryset = queryset.filter(expiry_date__lt=today)
            
            # Then apply the date range filter IF provided
            if expiry_from and expiry_to:
                # Filter products that expired within the date range
                queryset = queryset.filter(
                    expiry_date__gte=expiry_from,
                    expiry_date__lte=expiry_to
                )
                logger.info(f"Filtering by date range: {expiry_from} to {expiry_to}")
            elif expiry_from:
                queryset = queryset.filter(expiry_date__gte=expiry_from)
                logger.info(f"Filtering by date from: {expiry_from}")
            elif expiry_to:
                queryset = queryset.filter(expiry_date__lte=expiry_to)
                logger.info(f"Filtering by date to: {expiry_to}")
            else:
                logger.info("No date range filter applied - showing all expired products")
            
            # Apply staff filter
            if staff_name_filter and staff_name_filter != 'All':
                queryset = queryset.filter(staff__fullname=staff_name_filter)
                logger.info(f"Filtering by staff: {staff_name_filter}")
            
            # Select related fields for optimization
            queryset = queryset.select_related('staff')
            
            # Log count for debugging
            record_count = queryset.count()
            logger.info(f"Found {record_count} expired products in {store_label}")
            
            # Process each record
            for record in queryset:
                # Calculate expiry status
                days_expired = (today - record.expiry_date).days
                if days_expired == 0:
                    expiry_status = "Expires today"
                elif days_expired == 1:
                    expiry_status = "Expired 1 day ago"
                else:
                    expiry_status = f"Expired {days_expired} days ago"
                
                # Get staff name
                staff_name = record.staff.fullname if record.staff else ''
                
                # Build row data
                row = {
                    'product_name': record.product_name or '',
                    'product_id': record.product_id or '',
                    'description': record.description or '',
                    'price': float(record.price) if record.price else 0,
                    'stock': record.stock or 0,
                    'minimum_UoM': record.minimum_UoM or '',
                    'low_stock_threshold': record.low_stock_threshold or 0,
                    'manufacturing_date': record.manufacturing_date,
                    'expiry_date': record.expiry_date,
                    'expiry_status': expiry_status,
                    'store_label': store_label,
                    'staff_name': staff_name,
                    'created_date': record.created_date,
                }
                
                all_records.append(row)
                
        except Exception as e:
            logger.error(f"Error processing {config['app']}.{config['model']}: {e}")
            continue
    
    # Sort by expiry date (oldest first - most urgent)
    all_records.sort(key=lambda x: x['expiry_date'])
    
    logger.info(f"Total expired products found across all stores: {len(all_records)}")
    return all_records


def export_expired_products_to_excel(export_data, context):
    """Export Expired Products to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Expired Products"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Product Name', 35),
        ('Product ID', 18),
        ('Description', 40),
        ('Price (₦)', 15),
        ('Stock', 12),
        ('Minimum UoM', 15),
        ('Low Stock Threshold', 18),
        ('Manufacturing Date', 20),
        ('Expiry Date', 20),
        ('Expiry Status', 25),
        ('Store Label', 20),
        ('Uploaded By', 25),
        ('Created Date', 20),
    ]
    
    # Apply headers - using orange/red theme for expired products
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="E65100", end_color="E65100", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_idx - 1,  # S/N
            row_data['product_name'],
            row_data['product_id'],
            row_data['description'],
            row_data['price'],
            row_data['stock'],
            row_data['minimum_UoM'],
            row_data['low_stock_threshold'],
            row_data['manufacturing_date'].strftime('%d-%m-%Y') if row_data['manufacturing_date'] else '',
            row_data['expiry_date'].strftime('%d-%m-%Y') if row_data['expiry_date'] else '',
            row_data['expiry_status'],
            row_data['store_label'],
            row_data['staff_name'],
            row_data['created_date'].strftime('%d-%m-%Y %H:%M') if row_data['created_date'] else '',
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Price column - 5)
            if col == 5:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Color code based on expiry severity
    for row_idx in range(2, len(export_data) + 2):
        expiry_status = export_data[row_idx - 2]['expiry_status']
        days_ago = 0
        try:
            if "days ago" in expiry_status:
                days_ago = int(expiry_status.split()[1])
        except:
            pass
        
        # Color based on severity
        if days_ago > 30:
            color = "FFCCCC"  # Dark red for very old expired
        elif days_ago > 7:
            color = "FFE0B2"  # Orange for medium expired
        else:
            color = "FFF3E0"  # Light orange for recently expired
        
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    
    # Generate filename
    expiry_date_from = context.get('expiry_date_from', '')
    expiry_date_to = context.get('expiry_date_to', '')
    
    if expiry_date_from and expiry_date_to:
        filename = f"ISALU_HOSPITALS_expired_products_detail_{expiry_date_from}_to_{expiry_date_to}.xlsx"
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        filename = f"ISALU_HOSPITALS_expired_products_detail_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_expired_products_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")



# Expired Products Models Configuration
PRODUCTS_MODELS = [
    {'model': 'Product', 'app': 'inventory', 'store_label': 'Main Store'},
    {'model': 'Drugs', 'app': 'IPD_pharm', 'store_label': 'IPD Pharmacy 1'},
    {'model': 'Ipd2Drugs', 'app': 'IPD_pharm2', 'store_label': 'IPD Pharmacy 2'},
    {'model': 'Ipd3Drugs', 'app': 'IPD_pharm3', 'store_label': 'IPD Pharmacy 3'},
    {'model': 'OpdDrugs', 'app': 'OPD_pharm', 'store_label': 'OPD Pharmacy 1'},
    {'model': 'Opd2Drugs', 'app': 'OPD_pharm2', 'store_label': 'OPD Pharmacy 2'},
]

# EXPIRY FLAG OPTIONS
EXPIRY_FLAG_CHOICES = {
    'hours': 'Hours',
    'days': 'Days',
    'weeks': 'Weeks',
}


# Expiring products report

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def expiring_products_report(request):
    """Generate Expiring Products Report (products approaching expiry)"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    expiry_date_from = request.GET.get('expiry_date_from')
    expiry_date_to = request.GET.get('expiry_date_to')
    store_label = request.GET.get('store_label', 'All')
    expiry_flag = request.GET.get('expiry_flag', 'All')
    expiry_flag_num = request.GET.get('expiry_flag_num', '')
    staff_name = request.GET.get('staff_name', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # Get filter options for dropdowns
    store_labels = sorted([model['store_label'] for model in PRODUCTS_MODELS])
    
    # Get unique staff names from all product models
    staff_names = get_unique_staff_names_for_products()
    
    context = {
        'expiry_date_from': expiry_date_from,
        'expiry_date_to': expiry_date_to,
        'store_label': store_label,
        'expiry_flag': expiry_flag,
        'expiry_flag_num': expiry_flag_num,
        'staff_name': staff_name,
        'store_labels': store_labels,
        'staff_names': staff_names,
        'expiry_flag_choices': EXPIRY_FLAG_CHOICES,
        'orientation': orientation,
        'destination': destination,
        'products_models': PRODUCTS_MODELS,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_expiring_products_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/expiring_products.html', context)


def get_unique_staff_names_for_products():
    """Get unique staff names from all product models"""
    staff_names = set()
    
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            
            # Get distinct staff IDs from the model
            staff_ids = model.objects.filter(
                staff__isnull=False
            ).values_list('staff__id', flat=True).distinct()
            
            # Get user fullnames
            users = User.objects.filter(id__in=staff_ids)
            for user in users:
                if user.fullname:
                    staff_names.add(user.fullname)
                    
        except Exception as e:
            logger.error(f"Error getting staff names from {config['app']}.{config['model']}: {e}")
            continue
    
    return sorted(list(staff_names))


def generate_expiring_products_export(request, context):
    """Generate Excel or PDF export for Expiring Products"""
    
    # Build the queryset with filters
    expiring_data = get_expiring_products_data(context)
    
    if not expiring_data:
        return HttpResponse("No expiring products found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_expiring_products_to_excel(expiring_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_expiring_products_to_pdf(expiring_data, context)


def get_expiring_products_data(context):
    """Fetch expiring products from all store models with filters applied"""
    
    all_records = []
    today = timezone.now().date()
    
    # Get filter parameters
    expiry_date_from = context.get('expiry_date_from')
    expiry_date_to = context.get('expiry_date_to')
    store_label_filter = context.get('store_label')
    expiry_flag_filter = context.get('expiry_flag')
    expiry_flag_num_filter = context.get('expiry_flag_num')
    staff_name_filter = context.get('staff_name')
    
    # Parse expiry date range
    expiry_from = None
    expiry_to = None
    
    if expiry_date_from and expiry_date_to:
        try:
            expiry_from = datetime.strptime(expiry_date_from, '%Y-%m-%d').date()
            expiry_to = datetime.strptime(expiry_date_to, '%Y-%m-%d').date()
        except ValueError:
            pass
    
    # Parse expiry flag number
    flag_num = None
    if expiry_flag_num_filter and expiry_flag_num_filter != '':
        try:
            flag_num = int(expiry_flag_num_filter)
        except ValueError:
            pass
    
    # Iterate through each product model
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            store_label = config['store_label']
            
            # Apply store label filter
            if store_label_filter and store_label_filter != 'All':
                if store_label_filter != store_label:
                    continue
            
            # Build base queryset - stock > 0 and expiry_date is not null
            queryset = model.objects.filter(
                stock__gt=0,
                expiry_date__isnull=False
            )
            
            # Apply expiry flag filter
            if expiry_flag_filter and expiry_flag_filter != 'All':
                queryset = queryset.filter(expiry_flag_in__iexact=expiry_flag_filter)
                
                # Apply expiry flag number filter if provided
                if flag_num is not None:
                    queryset = queryset.filter(expiry_flag_in_num=flag_num)
            elif flag_num is not None:
                # If only number is provided, filter by that number
                queryset = queryset.filter(expiry_flag_in_num=flag_num)
            
            # Apply expiry date range filter
            if expiry_from and expiry_to:
                queryset = queryset.filter(
                    expiry_date__date__gte=expiry_from,
                    expiry_date__date__lte=expiry_to
                )
            elif expiry_from:
                queryset = queryset.filter(expiry_date__date__gte=expiry_from)
            elif expiry_to:
                queryset = queryset.filter(expiry_date__date__lte=expiry_to)
            
            # Apply staff filter
            if staff_name_filter and staff_name_filter != 'All':
                queryset = queryset.filter(staff__fullname=staff_name_filter)
            
            # Select related fields for optimization
            queryset = queryset.select_related('staff')
            
            # Process each record
            for record in queryset:
                # Calculate days until expiry
                days_until_expiry = (record.expiry_date - today).days
                
                # Check if product is actually approaching expiry based on flag
                should_include = False
                
                if record.expiry_flag_in and record.expiry_flag_in_num:
                    flag_in = record.expiry_flag_in.lower()
                    flag_num = record.expiry_flag_in_num
                    
                    if flag_in == 'hours':
                        threshold_days = flag_num / 24
                    elif flag_in == 'days':
                        threshold_days = flag_num
                    elif flag_in == 'weeks':
                        threshold_days = flag_num * 7
                    else:
                        threshold_days = 0
                    
                    # Include if days until expiry <= threshold and > 0
                    if 0 < days_until_expiry <= threshold_days:
                        should_include = True
                else:
                    # If no flag set, include all products with expiry_date > today
                    # (as long as they're not already expired)
                    if days_until_expiry > 0:
                        should_include = True
                
                # If product doesn't meet the flag criteria, skip it
                if not should_include:
                    continue
                
                # Calculate expiring status
                if days_until_expiry == 0:
                    expiring_status = "Expiring today"
                elif days_until_expiry == 1:
                    expiring_status = "Expiring in 1 day"
                else:
                    expiring_status = f"Expiring in {days_until_expiry} days"
                
                # Get staff name
                staff_name = record.staff.fullname if record.staff else ''
                
                # Build row data
                row = {
                    'product_name': record.product_name or '',
                    'product_id': record.product_id or '',
                    'description': record.description or '',
                    'price': float(record.price) if record.price else 0,
                    'stock': record.stock or 0,
                    'minimum_UoM': record.minimum_UoM or '',
                    'low_stock_threshold': record.low_stock_threshold or 0,
                    'manufacturing_date': record.manufacturing_date,
                    'expiry_date': record.expiry_date,
                    'expiring_status': expiring_status,
                    'store_label': store_label,
                    'staff_name': staff_name,
                    'created_date': record.created_date,
                    'days_until_expiry': days_until_expiry,
                }
                
                all_records.append(row)
                
        except Exception as e:
            logger.error(f"Error processing {config['app']}.{config['model']}: {e}")
            continue
    
    # Sort by days until expiry (soonest first)
    all_records.sort(key=lambda x: x['days_until_expiry'])
    
    logger.info(f"Total expiring products found: {len(all_records)}")
    return all_records


def export_expiring_products_to_excel(export_data, context):
    """Export Expiring Products to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Expiring Products"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Product Name', 35),
        ('Product ID', 18),
        ('Description', 40),
        ('Price (₦)', 15),
        ('Stock', 12),
        ('Minimum UoM', 15),
        ('Low Stock Threshold', 18),
        ('Manufacturing Date', 20),
        ('Expiry Date', 20),
        ('Expiring On', 25),
        ('Store Label', 20),
        ('Uploaded By', 25),
        ('Created Date', 20),
    ]
    
    # Apply headers - using yellow/amber theme for expiring products
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="F9A825", end_color="F9A825", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_idx - 1,  # S/N
            row_data['product_name'],
            row_data['product_id'],
            row_data['description'],
            row_data['price'],
            row_data['stock'],
            row_data['minimum_UoM'],
            row_data['low_stock_threshold'],
            row_data['manufacturing_date'].strftime('%d-%m-%Y') if row_data['manufacturing_date'] else '',
            row_data['expiry_date'].strftime('%d-%m-%Y') if row_data['expiry_date'] else '',
            row_data['expiring_status'],
            row_data['store_label'],
            row_data['staff_name'],
            row_data['created_date'].strftime('%d-%m-%Y %H:%M') if row_data['created_date'] else '',
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Price column - 5)
            if col == 5:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Color code based on urgency
    for row_idx in range(2, len(export_data) + 2):
        days = export_data[row_idx - 2]['days_until_expiry']
        
        # Color based on how soon it expires
        if days <= 3:
            color = "FFCCCC"  # Red - Critical (3 days or less)
        elif days <= 7:
            color = "FFE0B2"  # Orange - Warning (7 days or less)
        elif days <= 14:
            color = "FFF3E0"  # Light Orange - Notice (14 days or less)
        else:
            color = "FFFDE7"  # Light Yellow - Info
        
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    
    # Generate filename
    expiry_date_from = context.get('expiry_date_from', '')
    expiry_date_to = context.get('expiry_date_to', '')
    
    if expiry_date_from and expiry_date_to:
        filename = f"ISALU_HOSPITALS_expiring_products_detail_{expiry_date_from}_to_{expiry_date_to}.xlsx"
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        filename = f"ISALU_HOSPITALS_expiring_products_detail_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_expiring_products_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


# Products Models Configuration
PRODUCTS_MODELS = [
    {'model': 'Product', 'app': 'inventory', 'store_label': 'Main Store'},
    {'model': 'Drugs', 'app': 'IPD_pharm', 'store_label': 'IPD Pharmacy 1'},
    {'model': 'Ipd2Drugs', 'app': 'IPD_pharm2', 'store_label': 'IPD Pharmacy 2'},
    {'model': 'Ipd3Drugs', 'app': 'IPD_pharm3', 'store_label': 'IPD Pharmacy 3'},
    {'model': 'OpdDrugs', 'app': 'OPD_pharm', 'store_label': 'OPD Pharmacy 1'},
    {'model': 'Opd2Drugs', 'app': 'OPD_pharm2', 'store_label': 'OPD Pharmacy 2'},
]

# EXPIRY FLAG OPTIONS
EXPIRY_FLAG_CHOICES = {
    'hours': 'Hours',
    'days': 'Days',
    'weeks': 'Weeks',
}


# out of stock products report

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def out_of_stock_products_report(request):
    """Generate Out of Stock Products Report (stock == 0)"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    store_label = request.GET.get('store_label', 'All')
    staff_name = request.GET.get('staff_name', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # Get filter options for dropdowns
    store_labels = sorted([model['store_label'] for model in PRODUCTS_MODELS])
    
    # Get unique staff names from all product models
    staff_names = get_unique_staff_names_for_products()
    
    context = {
        'store_label': store_label,
        'staff_name': staff_name,
        'store_labels': store_labels,
        'staff_names': staff_names,
        'orientation': orientation,
        'destination': destination,
        'products_models': PRODUCTS_MODELS,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_out_of_stock_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/out_of_stock_products.html', context)


def get_unique_staff_names_for_products():
    """Get unique staff names from all product models"""
    staff_names = set()
    
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            
            # Get distinct staff IDs from the model
            staff_ids = model.objects.filter(
                staff__isnull=False
            ).values_list('staff__id', flat=True).distinct()
            
            # Get user fullnames
            users = User.objects.filter(id__in=staff_ids)
            for user in users:
                if user.fullname:
                    staff_names.add(user.fullname)
                    
        except Exception as e:
            logger.error(f"Error getting staff names from {config['app']}.{config['model']}: {e}")
            continue
    
    return sorted(list(staff_names))


def generate_out_of_stock_export(request, context):
    """Generate Excel or PDF export for Out of Stock Products"""
    
    # Build the queryset with filters
    out_of_stock_data = get_out_of_stock_products_data(context)
    
    if not out_of_stock_data:
        return HttpResponse("No out of stock products found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_out_of_stock_products_to_excel(out_of_stock_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_out_of_stock_products_to_pdf(out_of_stock_data, context)


def get_out_of_stock_products_data(context):
    """Fetch out of stock products from all store models with filters applied"""
    
    all_records = []
    
    # Get filter parameters
    store_label_filter = context.get('store_label')
    staff_name_filter = context.get('staff_name')
    
    # Iterate through each product model
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            store_label = config['store_label']
            
            # Apply store label filter
            if store_label_filter and store_label_filter != 'All':
                if store_label_filter != store_label:
                    continue
            
            # Build queryset - stock == 0 (out of stock)
            queryset = model.objects.filter(
                stock=0
            )
            
            # Apply staff filter
            if staff_name_filter and staff_name_filter != 'All':
                queryset = queryset.filter(staff__fullname=staff_name_filter)
            
            # Select related fields for optimization
            queryset = queryset.select_related('staff')
            
            # Process each record
            for record in queryset:
                # Get staff name
                staff_name = record.staff.fullname if record.staff else ''
                
                # Build row data
                row = {
                    'product_name': record.product_name or '',
                    'product_id': record.product_id or '',
                    'description': record.description or '',
                    'price': float(record.price) if record.price else 0,
                    'stock': record.stock or 0,
                    'manufacturing_date': record.manufacturing_date,
                    'expiry_date': record.expiry_date,
                    'store_label': store_label,
                    'staff_name': staff_name,
                    'created_date': record.created_date,
                }
                
                all_records.append(row)
                
        except Exception as e:
            logger.error(f"Error processing {config['app']}.{config['model']}: {e}")
            continue
    
    # Sort by product name
    all_records.sort(key=lambda x: x['product_name'])
    
    logger.info(f"Total out of stock products found: {len(all_records)}")
    return all_records


def export_out_of_stock_products_to_excel(export_data, context):
    """Export Out of Stock Products to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Out of Stock Products"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Product Name', 35),
        ('Product ID', 18),
        ('Description', 40),
        ('Price (₦)', 15),
        ('Stock', 12),
        ('Manufacturing Date', 20),
        ('Expiry Date', 20),
        ('Store Label', 20),
        ('Uploaded By', 25),
        ('Created Date', 20),
    ]
    
    # Apply headers - using red theme for out of stock
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="C62828", end_color="C62828", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_idx - 1,  # S/N
            row_data['product_name'],
            row_data['product_id'],
            row_data['description'],
            row_data['price'],
            row_data['stock'],
            row_data['manufacturing_date'].strftime('%d-%m-%Y') if row_data['manufacturing_date'] else '',
            row_data['expiry_date'].strftime('%d-%m-%Y') if row_data['expiry_date'] else '',
            row_data['store_label'],
            row_data['staff_name'],
            row_data['created_date'].strftime('%d-%m-%Y %H:%M') if row_data['created_date'] else '',
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Price column - 5)
            if col == 5:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Highlight out of stock rows in light red
    for row_idx in range(2, len(export_data) + 2):
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color="FFCDD2", end_color="FFCDD2", fill_type="solid")
    
    # Generate filename
    today = timezone.now().date().strftime('%Y-%m-%d')
    filename = f"ISALU_HOSPITALS_out_of_stock_products_detail_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_out_of_stock_products_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


# Low stock product reports

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def low_stock_products_report(request):
    """Generate Low Stock Products Report (stock <= low_stock_threshold)"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    store_label = request.GET.get('store_label', 'All')
    staff_name = request.GET.get('staff_name', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # Get filter options for dropdowns
    store_labels = sorted([model['store_label'] for model in PRODUCTS_MODELS])
    
    # Get unique staff names from all product models
    staff_names = get_unique_staff_names_for_products()
    
    context = {
        'store_label': store_label,
        'staff_name': staff_name,
        'store_labels': store_labels,
        'staff_names': staff_names,
        'orientation': orientation,
        'destination': destination,
        'products_models': PRODUCTS_MODELS,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_low_stock_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/low_stock_products.html', context)


def generate_low_stock_export(request, context):
    """Generate Excel or PDF export for Low Stock Products"""
    
    # Build the queryset with filters
    low_stock_data = get_low_stock_products_data(context)
    
    if not low_stock_data:
        return HttpResponse("No low stock products found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_low_stock_products_to_excel(low_stock_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_low_stock_products_to_pdf(low_stock_data, context)



def get_low_stock_products_data(context):
    """Fetch low stock products from all store models with filters applied"""
    
    all_records = []
    today = timezone.now().date()
    
    # Get filter parameters
    store_label_filter = context.get('store_label')
    staff_name_filter = context.get('staff_name')
    
    # Iterate through each product model
    for config in PRODUCTS_MODELS:
        try:
            model = apps.get_model(config['app'], config['model'])
            store_label = config['store_label']
            
            # Apply store label filter
            if store_label_filter and store_label_filter != 'All':
                if store_label_filter != store_label:
                    continue
            

            queryset = model.objects.filter(
                stock__gt=0,
                stock__lte=F('low_stock_threshold')
            )
            
            # Apply staff filter
            if staff_name_filter and staff_name_filter != 'All':
                queryset = queryset.filter(staff__fullname=staff_name_filter)
            
            # Select related fields for optimization
            queryset = queryset.select_related('staff')
            
            # Log the count for debugging
            count = queryset.count()
            logger.info(f"Found {count} low stock products in {store_label}")
            
            # Process each record
            for record in queryset:
                # Calculate expiry status
                days_until_expiry = None
                expiring_status = ''
                
                if record.expiry_date:
                    days_until_expiry = (record.expiry_date - today).days
                    if days_until_expiry < 0:
                        expiring_status = "Expired"
                    elif days_until_expiry == 0:
                        expiring_status = "Expires today"
                    elif days_until_expiry == 1:
                        expiring_status = "Expires in 1 day"
                    else:
                        expiring_status = f"Expires in {days_until_expiry} days"
                
                # Get staff name
                staff_name = record.staff.fullname if record.staff else ''
                
                # Build row data
                row = {
                    'product_name': record.product_name or '',
                    'product_id': record.product_id or '',
                    'description': record.description or '',
                    'price': float(record.price) if record.price else 0,
                    'stock': record.stock or 0,
                    'minimum_UoM': record.minimum_UoM or '',
                    'low_stock_threshold': record.low_stock_threshold or 0,
                    'manufacturing_date': record.manufacturing_date,
                    'expiry_date': record.expiry_date,
                    'expiring_status': expiring_status,
                    'store_label': store_label,
                    'staff_name': staff_name,
                    'created_date': record.created_date,
                    'stock_level': record.stock,
                    'threshold': record.low_stock_threshold,
                }
                
                all_records.append(row)
                
        except Exception as e:
            logger.error(f"Error processing {config['app']}.{config['model']}: {e}")
            continue
    
    # Sort by stock level (lowest first)
    all_records.sort(key=lambda x: x['stock_level'])
    
    logger.info(f"Total low stock products found: {len(all_records)}")
    return all_records


def export_low_stock_products_to_excel(export_data, context):
    """Export Low Stock Products to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Low Stock Products"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Product Name', 35),
        ('Product ID', 18),
        ('Description', 40),
        ('Price (₦)', 15),
        ('Stock', 12),
        ('Minimum UoM', 15),
        ('Low Stock Threshold', 18),
        ('Manufacturing Date', 20),
        ('Expiry Date', 20),
        ('Expiring On', 25),
        ('Store Label', 20),
        ('Uploaded By', 25),
        ('Created Date', 20),
    ]
    
    # Apply headers - using orange/amber theme for low stock
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="E65100", end_color="E65100", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_idx - 1,  # S/N
            row_data['product_name'],
            row_data['product_id'],
            row_data['description'],
            row_data['price'],
            row_data['stock'],
            row_data['minimum_UoM'],
            row_data['low_stock_threshold'],
            row_data['manufacturing_date'].strftime('%d-%m-%Y') if row_data['manufacturing_date'] else '',
            row_data['expiry_date'].strftime('%d-%m-%Y') if row_data['expiry_date'] else '',
            row_data['expiring_status'],
            row_data['store_label'],
            row_data['staff_name'],
            row_data['created_date'].strftime('%d-%m-%Y %H:%M') if row_data['created_date'] else '',
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Price column - 5)
            if col == 5:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Color code based on stock level urgency
    for row_idx in range(2, len(export_data) + 2):
        stock = export_data[row_idx - 2]['stock_level']
        threshold = export_data[row_idx - 2]['threshold']
        
        # Calculate how critical the stock level is
        if threshold > 0:
            percentage = (stock / threshold) * 100
        else:
            percentage = 0
        
        # Color based on percentage of threshold remaining
        if percentage <= 25:
            color = "FFCCCC"  # Red - Critical (≤25% of threshold)
        elif percentage <= 50:
            color = "FFE0B2"  # Orange - Warning (≤50% of threshold)
        elif percentage <= 75:
            color = "FFF3E0"  # Light Orange - Notice (≤75% of threshold)
        else:
            color = "FFFDE7"  # Light Yellow - Info
        
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    
    # Generate filename
    today = timezone.now().date().strftime('%Y-%m-%d')
    filename = f"ISALU_HOSPITALS_low_stock_products_detail_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_low_stock_products_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


# Store mapping for source and destination
STORE_MAPPING = {
    'inventory': 'Main Store',
    'ipd_pharm': 'IPD Pharmacy 1',
    'ipd2_pharm': 'IPD Pharmacy 2',
    'ipd3_pharm': 'IPD Pharmacy 3',
    'opd_pharm': 'OPD Pharmacy 1',
    'opd2_pharm': 'OPD Pharmacy 2',
}

# Status mapping
STATUS_MAPPING = {
    0: 'Pending',
    1: 'Approved',
    2: 'Declined',
}

# Status colors for Excel
STATUS_COLORS = {
    'Pending': 'FFE082',      # Yellow
    'Approved': 'A5D6A7',     # Green
    'Declined': 'EF9A9A',     # Red
}

# product requisition reports

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def product_requisition_report(request):
    """Generate Product Requisition Report"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    request_date_from = request.GET.get('request_date_from')
    request_date_to = request.GET.get('request_date_to')
    request_from = request.GET.get('request_from', 'All')
    request_to = request.GET.get('request_to', 'All')
    requested_by = request.GET.get('requested_by', 'All')
    approved_by = request.GET.get('approved_by', 'All')
    request_status = request.GET.get('request_status', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    destination = request.GET.get('destination', 'excel')
    
    # Get filter options for dropdowns
    store_labels = sorted(STORE_MAPPING.values())
    
    # Get unique staff who made requests
    from inventory.models import ProductRequests
    requested_by_list = ProductRequests.objects.filter(
        staff__isnull=False
    ).values_list('staff__id', 'staff__fullname').distinct().order_by('staff__fullname')
    requested_by_list = [{'id': uid, 'fullname': fullname} for uid, fullname in requested_by_list if fullname]
    
    # Get unique staff2 (approvers)
    approved_by_list = ProductRequests.objects.filter(
        staff2__isnull=False
    ).exclude(staff2='').values_list('staff2', flat=True).distinct().order_by('staff2')
    approved_by_list = [{'id': name, 'fullname': name} for name in approved_by_list if name]
    
    context = {
        'request_date_from': request_date_from,
        'request_date_to': request_date_to,
        'request_from': request_from,
        'request_to': request_to,
        'requested_by': requested_by,
        'approved_by': approved_by,
        'request_status': request_status,
        'store_labels': store_labels,
        'requested_by_list': requested_by_list,
        'approved_by_list': approved_by_list,
        'status_choices': [{'value': 0, 'label': 'Pending'}, {'value': 1, 'label': 'Approved'}, {'value': 2, 'label': 'Declined'}],
        'orientation': orientation,
        'destination': destination,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_requisition_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/product_requisition.html', context)


def generate_requisition_export(request, context):
    """Generate Excel or PDF export for Product Requisition"""
    
    # Build the queryset with filters
    requisition_data = get_requisition_data(context)
    
    if not requisition_data:
        return HttpResponse("No requisition records found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('destination') == 'excel':
        return export_requisition_to_excel(requisition_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_requisition_to_pdf(requisition_data, context)


def get_requisition_data(context):
    """Fetch requisition records with filters applied"""
    
    from inventory.models import ProductRequests
    
    all_records = []
    
    # Get filter parameters
    request_date_from = context.get('request_date_from')
    request_date_to = context.get('request_date_to')
    request_from_filter = context.get('request_from')
    request_to_filter = context.get('request_to')
    requested_by_filter = context.get('requested_by')
    approved_by_filter = context.get('approved_by')
    request_status_filter = context.get('request_status')
    
    # Start with all requisitions
    queryset = ProductRequests.objects.select_related('product', 'staff')
    
    # Apply date filter - FIXED WITH TIMEZONE AWARENESS
    if request_date_from and request_date_to:
        try:
            from_date = datetime.strptime(request_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(request_date_to, '%Y-%m-%d').date()
            
            # Create timezone-aware datetime objects
            from_datetime = datetime.combine(from_date, datetime.min.time())
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__gte=from_datetime,
                created_date__lte=to_datetime
            )
            logger.info(f"Date filter applied: {request_date_from} to {request_date_to}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif request_date_from:
        try:
            from_date = datetime.strptime(request_date_from, '%Y-%m-%d').date()
            from_datetime = datetime.combine(from_date, datetime.min.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__gte=from_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif request_date_to:
        try:
            to_date = datetime.strptime(request_date_to, '%Y-%m-%d').date()
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__lte=to_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    
    # Apply request_from filter
    if request_from_filter and request_from_filter != 'All':
        for key, value in STORE_MAPPING.items():
            if value == request_from_filter:
                queryset = queryset.filter(source=key)
                break
    
    # Apply request_to filter
    if request_to_filter and request_to_filter != 'All':
        for key, value in STORE_MAPPING.items():
            if value == request_to_filter:
                queryset = queryset.filter(destination=key)
                break
    
    # Apply requested_by filter
    if requested_by_filter and requested_by_filter != 'All':
        queryset = queryset.filter(staff__id=requested_by_filter)
    
    # Apply approved_by filter
    if approved_by_filter and approved_by_filter != 'All':
        queryset = queryset.filter(staff2=approved_by_filter)
    
    # Apply status filter
    if request_status_filter and request_status_filter != 'All':
        status_map = {'Pending': 0, 'Approved': 1, 'Declined': 2}
        if request_status_filter in status_map:
            queryset = queryset.filter(status=status_map[request_status_filter])
    
    # Order by created date (newest first)
    queryset = queryset.order_by('-created_date')
    
    logger.info(f"Found {queryset.count()} requisition records")
    
    # Process each record
    for record in queryset:
        # Get source store label
        source_label = STORE_MAPPING.get(record.source, 'Unknown')
        
        # Get destination store label
        if record.destination and record.destination in STORE_MAPPING:
            destination_label = STORE_MAPPING[record.destination]
        else:
            destination_label = STORE_MAPPING.get('inventory', 'Main Store')
        
        # Get status text
        status_text = STATUS_MAPPING.get(record.status, 'Unknown')
        
        # Get product details
        product = record.product
        product_name = product.product_name if product else record.product_names or ''
        product_id = product.product_id if product else ''
        product_description = product.description if product else ''
        minimum_uom = record.minimum_UoM or (product.minimum_UoM if product else '')
        
        # Build row data
        row = {
            'product_name': product_name,
            'minimum_uom': minimum_uom,
            'product_id': product_id,
            'product_description': product_description,
            'price': float(record.price) if record.price else 0,
            'quantity': record.quantity or 0,
            'request_from': source_label,
            'request_to': destination_label,
            'requested_by': record.staff.fullname if record.staff else '',
            'approved_by': record.staff2 or '',
            'request_status': status_text,
            'status_code': record.status,
            'request_date': record.created_date,
            'record': record,
        }
        
        all_records.append(row)
    
    return all_records


def export_requisition_to_excel(export_data, context):
    """Export Product Requisition to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Product Requisitions"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Product Name', 35),
        ('Minimum UoM', 15),
        ('Product ID', 18),
        ('Description', 40),
        ('Price (₦)', 15),
        ('Quantity', 12),
        ('Request From', 20),
        ('Request To', 20),
        ('Requested By', 25),
        ('Approved By', 25),
        ('Request Status', 18),
        ('Request Date', 20),
    ]
    
    # Apply headers
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="1976D2", end_color="1976D2", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_idx - 1,  # S/N
            row_data['product_name'],
            row_data['minimum_uom'],
            row_data['product_id'],
            row_data['product_description'],
            row_data['price'],
            row_data['quantity'],
            row_data['request_from'],
            row_data['request_to'],
            row_data['requested_by'],
            row_data['approved_by'],
            row_data['request_status'],
            row_data['request_date'].strftime('%d-%m-%Y %H:%M') if row_data['request_date'] else '',
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Price column - 6)
            if col == 6:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Color code based on status
    for row_idx in range(2, len(export_data) + 2):
        status = export_data[row_idx - 2]['request_status']
        color = STATUS_COLORS.get(status, 'FFFFFF')
        
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    
    # Generate filename
    request_date_from = context.get('request_date_from', '')
    request_date_to = context.get('request_date_to', '')
    
    if request_date_from and request_date_to:
        filename = f"ISALU_HOSPITALS_products_requisitions_report_{request_date_from}_to_{request_date_to}.xlsx"
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        filename = f"ISALU_HOSPITALS_products_requisitions_report_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_requisition_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")



# Store mapping for destination
STORE_MAPPING = {
    'inventory': 'Main Store',
    'ipd_pharm': 'IPD Pharmacy 1',
    'ipd2_pharm': 'IPD Pharmacy 2',
    'ipd3_pharm': 'IPD Pharmacy 3',
    'opd_pharm': 'OPD Pharmacy 1',
    'opd2_pharm': 'OPD Pharmacy 2',
}

# Transaction type mapping
TRANSACTION_TYPE_MAPPING = {
    'PURCHASE': 'Incoming Inventory',
    'SALE': 'Outgoing Inventory',
}

# Transaction type colors for Excel
TRANSACTION_COLORS = {
    'Incoming Inventory': 'A5D6A7',  # Green
    'Outgoing Inventory': 'FFE082',  # Yellow
}

#  STOCK ANALYSIS REPORT

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def stock_analysis_report(request):
    """Generate Stock Analysis Report"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    transaction_date_from = request.GET.get('transaction_date_from')
    transaction_date_to = request.GET.get('transaction_date_to')
    transaction_type = request.GET.get('transaction_type', 'All')
    destination_filter = request.GET.get('destination', 'All')  
    created_by = request.GET.get('created_by', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    export_format = request.GET.get('format', 'excel')  
    
    # Get filter options for dropdowns
    store_labels = sorted(STORE_MAPPING.values())
    transaction_types = ['Incoming Inventory', 'Outgoing Inventory']
    
    # Get unique staff who created transactions
    from inventory.models import Transaction
    created_by_list = Transaction.objects.filter(
        staff__isnull=False
    ).values_list('staff__id', 'staff__fullname').distinct().order_by('staff__fullname')
    created_by_list = [{'id': uid, 'fullname': fullname} for uid, fullname in created_by_list if fullname]
    
    context = {
        'transaction_date_from': transaction_date_from,
        'transaction_date_to': transaction_date_to,
        'transaction_type': transaction_type,
        'destination_filter': destination_filter,  
        'created_by': created_by,
        'store_labels': store_labels,
        'transaction_types': transaction_types,
        'created_by_list': created_by_list,
        'orientation': orientation,
        'export_format': export_format, 
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_stock_analysis_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/stock_analysis.html', context)


def generate_stock_analysis_export(request, context):
    """Generate Excel or PDF export for Stock Analysis"""
    
    # Build the queryset with filters
    stock_data = get_stock_analysis_data(context)
    
    if not stock_data:
        return HttpResponse("No stock transactions found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('export_format') == 'excel':  # Changed from 'destination' to 'export_format'
        return export_stock_analysis_to_excel(stock_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_stock_analysis_to_pdf(stock_data, context)


def get_stock_analysis_data(context):
    """Fetch stock transactions with filters applied"""
    
    from inventory.models import Transaction
    
    all_records = []
    
    # Get filter parameters
    transaction_date_from = context.get('transaction_date_from')
    transaction_date_to = context.get('transaction_date_to')
    transaction_type_filter = context.get('transaction_type')
    destination_filter = context.get('destination_filter')  # Changed to match
    created_by_filter = context.get('created_by')
    
    # Start with all transactions
    queryset = Transaction.objects.select_related('product', 'staff')
    
    # Apply date filter - timezone aware
    if transaction_date_from and transaction_date_to:
        try:
            from_date = datetime.strptime(transaction_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(transaction_date_to, '%Y-%m-%d').date()
            
            from_datetime = datetime.combine(from_date, datetime.min.time())
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__gte=from_datetime,
                created_date__lte=to_datetime
            )
            logger.info(f"Date filter applied: {transaction_date_from} to {transaction_date_to}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif transaction_date_from:
        try:
            from_date = datetime.strptime(transaction_date_from, '%Y-%m-%d').date()
            from_datetime = datetime.combine(from_date, datetime.min.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__gte=from_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif transaction_date_to:
        try:
            to_date = datetime.strptime(transaction_date_to, '%Y-%m-%d').date()
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__lte=to_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    
    # Apply transaction type filter
    if transaction_type_filter and transaction_type_filter != 'All':
        for key, value in TRANSACTION_TYPE_MAPPING.items():
            if value == transaction_type_filter:
                queryset = queryset.filter(transaction_type=key)
                break
    
    # Apply destination filter 
    if destination_filter and destination_filter != 'All':
        logger.info(f"Attempting to filter by destination: {destination_filter}")
        
        # Try to find the destination in the mapping
        destination_found = False
        for key, value in STORE_MAPPING.items():
            if value == destination_filter:
                queryset = queryset.filter(destination=key)
                destination_found = True
                logger.info(f"Destination filter applied: {destination_filter} -> {key}")
                break
        
        # If not found in mapping, try direct match
        if not destination_found:
            # Check if any destination in the database matches
            available_destinations = Transaction.objects.values_list('destination', flat=True).distinct()
            for dest in available_destinations:
                if dest and dest == destination_filter:
                    queryset = queryset.filter(destination=dest)
                    destination_found = True
                    logger.info(f"Destination filter applied (direct): {destination_filter}")
                    break
            
            # If still not found, try case-insensitive match
            if not destination_found:
                queryset = queryset.filter(destination__iexact=destination_filter)
                logger.info(f"Destination filter applied (case-insensitive): {destination_filter}")
    
    # Apply created_by filter
    if created_by_filter and created_by_filter != 'All':
        queryset = queryset.filter(staff__id=created_by_filter)
    
    # Order by created date (newest first)
    queryset = queryset.order_by('-created_date')
    
    logger.info(f"Found {queryset.count()} stock transactions")
    
    # Process each record
    for record in queryset:
        # Get destination store label
        destination_label = STORE_MAPPING.get(record.destination, record.destination or 'Unknown')
        
        # Get transaction type display name
        transaction_type_display = TRANSACTION_TYPE_MAPPING.get(record.transaction_type, record.transaction_type or 'Unknown')
        
        # Get product details
        product = record.product
        product_name = product.product_name if product else record.product_names or ''
        product_id = product.product_id if product else ''
        product_description = product.description if product else ''
        minimum_uom = record.minimum_UoM or (product.minimum_UoM if product else '')
        
        # Build row data
        row = {
            'product_name': product_name,
            'minimum_uom': minimum_uom,
            'product_id': product_id,
            'product_description': product_description,
            'price': float(record.price) if record.price else 0,
            'quantity': record.quantity or 0,
            'destination': destination_label,
            'created_by': record.staff.fullname if record.staff else '',
            'created_date': record.created_date,
            'transaction_type': transaction_type_display,
            'transaction_code': record.transaction_type,
            'record': record,
        }
        
        all_records.append(row)
    
    return all_records


def export_stock_analysis_to_excel(export_data, context):
    """Export Stock Analysis to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Stock Analysis"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Product Name', 35),
        ('Minimum UoM', 15),
        ('Product ID', 18),
        ('Description', 40),
        ('Price (₦)', 15),
        ('Quantity', 12),
        ('Destination', 20),
        ('Created By', 25),
        ('Created Date', 20),
        ('Transaction Type', 22),
    ]
    
    # Apply headers
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="6A1B9A", end_color="6A1B9A", fill_type="solid")  # Purple theme
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        row = [
            row_idx - 1,  # S/N
            row_data['product_name'],
            row_data['minimum_uom'],
            row_data['product_id'],
            row_data['product_description'],
            row_data['price'],
            row_data['quantity'],
            row_data['destination'],
            row_data['created_by'],
            row_data['created_date'].strftime('%d-%m-%Y %H:%M') if row_data['created_date'] else '',
            row_data['transaction_type'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (Price column - 6)
            if col == 6:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Color code based on transaction type
    for row_idx in range(2, len(export_data) + 2):
        transaction_type = export_data[row_idx - 2]['transaction_type']
        color = TRANSACTION_COLORS.get(transaction_type, 'FFFFFF')
        
        for col_idx in range(1, len(headers) + 1):
            cell = ws.cell(row=row_idx, column=col_idx)
            cell.fill = PatternFill(start_color=color, end_color=color, fill_type="solid")
    
    # Generate filename
    transaction_date_from = context.get('transaction_date_from', '')
    transaction_date_to = context.get('transaction_date_to', '')
    
    if transaction_date_from and transaction_date_to:
        filename = f"ISALU_HOSPITALS_stock_analysis_report_{transaction_date_from}_to_{transaction_date_to}.xlsx"
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        filename = f"ISALU_HOSPITALS_stock_analysis_report_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_stock_analysis_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")


#  VENDORS AND EXPENSE ANALYSIS REPORT 

@login_required(login_url='login')
@department_required('Reporting', 'Admin', 'CMD')
def vendors_expense_analysis_report(request):
    """Generate Vendors and Expense Analysis Report"""
    
    # Check if this is an export request
    is_export = request.GET.get('export', 'false') == 'true'
    
    # Get filter parameters
    vendor_name = request.GET.get('vendor_name', 'All')
    transaction_date_from = request.GET.get('transaction_date_from')
    transaction_date_to = request.GET.get('transaction_date_to')
    payment_date_from = request.GET.get('payment_date_from')
    payment_date_to = request.GET.get('payment_date_to')
    transaction_created_by = request.GET.get('transaction_created_by', 'All')
    payment_updated_by = request.GET.get('payment_updated_by', 'All')
    orientation = request.GET.get('orientation', 'Landscape')
    export_format = request.GET.get('format', 'excel')
    
    # Get filter options for dropdowns
    from inventory.models import VendorTransaction, Expense
    
    # Get unique vendor names
    vendor_names = Expense.objects.filter(
        vendor_name__isnull=False
    ).exclude(vendor_name='').values_list('vendor_name', flat=True).distinct().order_by('vendor_name')
    vendor_names = [v for v in vendor_names if v]
    
    # Get unique staff who created transactions (from Expense model)
    transaction_created_by_list = Expense.objects.filter(
        staff__isnull=False
    ).values_list('staff__id', 'staff__fullname').distinct().order_by('staff__fullname')
    transaction_created_by_list = [{'id': uid, 'fullname': fullname} for uid, fullname in transaction_created_by_list if fullname]

    # Get unique staff who updated payments (from VendorTransaction model)
    payment_updated_by_list = VendorTransaction.objects.filter(
        staff__isnull=False
    ).values_list('staff__id', 'staff__fullname').distinct().order_by('staff__fullname')
    payment_updated_by_list = [{'id': uid, 'fullname': fullname} for uid, fullname in payment_updated_by_list if fullname]

    context = {
        'vendor_name': vendor_name,
        'transaction_date_from': transaction_date_from,
        'transaction_date_to': transaction_date_to,
        'payment_date_from': payment_date_from,
        'payment_date_to': payment_date_to,
        'transaction_created_by': transaction_created_by,
        'payment_updated_by': payment_updated_by,
        'vendor_names': vendor_names,
        'transaction_created_by_list': transaction_created_by_list,
        'payment_updated_by_list': payment_updated_by_list,
        'orientation': orientation,
        'export_format': export_format,
    }
    
    # ONLY generate export if export parameter is explicitly set to 'true'
    if is_export:
        return generate_vendors_expense_export(request, context)
    
    # Otherwise, display the filter page
    return render(request, 'reporting/vendors_expense_analysis.html', context)


def generate_vendors_expense_export(request, context):
    """Generate Excel or PDF export for Vendors and Expense Analysis"""
    
    # Build the queryset with filters
    expense_data = get_vendors_expense_data(context)
    
    if not expense_data:
        return HttpResponse("No vendor transactions found for the selected filters. Please adjust your filters and try again.")
    
    # Generate Excel
    if context.get('export_format') == 'excel':
        return export_vendors_expense_to_excel(expense_data, context)
    
    # Generate PDF (will be implemented later)
    else:
        return export_vendors_expense_to_pdf(expense_data, context)


def get_vendors_expense_data(context):
    """Fetch vendor transactions with filters applied"""
    
    from inventory.models import VendorTransaction, Expense
    
    all_records = []
    
    # Get filter parameters
    vendor_name_filter = context.get('vendor_name')
    transaction_date_from = context.get('transaction_date_from')
    transaction_date_to = context.get('transaction_date_to')
    payment_date_from = context.get('payment_date_from')
    payment_date_to = context.get('payment_date_to')
    transaction_created_by_filter = context.get('transaction_created_by')
    payment_updated_by_filter = context.get('payment_updated_by')
    
    # Start with all vendor transactions
    queryset = VendorTransaction.objects.select_related('vendor', 'staff')
    
    # Apply vendor name filter
    if vendor_name_filter and vendor_name_filter != 'All':
        queryset = queryset.filter(vendor_name=vendor_name_filter)
    
    # Apply transaction date filter (from vendor.created_date) - FIXED with timezone awareness
    if transaction_date_from and transaction_date_to:
        try:
            from_date = datetime.strptime(transaction_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(transaction_date_to, '%Y-%m-%d').date()
            
            # Create timezone-aware datetime objects
            from_datetime = datetime.combine(from_date, datetime.min.time())
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
                to_datetime = timezone.make_aware(to_datetime)
            
            # Filter using the related vendor's created_date
            queryset = queryset.filter(
                vendor__created_date__isnull=False,
                vendor__created_date__gte=from_datetime,
                vendor__created_date__lte=to_datetime
            )
            logger.info(f"Transaction date filter applied: {transaction_date_from} to {transaction_date_to}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif transaction_date_from:
        try:
            from_date = datetime.strptime(transaction_date_from, '%Y-%m-%d').date()
            from_datetime = datetime.combine(from_date, datetime.min.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
            
            queryset = queryset.filter(
                vendor__created_date__isnull=False,
                vendor__created_date__gte=from_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif transaction_date_to:
        try:
            to_date = datetime.strptime(transaction_date_to, '%Y-%m-%d').date()
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                vendor__created_date__isnull=False,
                vendor__created_date__lte=to_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    
    # Apply payment updated date filter (from VendorTransaction.created_date) - with timezone awareness
    if payment_date_from and payment_date_to:
        try:
            from_date = datetime.strptime(payment_date_from, '%Y-%m-%d').date()
            to_date = datetime.strptime(payment_date_to, '%Y-%m-%d').date()
            
            from_datetime = datetime.combine(from_date, datetime.min.time())
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__gte=from_datetime,
                created_date__lte=to_datetime
            )
            logger.info(f"Payment date filter applied: {payment_date_from} to {payment_date_to}")
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif payment_date_from:
        try:
            from_date = datetime.strptime(payment_date_from, '%Y-%m-%d').date()
            from_datetime = datetime.combine(from_date, datetime.min.time())
            
            if timezone.is_aware(timezone.now()):
                from_datetime = timezone.make_aware(from_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__gte=from_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    elif payment_date_to:
        try:
            to_date = datetime.strptime(payment_date_to, '%Y-%m-%d').date()
            to_datetime = datetime.combine(to_date, datetime.max.time())
            
            if timezone.is_aware(timezone.now()):
                to_datetime = timezone.make_aware(to_datetime)
            
            queryset = queryset.filter(
                created_date__isnull=False,
                created_date__lte=to_datetime
            )
        except ValueError as e:
            logger.error(f"Date parsing error: {e}")
    
    # Apply transaction created by filter
    if transaction_created_by_filter and transaction_created_by_filter != 'All':
        queryset = queryset.filter(vendor__staff__id=transaction_created_by_filter)
    
    # Apply payment updated by filter
    if payment_updated_by_filter and payment_updated_by_filter != 'All':
        queryset = queryset.filter(staff__id=payment_updated_by_filter)
    
    # Order by expense_id and created_date
    queryset = queryset.order_by('expense_id', '-created_date')
    
    logger.info(f"Found {queryset.count()} vendor transactions")
    
    # Get all unique expense_ids for color grouping
    expense_ids = list(queryset.values_list('expense_id', flat=True).distinct())
    
    # Process each record
    for record in queryset:
        vendor = record.vendor
        
        # Get vendor details
        vendor_name = vendor.vendor_name if vendor else record.vendor_name or ''
        product_name = vendor.product_name if vendor else record.product_name or ''
        product_id = vendor.product_id if vendor else ''
        minimum_uom = vendor.minimum_UoM if vendor else ''
        quantity = vendor.quantity if vendor else 0
        total_cost = float(vendor.total_cost) if vendor and vendor.total_cost else float(record.total_cost or 0)
        
        # Payment from VendorTransaction (updated payment)
        updated_payment = float(record.payment) if record.payment else 0
        
        # Total payment from Vendor (original payment)
        total_payment = float(vendor.payment) if vendor and vendor.payment else 0
        
        # Dues from Vendor
        dues = float(vendor.due) if vendor and vendor.due else 0
        
        # Transaction date from Vendor
        transaction_date = vendor.created_date if vendor else None
        
        # Payment updated date from VendorTransaction
        payment_updated_date = record.created_date
        
        # Transaction created by (staff from Vendor)
        transaction_created_by = vendor.staff.fullname if vendor and vendor.staff else ''
        
        # Payment updated by (staff from VendorTransaction)
        payment_updated_by = record.staff.fullname if record.staff else ''
        
        # Build row data
        row = {
            'vendor_name': vendor_name,
            'product_name': product_name,
            'product_id': product_id,
            'minimum_uom': minimum_uom,
            'quantity': quantity,
            'total_cost': total_cost,
            'updated_payment': updated_payment,
            'total_payment': total_payment,
            'dues': dues,
            'transaction_date': transaction_date,
            'payment_updated_date': payment_updated_date,
            'transaction_created_by': transaction_created_by,
            'payment_updated_by': payment_updated_by,
            'expense_id': record.expense_id,
            'record': record,
        }
        
        all_records.append(row)
    
    return all_records


def export_vendors_expense_to_excel(export_data, context):
    """Export Vendors and Expense Analysis to MS Excel"""
    
    if not export_data:
        return HttpResponse("No data found for the selected filters. Please adjust your filters and try again.")
    
    wb = Workbook()
    ws = wb.active
    ws.title = "Vendors & Expense Analysis"
    
    # Define headers and their column widths
    headers = [
        ('S/N', 8),
        ('Vendor Name', 30),
        ('Product Name', 35),
        ('Product ID', 18),
        ('Minimum UoM', 15),
        ('Quantity', 12),
        ('Total Cost (₦)', 18),
        ('Updated Payment (₦)', 20),
        ('Total Payment (₦)', 18),
        ('Accounts Payable (₦)', 25),
        ('Transaction Date', 20),
        ('Payment Updated Date', 20),
        ('Transaction Created By', 25),
        ('Payment Updated By', 25),
    ]
    
    # Apply headers - using blue/teal theme
    for col, (header, width) in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col, value=header)
        cell.font = Font(bold=True, size=11)
        cell.fill = PatternFill(start_color="00695C", end_color="00695C", fill_type="solid")
        cell.font = Font(bold=True, color="FFFFFF", size=11)
        cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.column_dimensions[get_column_letter(col)].width = width
    
    # Generating a color palette for expense_id grouping
    # Using a set of distinct colors for different expense_ids
    expense_ids = list(set([row['expense_id'] for row in export_data]))
    color_palette = [
        'FFF3E0', 'E8F5E9', 'E3F2FD', 'FCE4EC', 'F3E5F5', 
        'E0F7FA', 'FFF8E1', 'F1F8E9', 'E8EAF6', 'FBE9E7',
        'E0F2F1', 'FFFDE7', 'F9FBE7', 'F3E5F5', 'E8F5E9',
        'FFF3E0', 'E3F2FD', 'FCE4EC', 'E0F7FA', 'FFF8E1'
    ]
    
    expense_color_map = {}
    for idx, expense_id in enumerate(expense_ids):
        expense_color_map[expense_id] = color_palette[idx % len(color_palette)]
    
    # Apply data
    for row_idx, row_data in enumerate(export_data, 2):
        expense_id = row_data['expense_id']
        row_color = expense_color_map.get(expense_id, 'FFFFFF')
        
        row = [
            row_idx - 1,  # S/N
            row_data['vendor_name'],
            row_data['product_name'],
            row_data['product_id'],
            row_data['minimum_uom'],
            row_data['quantity'],
            row_data['total_cost'],
            row_data['updated_payment'],
            row_data['total_payment'],
            row_data['dues'],
            row_data['transaction_date'].strftime('%d-%m-%Y %H:%M') if row_data['transaction_date'] else '',
            row_data['payment_updated_date'].strftime('%d-%m-%Y %H:%M') if row_data['payment_updated_date'] else '',
            row_data['transaction_created_by'],
            row_data['payment_updated_by'],
        ]
        
        for col, value in enumerate(row, 1):
            cell = ws.cell(row=row_idx, column=col, value=value)
            
            # Format monetary values (columns 7, 8, 9, 10)
            if col in [7, 8, 9, 10]:
                if isinstance(value, (int, float)):
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal='right', vertical='center')
                else:
                    cell.alignment = Alignment(horizontal='right', vertical='center')
            else:
                cell.alignment = Alignment(horizontal='left' if isinstance(value, str) else 'right', vertical='center')
            
            # Apply background color for grouping
            cell.fill = PatternFill(start_color=row_color, end_color=row_color, fill_type="solid")
    
    # Add borders to all cells
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    
    for row in ws.iter_rows(min_row=1, max_row=len(export_data)+1, max_col=len(headers)):
        for cell in row:
            cell.border = thin_border
    
    # Freeze the header row
    ws.freeze_panes = 'A2'
    
    # Generate filename
    transaction_date_from = context.get('transaction_date_from', '')
    transaction_date_to = context.get('transaction_date_to', '')
    
    if transaction_date_from and transaction_date_to:
        filename = f"ISALU_HOSPITALS_vendors_and_expense_analysis_report_{transaction_date_from}_to_{transaction_date_to}.xlsx"
    else:
        today = timezone.now().date().strftime('%Y-%m-%d')
        filename = f"ISALU_HOSPITALS_vendors_and_expense_analysis_report_{today}.xlsx"
    
    # Create response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    wb.save(response)
    return response


def export_vendors_expense_to_pdf(export_data, context):
    """Export data to PDF (placeholder)"""
    return HttpResponse("PDF export coming soon...")