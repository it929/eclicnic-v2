import logging

from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, permissions
from django.shortcuts import get_object_or_404
from django.utils import timezone
from datetime import datetime, date, timedelta
from decimal import Decimal

from patients.models import PatientProfile, PatientAppointment
from queue_operations.models import ImmunizationRecord, PatientEncounter
from Billings.models import Invoice, TransactionUpdate
from users.models import User
from .vaccine_pricing import get_patient_vaccine_tariffs, get_general_vaccine_tariffs, match_catalog_codes, resolve_tariff_for_patient

logger = logging.getLogger(__name__)

# Standard WHO / National Routine Childhood & Adult Immunization Schedule
IMMUNIZATION_SCHEDULE = [
    {
        'stage_id': 'birth',
        'title': 'At Birth',
        'target_group': 'Newborns (0 - 2 Weeks)',
        'min_age_weeks': 0,
        'max_age_weeks': 2,
        'vaccines': [
            {
                'name': 'BCG (Bacille Calmette-Guérin)',
                'code': 'BCG',
                'target_disease': 'Tuberculosis (TB)',
                'default_dose': 'Birth Dose',
                'default_route': 'Intradermal (ID)',
                'default_site': 'Left Upper Arm (Deltoid)',
                'dosage': '0.05 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'OPV 0 (Oral Polio Vaccine 0)',
                'code': 'OPV-0',
                'target_disease': 'Poliomyelitis',
                'default_dose': 'Birth Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '2 drops',
                'default_fee': 0.0,
            },
            {
                'name': 'Hepatitis B 0 (HepB Birth Dose)',
                'code': 'HEPB-0',
                'target_disease': 'Hepatitis B Virus (Mother-to-child transmission)',
                'default_dose': 'Birth Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '6weeks',
        'title': '6 Weeks',
        'target_group': 'Infants (6 Weeks / 1.5 Months)',
        'min_age_weeks': 6,
        'max_age_weeks': 9,
        'vaccines': [
            {
                'name': 'Pentavalent 1 (DTP-HepB-Hib 1)',
                'code': 'PENTA-1',
                'target_disease': 'Diphtheria, Tetanus, Pertussis, Hepatitis B, Haemophilus influenzae b',
                'default_dose': '1st Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'OPV 1 (Oral Polio Vaccine 1)',
                'code': 'OPV-1',
                'target_disease': 'Poliomyelitis',
                'default_dose': '1st Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '2 drops',
                'default_fee': 0.0,
            },
            {
                'name': 'PCV 1 (Pneumococcal Conjugate 1)',
                'code': 'PCV-1',
                'target_disease': 'Pneumococcal Pneumonia, Meningitis & Sepsis',
                'default_dose': '1st Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Rotavirus 1 (Rota 1)',
                'code': 'ROTA-1',
                'target_disease': 'Severe Rotavirus Diarrheal Dehydration',
                'default_dose': '1st Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '1.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '10weeks',
        'title': '10 Weeks',
        'target_group': 'Infants (10 Weeks / 2.5 Months)',
        'min_age_weeks': 10,
        'max_age_weeks': 13,
        'vaccines': [
            {
                'name': 'Pentavalent 2 (DTP-HepB-Hib 2)',
                'code': 'PENTA-2',
                'target_disease': 'Diphtheria, Tetanus, Pertussis, Hepatitis B, Hib',
                'default_dose': '2nd Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'OPV 2 (Oral Polio Vaccine 2)',
                'code': 'OPV-2',
                'target_disease': 'Poliomyelitis',
                'default_dose': '2nd Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '2 drops',
                'default_fee': 0.0,
            },
            {
                'name': 'PCV 2 (Pneumococcal Conjugate 2)',
                'code': 'PCV-2',
                'target_disease': 'Pneumococcal Pneumonia & Meningitis',
                'default_dose': '2nd Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Rotavirus 2 (Rota 2)',
                'code': 'ROTA-2',
                'target_disease': 'Rotavirus Diarrheal Illness',
                'default_dose': '2nd Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '1.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '14weeks',
        'title': '14 Weeks',
        'target_group': 'Infants (14 Weeks / 3.5 Months)',
        'min_age_weeks': 14,
        'max_age_weeks': 23,
        'vaccines': [
            {
                'name': 'Pentavalent 3 (DTP-HepB-Hib 3)',
                'code': 'PENTA-3',
                'target_disease': 'Diphtheria, Tetanus, Pertussis, Hepatitis B, Hib',
                'default_dose': '3rd Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'OPV 3 (Oral Polio Vaccine 3)',
                'code': 'OPV-3',
                'target_disease': 'Poliomyelitis',
                'default_dose': '3rd Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '2 drops',
                'default_fee': 0.0,
            },
            {
                'name': 'PCV 3 (Pneumococcal Conjugate 3)',
                'code': 'PCV-3',
                'target_disease': 'Pneumococcal Disease',
                'default_dose': '3rd Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Anterolateral Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'IPV 1 (Inactivated Polio Vaccine 1)',
                'code': 'IPV-1',
                'target_disease': 'Polio Virus (Injectable Protection)',
                'default_dose': '1st Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Deltoid / Thigh',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '6months',
        'title': '6 Months',
        'target_group': 'Infants (6 Months)',
        'min_age_weeks': 24,
        'max_age_weeks': 35,
        'vaccines': [
            {
                'name': 'Vitamin A (Dose 1)',
                'code': 'VITA-1',
                'target_disease': 'Vitamin A Deficiency & Immune Fortification',
                'default_dose': '1st Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '100,000 IU (Blue Capsule)',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '9months',
        'title': '9 Months',
        'target_group': 'Infants (9 Months)',
        'min_age_weeks': 36,
        'max_age_weeks': 47,
        'vaccines': [
            {
                'name': 'Measles 1 (MCV 1)',
                'code': 'MEASLES-1',
                'target_disease': 'Measles Virus Infection',
                'default_dose': '1st Dose',
                'default_route': 'Subcutaneous (SC)',
                'default_site': 'Left Upper Arm (Deltoid)',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Yellow Fever Vaccine',
                'code': 'YF',
                'target_disease': 'Yellow Fever Flavivirus',
                'default_dose': 'Primary Dose',
                'default_route': 'Subcutaneous (SC)',
                'default_site': 'Right Upper Arm (Deltoid)',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Men A (Meningococcal A Conjugate)',
                'code': 'MEN-A',
                'target_disease': 'Meningococcal Meningitis Serogroup A',
                'default_dose': 'Primary Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Upper Arm (Deltoid)',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '12months',
        'title': '12 Months',
        'target_group': 'Toddlers (12 Months / 1 Year)',
        'min_age_weeks': 48,
        'max_age_weeks': 59,
        'vaccines': [
            {
                'name': 'Vitamin A (Dose 2)',
                'code': 'VITA-2',
                'target_disease': 'Vitamin A Fortification',
                'default_dose': '2nd Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '200,000 IU (Red Capsule)',
                'default_fee': 0.0,
            },
            {
                'name': 'PCV Booster (Dose 4)',
                'code': 'PCV-BOOST',
                'target_disease': 'Pneumococcal Long-term Immunity',
                'default_dose': 'Booster',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Deltoid',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': '15_18months',
        'title': '15 - 18 Months',
        'target_group': 'Toddlers (15 - 18 Months)',
        'min_age_weeks': 60,
        'max_age_weeks': 104,
        'vaccines': [
            {
                'name': 'Measles 2 (MCV 2) / MMR',
                'code': 'MEASLES-2',
                'target_disease': 'Measles, Mumps & Rubella Reinforcement',
                'default_dose': '2nd Dose',
                'default_route': 'Subcutaneous (SC)',
                'default_site': 'Left Upper Arm (Deltoid)',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Vitamin A (Dose 3)',
                'code': 'VITA-3',
                'target_disease': 'Vitamin A Fortification',
                'default_dose': '3rd Dose',
                'default_route': 'Oral',
                'default_site': 'Oral',
                'dosage': '200,000 IU (Red Capsule)',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': 'adolescent',
        'title': 'Adolescent & Special',
        'target_group': 'Adolescents (9 - 14 Years) & Special Risk',
        'min_age_weeks': 468,
        'max_age_weeks': 1040,
        'vaccines': [
            {
                'name': 'HPV Vaccine (Human Papillomavirus)',
                'code': 'HPV',
                'target_disease': 'Cervical Cancer & HPV Infection Prevention',
                'default_dose': '1st Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left Upper Arm (Deltoid)',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Typhoid Conjugate Vaccine (TCV)',
                'code': 'TCV',
                'target_disease': 'Salmonella Typhi (Enteric Fever)',
                'default_dose': 'Primary Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Deltoid',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Meningitis ACWY',
                'code': 'MEN-ACWY',
                'target_disease': 'Quadrivalent Meningococcal Meningitis',
                'default_dose': 'Primary Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Deltoid',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
        ],
    },
    {
        'stage_id': 'maternal_adult',
        'title': 'Maternal & Adult Vaccines',
        'target_group': 'Maternal (Antenatal Care), Adults & Healthcare Staff',
        'min_age_weeks': 780,
        'max_age_weeks': 5200,
        'vaccines': [
            {
                'name': 'Tetanus Toxoid (TT / Td)',
                'code': 'TT',
                'target_disease': 'Maternal & Neonatal Tetanus',
                'default_dose': '1st Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left Upper Arm (Deltoid)',
                'dosage': '0.5 ml',
                'default_fee': 0.0,
            },
            {
                'name': 'Hepatitis B Adult Recombinant',
                'code': 'HEPB-ADULT',
                'target_disease': 'Hepatitis B Virus (Adult Transmission)',
                'default_dose': '1st Dose (0, 1, 6 Months)',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Right Deltoid',
                'dosage': '1.0 ml',
                'default_fee': 3500.0,
            },
            {
                'name': 'Influenza (Flu) Annual Vaccine',
                'code': 'FLU',
                'target_disease': 'Seasonal Influenza A & B',
                'default_dose': 'Annual Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left Deltoid',
                'dosage': '0.5 ml',
                'default_fee': 5000.0,
            },
            {
                'name': 'COVID-19 Vaccine & Booster',
                'code': 'COVID-19',
                'target_disease': 'SARS-CoV-2 Infection',
                'default_dose': 'Booster Dose',
                'default_route': 'Intramuscular (IM)',
                'default_site': 'Left/Right Deltoid',
                'dosage': '0.3 ml',
                'default_fee': 0.0,
            },
        ],
    },
]

STANDARD_ROUTES = [
    'Intramuscular (IM)',
    'Oral',
    'Subcutaneous (SC)',
    'Intradermal (ID)',
]

STANDARD_SITES = [
    'Left Anterolateral Thigh',
    'Right Anterolateral Thigh',
    'Left Upper Arm (Deltoid)',
    'Right Upper Arm (Deltoid)',
    'Oral',
    'Right Buttock / Gluteal',
    'Left Buttock / Gluteal',
]

STANDARD_DOSES = [
    'Birth Dose',
    '1st Dose',
    '2nd Dose',
    '3rd Dose',
    '4th Dose',
    '5th Dose',
    'Booster 1',
    'Booster 2',
    'Annual Booster',
]


def calculate_patient_age_details(patient):
    """Calculates age in days, weeks, months, years for precise clinical immunization schedule matching."""
    today = date.today()
    dob = None
    if patient.dob:
        dob = patient.dob
    elif patient.age:
        # Approximate birth date from age in years
        try:
            years = int(patient.age)
            dob = today.replace(year=today.year - years)
        except Exception:
            pass

    if not dob:
        return {
            'days': None,
            'weeks': None,
            'months': None,
            'years': patient.age or 0,
            'display': f"{patient.age or 0} yrs",
            'is_infant': False,
            'is_child': (patient.age or 0) < 12,
        }

    total_days = (today - dob).days
    total_weeks = total_days // 7
    total_months = total_days // 30
    total_years = total_days // 365

    if total_days < 30:
        display = f"{total_days} day{'s' if total_days != 1 else ''}"
    elif total_weeks < 16:
        display = f"{total_weeks} week{'s' if total_weeks != 1 else ''} ({total_days} days)"
    elif total_months < 24:
        display = f"{total_months} month{'s' if total_months != 1 else ''}"
    else:
        display = f"{total_years} year{'s' if total_years != 1 else ''}"

    return {
        'days': total_days,
        'weeks': total_weeks,
        'months': total_months,
        'years': total_years,
        'display': display,
        'dob': dob.isoformat() if hasattr(dob, 'isoformat') else str(dob),
        'is_infant': total_weeks <= 52,
        'is_child': total_years < 12,
    }


def get_immunization_clearance(records):
    """
    A billable vaccine is only complete once billing has cleared it:
      - cash / pay-from-purse -> its patient invoice is paid (Invoice.completed == 1)
      - HMO covered           -> its HMO claim is approved   (Invoice.completed == 1)
    Free EPI vaccines are cleared immediately.
    After clearance the nurse confirms the injection with their PIN (administration_confirmed).
    Returns {record_id: {'status', 'label', 'cleared', 'administered', 'invoice_number'}}.
    status: 'cleared' (given) | 'ready_to_administer' | 'awaiting_payment' | 'awaiting_hmo_approval'
    """
    recs = list(records)
    billed_ids = [r.id for r in recs if r.billing_status == 'billed']
    invoices = {}
    if billed_ids:
        for inv in Invoice.objects.filter(
            original_source_model='ImmunizationRecord', original_source_id__in=billed_ids
        ).order_by('id'):
            invoices[inv.original_source_id] = inv  # latest invoice line wins

    out = {}
    for r in recs:
        if r.billing_status == 'not_billable' or not r.is_billable:
            out[r.id] = {'status': 'cleared', 'label': 'Free EPI', 'cleared': True, 'administered': True, 'invoice_number': None}
            continue
        inv = invoices.get(r.id) if r.billing_status == 'billed' else None
        is_claim = (inv is not None and str(inv.invoice_number or '').upper().startswith('CLM')) or (
            inv is None and r.payment_mode == 'covered'
        )
        if inv is not None and inv.completed == 1:
            paid_label = 'HMO approved' if is_claim else 'Paid'
            given = bool(getattr(r, 'administration_confirmed', False))
            out[r.id] = {
                'status': 'cleared' if given else 'ready_to_administer',
                'label': paid_label if given else f'{paid_label} - ready to give',
                'cleared': True,
                'administered': given,
                'invoice_number': inv.invoice_number,
            }
        elif is_claim:
            out[r.id] = {
                'status': 'awaiting_hmo_approval',
                'label': 'Awaiting HMO approval',
                'cleared': False,
                'administered': False,
                'invoice_number': inv.invoice_number if inv else None,
            }
        else:
            out[r.id] = {
                'status': 'awaiting_payment',
                'label': 'Awaiting payment',
                'cleared': False,
                'administered': False,
                'invoice_number': inv.invoice_number if inv else None,
            }
    return out


def verify_staff_pin(request, data, action='authorize this immunization'):
    """Returns (staff_user, None) when the PIN is valid, else (None, error Response)."""
    pin_str = str(data.get('pin') or data.get('security_pin') or '').strip()
    if not pin_str:
        return None, Response({'error': f'Enter your security PIN to {action}.'}, status=status.HTTP_400_BAD_REQUEST)
    staff = request.user if request.user and request.user.is_authenticated else None
    if staff is None and data.get('staff_id'):
        staff = User.objects.filter(id=data.get('staff_id'), is_active=True).first()
    if staff is None:
        return None, Response({'error': f'Please log in as a staff member to {action}.'}, status=status.HTTP_401_UNAUTHORIZED)
    if not staff.has_pin:
        return None, Response(
            {'error': f'{staff.fullname or staff.username} has no security PIN set. Set your PIN in Profile Settings first.'},
            status=status.HTTP_400_BAD_REQUEST,
        )
    if not staff.check_pin(pin_str):
        return None, Response({'error': 'Incorrect security PIN. Authorization denied.'}, status=status.HTTP_403_FORBIDDEN)
    return staff, None


def compute_next_due_vaccines(patient, age_info=None):
    """
    Works out which routine vaccines the patient still needs, with due dates from the DOB.
    Returns {'overdue': [...], 'next_milestone': {...} | None, 'next_due_date': 'YYYY-MM-DD' | None}.
    Only childhood milestones are considered until the patient is old enough for later ones,
    so a newborn is not shown adolescent / adult vaccines.
    """
    age_info = age_info or calculate_patient_age_details(patient)
    weeks = age_info.get('weeks')
    dob = None
    if age_info.get('dob'):
        try:
            dob = datetime.strptime(age_info['dob'][:10], '%Y-%m-%d').date()
        except Exception:
            dob = None

    given_names, given_codes = set(), set()
    for name, code in ImmunizationRecord.objects.filter(patient=patient).values_list('vaccine_name', 'vaccine_code'):
        given_names.add((name or '').strip().lower())
        if code:
            given_codes.add(code.strip().upper())

    def is_given(v):
        code = (v.get('code') or '').strip().upper()
        return (v['name'].strip().lower() in given_names) or (code and code in given_codes)

    today = date.today()
    overdue, next_milestone = [], None
    for milestone in IMMUNIZATION_SCHEDULE:
        pending = [v for v in milestone['vaccines'] if not is_given(v)]
        if not pending:
            continue
        due = dob + timedelta(weeks=milestone['min_age_weeks']) if dob else None
        entry = {
            'stage': milestone['title'],
            'due_date': due.isoformat() if due else None,
            'vaccines': [{'name': v['name'], 'code': v.get('code')} for v in pending],
        }
        # Milestone window already passed -> overdue
        if weeks is not None and weeks > milestone['max_age_weeks']:
            # Childhood catch-up only applies to under-5s; adolescent/adult stages are optional
            if milestone['min_age_weeks'] < 400 and weeks <= 260:
                overdue.append(entry)
            continue
        # Current or future milestone -> the next one to come for
        if next_milestone is None:
            if due and due < today:
                entry['due_date'] = today.isoformat()
            next_milestone = entry
            break

    next_due_date = None
    if overdue:
        next_due_date = today.isoformat()
    elif next_milestone:
        next_due_date = next_milestone['due_date']
    return {'overdue': overdue, 'next_milestone': next_milestone, 'next_due_date': next_due_date}


def format_next_due_text(next_due):
    lines = []
    for o in next_due.get('overdue', []):
        lines.append(f"- OVERDUE ({o['stage']}): " + ', '.join(v['name'] for v in o['vaccines']))
    nm = next_due.get('next_milestone')
    if nm:
        when = ''
        if nm.get('due_date'):
            try:
                when = datetime.strptime(nm['due_date'], '%Y-%m-%d').strftime('%d-%b-%Y')
            except Exception:
                when = nm['due_date']
        lines.append(f"- {nm['stage']}{f' (due {when})' if when else ''}: " + ', '.join(v['name'] for v in nm['vaccines']))
    return '\n'.join(lines)


class ImmunizationCatalogView(APIView):
    """Returns the National / WHO Routine Childhood & Adult Immunization Schedule, routes, and sites."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        return Response({
            'schedule': IMMUNIZATION_SCHEDULE,
            'routes': STANDARD_ROUTES,
            'sites': STANDARD_SITES,
            'doses': STANDARD_DOSES,
        })


class PatientImmunizationListView(APIView):
    """Returns a patient's complete immunization card, historical vaccines, and due status."""
    permission_classes = [permissions.AllowAny]

    def get(self, request, patient_id):
        patient = get_object_or_404(PatientProfile, id=patient_id)
        age_info = calculate_patient_age_details(patient)

        records = list(ImmunizationRecord.objects.filter(patient=patient).select_related('administered_by', 'appointment'))
        clearance = get_immunization_clearance(records)
        records_data = []
        given_vaccine_names = set()   # cleared (paid / HMO approved / free) -> complete
        given_codes = set()

        for r in records:
            clr = clearance.get(r.id, {'status': 'cleared', 'label': '', 'cleared': True, 'administered': True, 'invoice_number': None})
            if clr['administered']:
                given_vaccine_names.add(r.vaccine_name.strip().lower())
                if r.vaccine_code:
                    given_codes.add(r.vaccine_code.strip().upper())

            records_data.append({
                'id': r.id,
                'vaccine_name': r.vaccine_name,
                'vaccine_code': r.vaccine_code,
                'dose_stage': r.dose_stage,
                'schedule_stage': r.schedule_stage,
                'route': r.route,
                'site': r.site,
                'batch_number': r.batch_number,
                'expiry_date': r.expiry_date.isoformat() if r.expiry_date else None,
                'manufacturer': r.manufacturer,
                'administered_date': r.administered_date.isoformat() if r.administered_date else None,
                'administered_time': r.administered_time.strftime('%H:%M') if r.administered_time else None,
                'administered_by_name': r.administered_by_name or (r.administered_by.fullname if r.administered_by else 'Nurse / Healthcare Officer'),
                'next_due_date': r.next_due_date.isoformat() if r.next_due_date else None,
                'fee': float(r.fee or 0),
                'is_billable': r.is_billable,
                'payment_mode': r.payment_mode,
                'billing_status': r.billing_status,
                'clearance_status': clr['status'],
                'clearance_label': clr['label'],
                'is_cleared': clr['cleared'],
                'is_administered': clr['administered'],
                'authorized_by_name': r.authorized_by_name or r.administered_by_name,
                'confirmed_at': r.confirmed_at.isoformat() if r.confirmed_at else None,
                'invoice_number': clr['invoice_number'],
                'tariff_name': r.tariff_name,
                'price_source': r.price_source,
                'notes': r.notes,
                'aefi_reported': r.aefi_reported,
                'aefi_notes': r.aefi_notes,
                'created_at': r.created_at.isoformat() if r.created_at else None,
            })

        # Match with standard schedule milestones to detect Due / Completed / Pending
        schedule_status = []
        weeks = age_info.get('weeks')

        for milestone in IMMUNIZATION_SCHEDULE:
            stage_status = {
                'stage_id': milestone['stage_id'],
                'title': milestone['title'],
                'target_group': milestone['target_group'],
                'min_age_weeks': milestone['min_age_weeks'],
                'max_age_weeks': milestone['max_age_weeks'],
                'vaccines': [],
                'all_completed': True,
                'awaiting_clearance': 0,
                'ready_to_administer': 0,
                'is_current_due': False,
                'is_overdue': False,
            }

            if weeks is not None:
                if milestone['min_age_weeks'] <= weeks <= milestone['max_age_weeks']:
                    stage_status['is_current_due'] = True
                elif weeks > milestone['max_age_weeks']:
                    stage_status['is_overdue'] = True

            for v in milestone['vaccines']:
                v_name = v['name'].strip().lower()
                v_code = (v.get('code') or '').strip().upper()
                is_given = (v_name in given_vaccine_names) or (v_code and v_code in given_codes)

                matching_record = next(
                    (rec for rec in records_data if (v_name in rec['vaccine_name'].lower()) or (v_code and rec.get('vaccine_code') == v_code)),
                    None
                )

                if not is_given:
                    stage_status['all_completed'] = False

                # Authorized but not yet paid / HMO-approved -> not complete yet
                awaiting = None
                if not is_given and matching_record and not matching_record.get('is_administered', True):
                    awaiting = matching_record.get('clearance_status')
                    if awaiting == 'ready_to_administer':
                        stage_status['ready_to_administer'] += 1
                    else:
                        stage_status['awaiting_clearance'] += 1

                if is_given:
                    v_status = 'Given'
                elif awaiting == 'awaiting_hmo_approval':
                    v_status = 'Awaiting HMO Approval'
                elif awaiting == 'awaiting_payment':
                    v_status = 'Awaiting Payment'
                elif awaiting == 'ready_to_administer':
                    v_status = 'Ready to Administer'
                else:
                    v_status = 'Due' if stage_status['is_current_due'] else ('Overdue' if stage_status['is_overdue'] else 'Upcoming')

                stage_status['vaccines'].append({
                    'name': v['name'],
                    'code': v.get('code'),
                    'target_disease': v['target_disease'],
                    'default_dose': v['default_dose'],
                    'default_route': v['default_route'],
                    'default_site': v['default_site'],
                    'dosage': v.get('dosage'),
                    'default_fee': v.get('default_fee', 0.0),
                    'status': v_status,
                    'record': matching_record,
                })

            schedule_status.append(stage_status)

        patient_name = f"{patient.surname or ''} {patient.first_name or ''} {patient.other_name or ''}".strip() or patient.patient_name or 'Patient'
        sponsor_name = getattr(patient.sponsor, 'name', None) if getattr(patient, 'sponsor', None) else None
        plan_name = getattr(patient.plan, 'plan', None) if getattr(patient, 'plan', None) else None

        return Response({
            'patient': {
                'id': patient.id,
                'full_name': patient_name,
                'hospital_number': patient.hospital_number or 'N/A',
                'gender': patient.gender or 'N/A',
                'age_info': age_info,
                'phone_number': patient.phone_number or '',
                'category_name': getattr(patient.category, 'category', None) if getattr(patient, 'category', None) else 'Private',
                'sponsor_name': sponsor_name,
                'plan_name': plan_name,
                'blood_group': patient.blood_group if hasattr(patient, 'blood_group') else '',
                'genotype': patient.genotype if hasattr(patient, 'genotype') else '',
            },
            'records': records_data,
            'total_administered': len([x for x in records_data if x['is_administered']]),
            'total_awaiting_clearance': len([x for x in records_data if not x['is_cleared']]),
            'total_ready_to_administer': len([x for x in records_data if x['is_cleared'] and not x['is_administered']]),
            'schedule_status': schedule_status,
            'next_due': compute_next_due_vaccines(patient, age_info),
        })


class PatientVaccineTariffView(APIView):
    """
    Vaccines priced for this patient's sponsor + coverage plan.
    HMO patients: plan tariff, then sponsor-wide tariff only (no General fallback; the General
    list is returned separately for vaccines the plan does not cover).
    Other patients: plan, sponsor-wide, then General prices. Each item says which source was used.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, patient_id):
        patient = get_object_or_404(PatientProfile.objects.select_related('sponsor', 'sponsor__category', 'plan', 'plan__sponsor', 'category'), id=patient_id)
        ctx, vaccines = get_patient_vaccine_tariffs(patient)
        general_vaccines = get_general_vaccine_tariffs()
        counts = {'plan': 0, 'sponsor': 0, 'general': 0}
        for v in vaccines:
            counts[v['source']] += 1
        # Size of the General (pay-from-purse) list, offered separately to HMO patients
        counts['general_available'] = len(general_vaccines)
        return Response({
            'pricing': {
                'sponsor_id': ctx['sponsor_id'],
                'sponsor_name': ctx['sponsor_name'],
                'sponsor_code': ctx['sponsor_code'],
                'plan_id': ctx['plan_id'],
                'plan_name': ctx['plan_name'],
                'category': ctx['category'],
                'is_hmo': ctx['is_hmo'],
                'counts': counts,
            },
            'vaccines': vaccines,
            'catalog_matches': match_catalog_codes(IMMUNIZATION_SCHEDULE, vaccines),
            # General (self-pay) list for vaccines the HMO / sponsor plan does not cover
            'general_vaccines': general_vaccines,
            'general_catalog_matches': match_catalog_codes(IMMUNIZATION_SCHEDULE, general_vaccines),
        })


class AdministerImmunizationBatchView(APIView):
    """
    Administers and records one or more vaccines for a patient.
    - Saves ImmunizationRecord for each vaccine with batch/lot numbers, site & route.
    - Automatically creates a permanent PatientEncounter on the medical case note timeline.
    - If fee > 0, routes to Billings TransactionUpdate for the cashier/HMO desk.
    - If next_appointment_date is passed, schedules the follow-up appointment.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data
        patient_id = data.get('patient_id')
        if not patient_id:
            return Response({'error': 'Patient ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        patient = get_object_or_404(PatientProfile, id=patient_id)
        appointment_id = data.get('appointment_id')
        appointment = None
        if appointment_id:
            try:
                appointment = PatientAppointment.objects.get(id=appointment_id)
            except Exception:
                pass

        vaccines = data.get('vaccines', [])
        if not vaccines or not isinstance(vaccines, list):
            return Response({'error': 'At least one vaccine must be specified in the batch'}, status=status.HTTP_400_BAD_REQUEST)

        # ---- Staff PIN authorization: records exactly who authorized the vaccines ----
        authorizing_staff, pin_error = verify_staff_pin(request, data)
        if pin_error is not None:
            return pin_error

        current_user = authorizing_staff
        staff_name = (getattr(current_user, 'fullname', None) or '').strip() or current_user.username

        administered_date_str = data.get('administered_date')
        if administered_date_str:
            try:
                admin_date = datetime.strptime(administered_date_str, '%Y-%m-%d').date()
            except Exception:
                admin_date = date.today()
        else:
            admin_date = date.today()

        next_due_date_str = data.get('next_appointment_date')
        next_due_date = None
        if next_due_date_str:
            try:
                next_due_date = datetime.strptime(next_due_date_str, '%Y-%m-%d').date()
            except Exception:
                pass

        saved_records = []
        total_billed = Decimal('0.00')
        vaccine_names_summary = []
        price_cache = {}

        # Vaccines already authorized for this patient but not yet paid / HMO-approved
        open_recs = [
            r for r in ImmunizationRecord.objects.filter(patient=patient, billing_status__in=['pending', 'billed'])
        ]
        open_clr = get_immunization_clearance(open_recs)
        awaiting_names, awaiting_codes = {}, {}
        for r in open_recs:
            c = open_clr.get(r.id)
            if c and not c['administered']:
                awaiting_names[r.vaccine_name.strip().lower()] = c['label']
                if r.vaccine_code:
                    awaiting_codes[r.vaccine_code.strip().upper()] = c['label']

        # ---- Validate the whole batch first, so a bad item never leaves half the visit saved ----
        for v in vaccines:
            v_name = (v.get('vaccine_name') or '').strip()
            if not v_name:
                continue
            v_code = (v.get('vaccine_code') or '').strip().upper()
            pending_label = awaiting_names.get(v_name.lower()) or (awaiting_codes.get(v_code) if v_code else None)
            if pending_label:
                return Response(
                    {'error': f"'{v_name}' is already authorized ({pending_label.lower()}). "
                              "Confirm it from the Vaccination Card once billing has cleared it - do not authorize it again."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if (v.get('payment_mode') or 'free').strip().lower() != 'free':
                tid = v.get('tariff_id')
                if not tid:
                    return Response(
                        {'error': f"'{v_name}' has no price on this patient's sponsor/plan tariff. "
                                  "Pick a priced vaccine, mark it as Free EPI, or add the vaccine to the plan's tariff."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                plist = 'general' if (v.get('price_list') or '').lower() == 'general' else 'plan'
                key = (plist, str(tid))
                if key not in price_cache:
                    price_cache[key] = resolve_tariff_for_patient(patient, tid, plist)
                if price_cache[key] is None:
                    return Response(
                        {'error': f"The price for '{v_name}' is not valid for this patient's sponsor/plan. Reload the clinic and try again."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
            if v.get('expiry_date'):
                try:
                    vial_exp = datetime.strptime(str(v.get('expiry_date'))[:10], '%Y-%m-%d').date()
                except Exception:
                    return Response({'error': f"Invalid vial expiry date for '{v_name}'."}, status=status.HTTP_400_BAD_REQUEST)
                if vial_exp < admin_date:
                    return Response(
                        {'error': f"'{v_name}' batch {v.get('batch_number') or ''} expired on {vial_exp.strftime('%d-%b-%Y')}. "
                                  "Do not administer expired vaccine. Select another batch."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

        for v in vaccines:
            v_name = v.get('vaccine_name', '').strip()
            if not v_name:
                continue

            # Prices are NEVER taken from the client. A billable vaccine must be linked to a
            # sponsor/plan tariff; the tariff decides the price and who pays (HMO claim vs patient).
            requested_mode = (v.get('payment_mode') or 'free').strip().lower()
            tariff_id = v.get('tariff_id')
            priced = None
            if requested_mode != 'free':
                if not tariff_id:
                    return Response(
                        {'error': f"'{v_name}' has no price on this patient's sponsor/plan tariff. "
                                  "Pick a priced vaccine, mark it as Free EPI, or add the vaccine to the plan's tariff."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                plist = 'general' if (v.get('price_list') or '').lower() == 'general' else 'plan'
                key = (plist, str(tariff_id))
                if key not in price_cache:
                    price_cache[key] = resolve_tariff_for_patient(patient, tariff_id, plist)
                priced = price_cache[key]
                if priced is None:
                    return Response(
                        {'error': f"The price for '{v_name}' is not valid for this patient's sponsor/plan. Reload the clinic and try again."},
                        status=status.HTTP_400_BAD_REQUEST,
                    )

            if priced:
                fee_val = Decimal(str(priced['rate']))
                pay_mode = priced['payment_mode']  # 'covered' (HMO claim) or 'cash' (patient pays)
                tariff_note = f"[Tariff: {priced['name']} - {priced['source_label']} @ NGN {priced['rate']:,.2f}]"
                if plist == 'general' and patient.sponsor_id:
                    tariff_note += ' [Not covered by HMO/sponsor plan - pay from purse]'
            else:
                fee_val = Decimal('0.00')
                pay_mode = 'free'
                tariff_note = ''
            is_billable = bool(fee_val > 0)

            exp_date = None
            if v.get('expiry_date'):
                try:
                    exp_date = datetime.strptime(v.get('expiry_date'), '%Y-%m-%d').date()
                except Exception:
                    pass

            item_due_date = next_due_date
            if v.get('next_due_date'):
                try:
                    item_due_date = datetime.strptime(v.get('next_due_date'), '%Y-%m-%d').date()
                except Exception:
                    pass

            rec = ImmunizationRecord.objects.create(
                patient=patient,
                appointment=appointment,
                vaccine_name=v_name,
                vaccine_code=v.get('vaccine_code') or None,
                dose_stage=v.get('dose_stage', '1st Dose'),
                schedule_stage=v.get('schedule_stage') or None,
                route=v.get('route', 'Intramuscular (IM)'),
                site=v.get('site', 'Left Anterolateral Thigh'),
                batch_number=v.get('batch_number') or None,
                expiry_date=exp_date,
                manufacturer=v.get('manufacturer') or None,
                administered_date=admin_date,
                administered_time=timezone.now().time(),
                administered_by=current_user,
                administered_by_name=staff_name,
                next_due_date=item_due_date,
                fee=fee_val,
                is_billable=is_billable,
                payment_mode=pay_mode,
                tariff_id=priced['tariff_id'] if priced else None,
                tariff_name=(priced['name'] if priced else None),
                price_source=(priced['source'] if priced else None),
                billing_status='pending' if is_billable else 'not_billable',
                authorized_by_name=staff_name,
                administration_confirmed=not is_billable,
                confirmed_at=None if is_billable else timezone.now(),
                notes=' '.join(x for x in [v.get('notes') or '', tariff_note] if x).strip(),
                aefi_reported=bool(v.get('aefi_reported', False)),
                aefi_notes=v.get('aefi_notes') or None,
            )
            saved_records.append(rec)
            vaccine_names_summary.append(f"{rec.vaccine_name} [{rec.dose_stage}] via {rec.route} ({rec.site})")

            if is_billable and fee_val > 0:
                total_billed += fee_val

        if not saved_records:
            return Response({'error': 'No valid vaccines were provided to record'}, status=status.HTTP_400_BAD_REQUEST)

        awaiting_count = len([r for r in saved_records if r.billing_status == 'pending'])

        # 1. Create a permanent PatientEncounter in the electronic medical records
        next_due_info = compute_next_due_vaccines(patient)
        next_due_text = format_next_due_text(next_due_info)
        summary_text = (
            ("AUTHORIZED VACCINES (awaiting payment / HMO approval where billable):\n" if awaiting_count else "ADMINISTERED VACCINES:\n") +
            "\n".join([f"- {s}" for s in vaccine_names_summary]) +
            (f"\n\nNEXT VACCINES DUE:\n{next_due_text}" if next_due_text else "\n\nNEXT VACCINES DUE: Routine schedule complete for current age.") +
            (f"\nRETURN VISIT BOOKED FOR: {next_due_date.strftime('%d-%b-%Y')}" if next_due_date else "") +
            (f"\nCLINICAL OBSERVATIONS / NOTES: {data.get('general_notes')}" if data.get('general_notes') else "")
        )

        # PatientEncounter.provider is required: use the logged-in user, else the staff
        # member named on the request, else any active staff account so the note is never lost.
        # The case note is signed by the staff member who authorized with their PIN
        provider = current_user

        encounter_saved = False
        if provider is not None:
            try:
                PatientEncounter.objects.create(
                    patient=patient,
                    provider=provider,
                    chief_complaint='Routine Immunization & Vaccine Administration',
                    history_of_present_illness=summary_text,
                    diagnosis='Immunization Clinic Visit (EPI Schedule)',
                    comments_on_diagnosis=(
                        f"Vaccine(s) authorized by {staff_name} (security PIN verified)."
                        + (
                            f" {awaiting_count} vaccine(s) sent to billing - to be given only after payment / HMO approval, then confirmed by the administering nurse with their PIN."
                            if awaiting_count else ""
                        )
                    ),
                )
                encounter_saved = True
            except Exception as e:
                logger.exception('Error creating immunization PatientEncounter for patient %s: %s', patient.id, e)
        else:
            logger.error('No staff user available to record immunization case note for patient %s', patient.id)

        # 2. If next appointment date provided, create follow-up appointment
        if next_due_date:
            try:
                PatientAppointment.objects.create(
                    patient=patient,
                    arrival_date=next_due_date,
                    purpose='Immunization Follow-up & Next Dose',
                    doctor=current_user,
                    visit_type='Routine',
                )
            except Exception as e:
                print(f"Error scheduling next immunization appointment: {e}")

        # 3. Billable vaccines are now 'pending' ImmunizationRecords: the Encounter Billing Queue
        #    picks them up (HMO-covered -> claim needing PA code, others -> patient invoice).
        covered_total = sum((r.fee for r in saved_records if r.billing_status == 'pending' and r.payment_mode == 'covered'), Decimal('0.00'))
        patient_total = total_billed - covered_total

        # 4. If current appointment was for immunization, mark completed
        if appointment:
            try:
                appointment.status = 'Completed'
                appointment.save()
            except Exception:
                pass

        patient_name = f"{patient.surname or ''} {patient.first_name or ''}".strip() or 'Patient'
        return Response({
            'success': True,
            'total_administered': len(saved_records),
            'total_billed': float(total_billed),
            'case_note_saved': encounter_saved,
            'authorized_by': staff_name,
            'sent_to_billing': len([r for r in saved_records if r.billing_status == 'pending']),
            'hmo_claim_total': float(covered_total),
            'patient_pay_total': float(patient_total),
            'next_due': next_due_info,
            'next_appointment_date': next_due_date.isoformat() if next_due_date else None,
            'awaiting_clearance': awaiting_count,
            'message': (
                f"{len(saved_records)} vaccine(s) authorized for {patient_name} by {staff_name}. "
                f"{awaiting_count} sent to billing - give them after payment / HMO approval and confirm with your PIN."
                if awaiting_count else
                f"Successfully administered {len(saved_records)} vaccine(s) to {patient_name} by {staff_name}!"
            ),
        })


class ConfirmImmunizationAdministrationView(APIView):
    """
    Step 2 for billable vaccines: once billing has cleared them (paid / HMO approved),
    the nurse who gives the injection confirms it with their security PIN.
    Body: { patient_id, record_ids: [...], pin, staff_id?, notes? }
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        data = request.data
        patient = get_object_or_404(PatientProfile, id=data.get('patient_id'))
        ids = [int(i) for i in (data.get('record_ids') or []) if str(i).isdigit()]
        if not ids:
            return Response({'error': 'Select at least one vaccine to confirm.'}, status=status.HTTP_400_BAD_REQUEST)

        nurse, pin_error = verify_staff_pin(request, data, action='confirm the vaccine was given')
        if pin_error is not None:
            return pin_error
        nurse_name = (getattr(nurse, 'fullname', None) or '').strip() or nurse.username

        records = list(ImmunizationRecord.objects.filter(patient=patient, id__in=ids))
        if len(records) != len(set(ids)):
            return Response({'error': 'One or more vaccines were not found for this patient.'}, status=status.HTTP_404_NOT_FOUND)

        clearance = get_immunization_clearance(records)
        today = date.today()
        for r in records:
            c = clearance[r.id]
            if c['administered']:
                return Response({'error': f"'{r.vaccine_name}' is already confirmed as given."}, status=status.HTTP_400_BAD_REQUEST)
            if not c['cleared']:
                return Response(
                    {'error': f"'{r.vaccine_name}' is {c['label'].lower()}. Do not give it until billing clears it."},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if r.expiry_date and r.expiry_date < today:
                return Response(
                    {'error': f"'{r.vaccine_name}' batch {r.batch_number or ''} expired on {r.expiry_date.strftime('%d-%b-%Y')}. "
                              "Do not administer expired vaccine."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        now = timezone.now()
        extra = (data.get('notes') or '').strip()
        for r in records:
            r.authorized_by_name = r.authorized_by_name or r.administered_by_name
            r.administered_by = nurse
            r.administered_by_name = nurse_name
            r.administered_date = today
            r.administered_time = timezone.localtime(now).time() if timezone.is_aware(now) else now.time()
            r.administration_confirmed = True
            r.confirmed_at = now
            if extra:
                r.notes = f"{r.notes or ''} [Given: {extra}]".strip()
            r.save(update_fields=[
                'authorized_by_name', 'administered_by', 'administered_by_name', 'administered_date',
                'administered_time', 'administration_confirmed', 'confirmed_at', 'notes',
            ])

        lines = []
        for r in records:
            c = clearance[r.id]
            ref = f" - {c['label'].split(' - ')[0]} {c['invoice_number']}" if c.get('invoice_number') else ''
            lines.append(f"- {r.vaccine_name} [{r.dose_stage}] via {r.route} ({r.site}){f', batch {r.batch_number}' if r.batch_number else ''}{ref}")
        next_due_text = format_next_due_text(compute_next_due_vaccines(patient))
        case_note_saved = False
        try:
            PatientEncounter.objects.create(
                patient=patient,
                provider=nurse,
                chief_complaint='Routine Immunization - Vaccine Administered',
                history_of_present_illness=(
                    "ADMINISTERED VACCINES (after billing clearance):\n" + "\n".join(lines)
                    + (f"\n\nNEXT VACCINES DUE:\n{next_due_text}" if next_due_text else '')
                    + (f"\nNOTES: {extra}" if extra else '')
                ),
                diagnosis='Immunization Clinic Visit (EPI Schedule)',
                comments_on_diagnosis=f"Vaccine(s) administered by {nurse_name} (security PIN verified). "
                                      "Patient observed post-administration without immediate adverse reactions.",
            )
            case_note_saved = True
        except Exception as e:
            logger.exception('Error creating confirmation PatientEncounter for patient %s: %s', patient.id, e)

        return Response({
            'success': True,
            'confirmed': len(records),
            'administered_by': nurse_name,
            'case_note_saved': case_note_saved,
            'message': f"{len(records)} vaccine(s) confirmed as given by {nurse_name}.",
        })


class DeleteImmunizationRecordView(APIView):
    """Deletes or reverses an immunization record entered in error."""
    permission_classes = [permissions.AllowAny]

    def delete(self, request, pk):
        record = get_object_or_404(ImmunizationRecord, id=pk)
        record.delete()
        return Response({'success': True, 'message': 'Immunization record removed successfully.'})

