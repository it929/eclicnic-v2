from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db.models import Q


# Admission lifecycle. Every change goes through IPD/services.py, which also keeps the
# legacy 0/1 flags below in step for the older screens and reports that still read them.
ADMISSION_STATUSES = [
    ('awaiting_bed', 'Awaiting bed'),           # doctor admitted, ward has not received the patient yet
    ('in_ward', 'In ward'),                     # received by the ward and on a bed
    ('discharge_ordered', 'Discharge ordered'), # doctor signed the discharge, patient still on the bed
    ('discharged', 'Discharged'),               # left the ward, bed released
    ('cancelled', 'Cancelled'),                 # admitted in error, before the ward received the patient
]
OPEN_ADMISSION_STATUSES = ('awaiting_bed', 'in_ward', 'discharge_ordered')

ADMISSION_TYPES = [
    ('elective', 'Elective / planned'),
    ('emergency', 'Emergency'),
    ('maternity', 'Maternity / labour'),
    ('observation', 'Observation'),
]
ADMISSION_SOURCES = [
    ('opd', 'Out-patient encounter'),
    ('anc', 'Antenatal clinic'),
    ('emergency', 'Emergency'),
    ('direct', 'Direct admission'),
    ('referral', 'Referral from another facility'),
]
DISCHARGE_TYPES = [
    ('routine', 'Routine discharge'),
    ('ama', 'Discharged against medical advice'),
    ('referred', 'Referred out'),
    ('death', 'Death'),
    ('absconded', 'Absconded'),
]


class AdmissionTable(models.Model):
    """One in-patient stay (an admission episode). Notes, ward rounds, drug charts and bills
    of the stay hang off this row through their ``admission`` foreign key."""
    admission_no = models.CharField(max_length=20, unique=True, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ADMISSION_STATUSES, default='awaiting_bed', db_index=True)
    admission_type = models.CharField(max_length=20, choices=ADMISSION_TYPES, default='elective')
    source = models.CharField(max_length=20, choices=ADMISSION_SOURCES, default='opd')
    appointment = models.ForeignKey('patients.PatientAppointment', on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name='admissions')
    ward = models.ForeignKey('IPD.Ward', on_delete=models.PROTECT, null=True, blank=True, related_name='admissions',
                             help_text='Requested ward until a bed is given, then the ward of the current bed.')
    bed = models.ForeignKey('IPD.Bed', on_delete=models.PROTECT, null=True, blank=True, related_name='admissions',
                            help_text='Current bed (history lives in BedAllocation).')
    consultant = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name='ipd_consultant_admissions')
    reason = models.TextField(blank=True, default='')
    provisional_diagnosis = models.TextField(blank=True, default='')
    notes = models.TextField(blank=True, default='')
    # Sponsor / plan at the time of admission: the stay is billed on these even if the patient's
    # sponsor changes later.
    sponsor = models.ForeignKey('patients.Sponsor', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+',
                                   help_text='Account signed in when the admission was entered.')
    received_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    discharge_ordered_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    discharge_type = models.CharField(max_length=20, choices=DISCHARGE_TYPES, blank=True, default='')
    discharge_summary = models.TextField(blank=True, default='')
    discharged_at = models.DateTimeField(null=True, blank=True)
    discharged_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cancel_reason = models.TextField(blank=True, default='')
    updated_at = models.DateTimeField(auto_now=True, null=True)
    # Billing clearance (IPD/billing_services.py). The ward cannot release the patient until set.
    bill_cleared_at = models.DateTimeField(null=True, blank=True)
    bill_cleared_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    clearance_type = models.CharField(max_length=10, blank=True, default='')  # paid | credit
    clearance_note = models.TextField(blank=True, default='')
    # HMO pre-authorization (PA) code for the stay. Sponsor-billed bed-days are approved with it automatically.
    pa_code = models.CharField(max_length=60, blank=True, default='')

    # ---- legacy fields (kept in step by IPD/services.py) ----
    doctor_admitted = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    doctor_admit_date = models.DateTimeField(auto_now_add=True)
    nurse_admitted =  models.CharField(null=True,max_length=50)
    nurse_admit_status = models.PositiveIntegerField(default=0)
    nurse_admit_date = models.DateTimeField(null=True, blank=True)
    doctor_discharged = models.CharField(null=True,max_length=50)
    doctor_discharge_status = models.PositiveIntegerField(default=0)
    doctor_discharge_date = models.DateTimeField(null=True, blank=True)
    bill_discharged = models.CharField(null=True,max_length=50)
    bill_discharge_status = models.PositiveIntegerField(default=0)
    bill_discharge_date = models.DateTimeField(null=True, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)

    class Meta:
        ordering = ['-doctor_admit_date']
        constraints = [
            # A patient can only be on one open admission at a time.
            models.UniqueConstraint(fields=['patient'], condition=Q(status__in=OPEN_ADMISSION_STATUSES),
                                    name='ipd_one_open_admission_per_patient'),
        ]

    @property
    def is_open(self):
        return self.status in OPEN_ADMISSION_STATUSES

    @property
    def current_allocation(self):
        return self.bedallocation_set.filter(is_active=True).first()

    def __str__(self):
        return f' {self.patient.surname} {self.patient.first_name} admitted on ({self.doctor_admit_date})'

WARD_TYPES = [
    ('general', 'General'),
    ('private', 'Private room'),
    ('maternity', 'Maternity / labour'),
    ('paediatric', 'Paediatric'),
    ('icu', 'Intensive care'),
    ('isolation', 'Isolation'),
    ('other', 'Other'),
]
WARD_GENDERS = [('any', 'Any'), ('male', 'Male only'), ('female', 'Female only')]


class Ward(models.Model):
    ward_name =  models.CharField(null=True,max_length=50,unique=True)
    price = models.PositiveIntegerField(default=0)  # general daily fee; sponsor/plan prices go through api/pricing.py
    ward_type = models.CharField(max_length=20, choices=WARD_TYPES, default='general')
    gender = models.CharField(max_length=10, choices=WARD_GENDERS, default='any')
    is_active = models.BooleanField(default=True)
    pharmacy_store = models.ForeignKey('inventory.PharmacyStore', on_delete=models.SET_NULL, null=True, blank=True,
                                       related_name='wards', help_text='IPD pharmacy that supplies this ward.')

    def __str__(self):
        return f"{self.ward_name}"

class Bed(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='beds', null=True)
    bed_name =  models.CharField(null=True,max_length=50)
    bed_status = models.PositiveIntegerField(default=0)
    is_occupied = models.BooleanField(default=False)  # cache of "has an active BedAllocation"
    is_active = models.BooleanField(default=True)     # False = out of service (repair, closed)
    class Meta:
        unique_together = ('ward', 'bed_name')
        ordering = ['ward_id', 'id']

    def __str__(self):
        return f"{self.bed_name}"

class BedAllocation(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='allocations', null=True)
    bed = models.ForeignKey(Bed, on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)  # request.user.username
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    admission_record = models.ForeignKey(AdmissionTable, on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    reason = models.CharField(max_length=20, default='admission')  # admission | transfer
    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')

    class Meta:
        ordering = ['-created_date']
        constraints = [
            models.UniqueConstraint(fields=['bed'], condition=Q(is_active=True), name='ipd_one_patient_per_bed'),
            models.UniqueConstraint(fields=['admission_record'], condition=Q(is_active=True),
                                    name='ipd_one_bed_per_admission'),
        ]
    
    def __str__(self):
        return f"{self.patient} - {self.bed} ({'Active' if self.is_active else 'Inactive'})"


class AdmissionFee(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='admission_fee', null=True)
    price = models.PositiveIntegerField(default=0)
    num_of_days = models.PositiveIntegerField(default=0)
    completed = models.PositiveIntegerField(default=0)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)  # request.user.username
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    admission_record = models.ForeignKey(AdmissionTable, on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" fees for {self.patient.surname} {self.patient.first_name} is {self.price}"


    # ---------- Notes ---------

class AdmissionNote(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='admission_notes')
    admission_note =  models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"

class DoctorNote(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='doctor_notes')
    doctor_note =  models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"

class NurseNote(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='nurse_notes')
    nurse_note =  models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"

class WardRound(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='ward_rounds')
    notes = models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"



class DrugPrescription(models.Model):
    PRESCRIPTION_TYPES = [
        ('regular', 'Regular Prescription'),
        ('stat', 'Stat Prescription'),
        ('prn', 'PRN Prescription'),
        ('glycemic', 'Glycemic Control Standing Order'),
    ]

    ROUTES = [
        ('oral', 'Oral'),
        ('iv', 'IV'),
        ('iv_inf', 'IV Infusion'),
        ('im', 'IM'),
        ('sc', 'Subcutaneous'),
        ('id', 'Intradermal'),
        ('topical', 'Topical'),
        ('inhaled', 'Inhaled'),
        ('pr', 'Rectal (PR)'),
        ('pv', 'Vaginal (PV)'),
        ('sl', 'Sublingual'),
        ('buccal', 'Buccal'),
        ('td', 'Transdermal'),
        ('ng', 'Nasogastric'),
        ('eye', 'Eye'),
        ('ear', 'Ear'),
        ('nasal', 'Nasal'),
    ]

    FREQUENCY = [
        ('od', 'Once Daily (OD)'),
        ('bd', 'Twice Daily (BD)'),
        ('tds', 'Three Times Daily (TDS)'),
        ('qds', 'Four Times Daily (QDS)'),
        ('q4h', 'Every 4 hours'),
        ('q6h', 'Every 6 hours'),
        ('q8h', 'Every 8 hours'),
        ('q12h', 'Every 12 hours'),
        ('mane', 'Morning (mane)'),
        ('nocte', 'At night (nocte)'),
        ('prn', 'As Required (PRN)'),
        ('stat', 'Stat (Immediate)'),
    ]

    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, related_name='prescriptions')
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='drug_prescriptions')
    prescription_type = models.CharField(max_length=20, choices=PRESCRIPTION_TYPES, default='regular')
    drug_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=50)  # display text, e.g. "1 cap (500mg)"
    # Structured order (IPD prescribe form). `dose` above is composed from these.
    dosage_form = models.CharField(max_length=30, blank=True, default='')
    strength = models.CharField(max_length=50, blank=True, default='')
    dose_qty = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    dose_unit = models.CharField(max_length=20, blank=True, default='')
    product_code = models.CharField(max_length=60, blank=True, default='')  # tariff product id / SKU
    # PRN only: most doses allowed in any 24 hours (checked when a dose is charted).
    prn_max_per_day = models.PositiveSmallIntegerField(null=True, blank=True)
    pay_source = models.CharField(max_length=10, blank=True, default='',
                                  choices=[('plan', 'Covered by plan'), ('patient', 'Patient pays')])
    quantity = models.IntegerField(default=1)
    route = models.CharField(max_length=20, choices=ROUTES)
    frequency = models.CharField(max_length=20, choices=FREQUENCY)
    start_date = models.DateField()
    stop_date = models.DateField(null=True, blank=True)
    prescribed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='prescribed_drugs')
    prescribed_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)
    discontinued_at = models.DateTimeField(null=True, blank=True)
    discontinued_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    discontinue_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-start_date', 'drug_name']

    def __str__(self):
        return f"{self.drug_name} - {self.dose} ({self.route})"


class DrugAdministration(models.Model):
    ADMINISTRATION_STATUS = [
        ('pending', 'Pending'),
        ('administered', 'Administered'),
        ('missed', 'Missed'),
        ('refused', 'Refused'),
        ('held', 'Held'),
    ]

    # Generic foreign key to any prescription model
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE, null=True)
    object_id = models.PositiveIntegerField(null=True)
    prescription = GenericForeignKey('content_type', 'object_id')

    source_store = models.CharField(max_length=50, blank=True, null=True)  # ipd_pharm1, ipd_pharm2, etc.
    source_model = models.CharField(max_length=100, blank=True, null=True)  # IPDAdministeredDrugs, etc.
    source_record_id = models.IntegerField(blank=True, null=True)

    # Administration details
    scheduled_time = models.DateTimeField()
    administered_time = models.DateTimeField(null=True, blank=True)
    administered_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(max_length=20, choices=ADMINISTRATION_STATUS, default='pending')

    # Fields
    is_patient_owned = models.BooleanField(default=False)
    action = models.CharField(max_length=50, blank=True)
    bedside_drug = models.CharField(max_length=200, blank=True)
    quantity_administered = models.CharField(max_length=50, blank=True)
    batch_no = models.CharField(max_length=100, blank=True)
    dose_given = models.CharField(max_length=50, blank=True)
    comments = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['scheduled_time']

    def __str__(self):
        return f"{self.get_status_display()} - {self.scheduled_time}"


class AdmissionEvent(models.Model):
    """Timeline of an admission: who did what and when (admit, bed, transfer, discharge, cancel)."""
    EVENTS = [
        ('admitted', 'Admitted'),
        ('bed_assigned', 'Bed assigned'),
        ('transferred', 'Bed transfer'),
        ('discharge_ordered', 'Discharge ordered'),
        ('discharge_reversed', 'Discharge order withdrawn'),
        ('discharged', 'Discharged'),
        ('cancelled', 'Cancelled'),
        ('med_ordered', 'Medication ordered'),
        ('med_stopped', 'Medication discontinued'),
        ('treatment_ordered', 'Treatment ordered'),
        ('treatment_stopped', 'Treatment discontinued'),
        ('entry_voided', 'Chart entry marked as error'),
        ('type_changed', 'Admission type changed'),
        ('charge_reversed', 'Charge reversed'),
        ('hmo_approved', 'HMO approval recorded'),
        ('hmo_declined', 'Not covered by HMO (patient pays)'),
        ('payment', 'Payment received'),
        ('payment_reversed', 'Payment reversed'),
        ('bill', 'Bill generated'),
        ('bill_cancelled', 'Final bill cancelled'),
        ('bill_cleared', 'Bill cleared for discharge'),
        ('supply_requested', 'Pharmacy supply requested'),
        ('supply_dispensed', 'Pharmacy supply dispensed'),
        ('supply_cancelled', 'Pharmacy supply cancelled'),
        ('investigation_ordered', 'Investigation / service ordered'),
        ('investigation_cancelled', 'Investigation / service cancelled'),
    ]
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='events')
    event = models.CharField(max_length=30, choices=EVENTS)
    from_status = models.CharField(max_length=20, blank=True, default='')
    to_status = models.CharField(max_length=20, blank=True, default='')
    detail = models.TextField(blank=True, default='')
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['created_at', 'id']

    def __str__(self):
        return f"{self.admission_id} {self.event} @ {self.created_at:%Y-%m-%d %H:%M}"


# ---------------------------------------------------------------------------------------------
# Inpatient chart. Rules live in IPD/chart_services.py. Clinical entries are never deleted:
# a wrong entry is marked "entered in error" (voided) with a reason, and stays visible.
# ---------------------------------------------------------------------------------------------
class _Voidable(models.Model):
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    void_reason = models.TextField(blank=True, default='')

    class Meta:
        abstract = True


NOTE_TYPES = [
    ('admission', 'Admission note'),
    ('doctor', "Doctor's note"),
    ('progress', 'Progress note'),
    ('ward_round', 'Ward round'),
    ('nursing', 'Nursing note'),
    ('sponsor', 'Sponsor note'),
    ('procedure', 'Procedure note'),
    ('discharge', 'Discharge note'),
    ('general', 'General note'),
]


class ClinicalNote(_Voidable):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='clinical_notes')
    note_type = models.CharField(max_length=20, choices=NOTE_TYPES, default='general', db_index=True)
    title = models.CharField(max_length=200, blank=True, default='')
    body = models.TextField()
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-created_at', '-id']


CONSCIOUSNESS = [('A', 'Alert'), ('C', 'New confusion'), ('V', 'Responds to voice'),
                 ('P', 'Responds to pain'), ('U', 'Unresponsive')]


class Observation(_Voidable):
    """One set of vital signs (observation chart)."""
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='observations')
    recorded_at = models.DateTimeField(db_index=True)
    temperature = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    pulse = models.PositiveIntegerField(null=True, blank=True)
    resp_rate = models.PositiveIntegerField(null=True, blank=True)
    bp_systolic = models.PositiveIntegerField(null=True, blank=True)
    bp_diastolic = models.PositiveIntegerField(null=True, blank=True)
    spo2 = models.PositiveIntegerField(null=True, blank=True)
    on_oxygen = models.BooleanField(default=False)
    oxygen_lpm = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    consciousness = models.CharField(max_length=1, choices=CONSCIOUSNESS, default='A')
    pain_score = models.PositiveSmallIntegerField(null=True, blank=True)
    blood_glucose = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)  # mmol/L
    weight = models.DecimalField(max_digits=5, decimal_places=1, null=True, blank=True)        # kg
    news_score = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, default='')
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at', '-id']


FLUID_KINDS = [('in', 'Intake'), ('out', 'Output')]
FLUID_ROUTES = [
    ('oral', 'Oral'), ('iv', 'IV fluid'), ('ng', 'NG feed'), ('blood', 'Blood / products'),
    ('urine', 'Urine'), ('vomit', 'Vomit'), ('drain', 'Drain'), ('stool', 'Stool'),
    ('ng_aspirate', 'NG aspirate'), ('blood_loss', 'Blood loss'), ('other', 'Other'),
]
FLUID_IN_ROUTES = ('oral', 'iv', 'ng', 'blood', 'other')
FLUID_OUT_ROUTES = ('urine', 'vomit', 'drain', 'stool', 'ng_aspirate', 'blood_loss', 'other')


class FluidEntry(_Voidable):
    """Fluid balance chart: one intake or output entry."""
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='fluid_entries')
    kind = models.CharField(max_length=3, choices=FLUID_KINDS)
    route = models.CharField(max_length=20, choices=FLUID_ROUTES)
    fluid = models.CharField(max_length=120, blank=True, default='')  # e.g. Normal saline, Pap
    volume_ml = models.PositiveIntegerField()
    recorded_at = models.DateTimeField(db_index=True)
    notes = models.CharField(max_length=300, blank=True, default='')
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-recorded_at', '-id']


TREATMENT_CATEGORIES = [
    ('nursing', 'Nursing care'), ('dressing', 'Wound dressing'), ('feeding', 'Feeding'),
    ('monitoring', 'Monitoring'), ('positioning', 'Positioning / turning'), ('procedure', 'Procedure'),
    ('physio', 'Physiotherapy'), ('other', 'Other'),
]


class TreatmentOrder(models.Model):
    """A non-drug order the ward carries out (treatment chart / execute order)."""
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='treatment_orders')
    category = models.CharField(max_length=20, choices=TREATMENT_CATEGORIES, default='nursing')
    instruction = models.TextField()
    frequency = models.CharField(max_length=20, default='od')  # same codes as DrugPrescription.FREQUENCY
    start_date = models.DateField()
    stop_date = models.DateField(null=True, blank=True)
    ordered_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    ordered_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    discontinued_at = models.DateTimeField(null=True, blank=True)
    discontinued_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    discontinue_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-ordered_at']


class TreatmentRecord(models.Model):
    STATUSES = [('done', 'Done'), ('not_done', 'Not done'), ('refused', 'Refused')]
    order = models.ForeignKey(TreatmentOrder, on_delete=models.CASCADE, related_name='records')
    scheduled_time = models.DateTimeField(null=True, blank=True)  # None for PRN / as-needed
    performed_at = models.DateTimeField()
    status = models.CharField(max_length=10, choices=STATUSES, default='done')
    comment = models.TextField(blank=True, default='')
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['performed_at']
        constraints = [
            models.UniqueConstraint(fields=['order', 'scheduled_time'], condition=Q(scheduled_time__isnull=False),
                                    name='ipd_one_record_per_treatment_slot'),
        ]


# ---------------------------------------------------------------------------------------------
# Inpatient billing: a running account per admission. Rules live in IPD/billing_services.py.
# Charges are priced on the server (api/pricing.py + WardTariff) and never deleted: a wrong
# charge is reversed with a reason. Payments are mirrored to Billings.Receipt for the cashier.
# ---------------------------------------------------------------------------------------------
class WardTariff(models.Model):
    """Daily bed fee of a ward for a sponsor and/or plan. A row with neither is the General price
    (Ward.price is the fallback General price)."""
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='tariffs')
    sponsor = models.ForeignKey('patients.Sponsor', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True, blank=True, related_name='+')
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    updated_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['ward_id', 'sponsor_id', 'plan_id']


CHARGE_KINDS = [
    ('bed', 'Bed / ward fee'),
    ('drug', 'Drug'),
    ('service', 'Service / procedure'),
    ('lab', 'Laboratory'),
    ('radiology', 'Radiology / scan'),
    ('other', 'Other (manual price)'),
]
PAYERS = [('patient', 'Patient'), ('sponsor', 'Sponsor (claim)')]
# HMO approval of a claim line: '' when the patient pays; pending until the HMO gives a PA code;
# declined lines are re-priced at the General price and moved to the patient.
APPROVAL_STATUSES = [('', 'Not a claim'), ('pending', 'Awaiting HMO approval'), ('approved', 'Approved by HMO'),
                     ('declined', 'Not covered (patient pays)')]


class AdmissionBill(models.Model):
    KINDS = [('interim', 'Interim bill'), ('final', 'Final bill')]
    STATUSES = [('active', 'Active'), ('cancelled', 'Cancelled')]
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='bills')
    bill_no = models.CharField(max_length=20, unique=True)
    kind = models.CharField(max_length=10, choices=KINDS)
    status = models.CharField(max_length=10, choices=STATUSES, default='active')
    total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    sponsor_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    patient_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    paid_total = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    balance = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cancel_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['-created_at', '-id']
        constraints = [
            models.UniqueConstraint(fields=['admission'], condition=Q(kind='final', status='active'),
                                    name='ipd_one_active_final_bill'),
        ]


class AdmissionCharge(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='charges')
    kind = models.CharField(max_length=10, choices=CHARGE_KINDS)
    description = models.CharField(max_length=255)
    code = models.CharField(max_length=50, blank=True, default='')
    service_date = models.DateField(db_index=True)
    qty = models.PositiveIntegerField(default=1)
    unit_price = models.DecimalField(max_digits=15, decimal_places=2)
    amount = models.DecimalField(max_digits=15, decimal_places=2)
    price_source = models.CharField(max_length=20, blank=True, default='')  # plan | sponsor | general | manual
    tariff_id = models.IntegerField(null=True, blank=True)
    payer = models.CharField(max_length=10, choices=PAYERS, default='patient')
    ward = models.ForeignKey(Ward, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    store = models.ForeignKey('inventory.PharmacyStore', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    product = models.ForeignKey('inventory.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    notes = models.CharField(max_length=500, blank=True, default='')
    posted_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    posted_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reverse_reason = models.TextField(blank=True, default='')
    # Ward orders: the drug-chart order this line supplies, or the lab / radiology request it pays for.
    prescription = models.ForeignKey(DrugPrescription, on_delete=models.SET_NULL, null=True, blank=True, related_name='charges')
    radiolab = models.ForeignKey('radio_lab.RadiologyLab', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    urgent = models.BooleanField(default=False)
    # HMO approval (IPD/billing_services.py: approve_charges / decline_charge)
    approval_status = models.CharField(max_length=10, choices=APPROVAL_STATUSES, blank=True, default='', db_index=True)
    pa_code = models.CharField(max_length=60, blank=True, default='')
    approval_note = models.CharField(max_length=500, blank=True, default='')
    approval_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    approval_at = models.DateTimeField(null=True, blank=True)

    def save(self, *args, **kwargs):
        # Every new line billed to the sponsor waits for the HMO's approval unless the caller already decided.
        if self._state.adding and self.payer == 'sponsor' and not self.approval_status:
            self.approval_status = 'pending'
        if self.payer != 'sponsor' and self.approval_status in ('pending', 'approved'):
            self.approval_status = ''
        super().save(*args, **kwargs)

    class Meta:
        ordering = ['service_date', 'posted_at', 'id']
        constraints = [
            models.UniqueConstraint(fields=['admission', 'service_date'], condition=Q(kind='bed', reversed_at__isnull=True),
                                    name='ipd_one_bed_charge_per_day'),
        ]


PAYMENT_METHODS = [('Cash', 'Cash'), ('POS', 'POS / card'), ('Transfer', 'Bank transfer'), ('Cheque', 'Cheque')]


class AdmissionPayment(models.Model):
    KINDS = [('deposit', 'Deposit'), ('payment', 'Payment'), ('refund', 'Refund')]
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='payments')
    kind = models.CharField(max_length=10, choices=KINDS, default='deposit')
    amount = models.DecimalField(max_digits=15, decimal_places=2)  # always positive; refunds count against
    method = models.CharField(max_length=20, choices=PAYMENT_METHODS, default='Cash')
    reference = models.CharField(max_length=100, blank=True, default='')
    receipt_number = models.CharField(max_length=30, blank=True, default='')
    received_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    created_at = models.DateTimeField(auto_now_add=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    reverse_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['created_at', 'id']


class MedicationSupply(models.Model):
    """
    One request to the inpatient pharmacy to supply a drug-chart order: the first supply is raised
    when the doctor signs the order, later ones (refills) by the ward. The bill line is posted when
    the request is raised (if the drug is on a price list) and settled to the exact item and quantity
    when pharmacy dispenses; stock leaves the store only at dispensing.
    """
    STATUSES = [('pending', 'Awaiting pharmacy'), ('dispensed', 'Dispensed'), ('cancelled', 'Cancelled')]
    KINDS = [('initial', 'New order'), ('refill', 'Refill')]

    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, related_name='supplies')
    prescription = models.ForeignKey(DrugPrescription, on_delete=models.CASCADE, related_name='supplies')
    kind = models.CharField(max_length=10, choices=KINDS, default='initial')
    qty = models.PositiveIntegerField()
    status = models.CharField(max_length=10, choices=STATUSES, default='pending', db_index=True)
    store = models.ForeignKey('inventory.PharmacyStore', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    product = models.ForeignKey('inventory.Product', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    qty_dispensed = models.PositiveIntegerField(null=True, blank=True)
    charge = models.ForeignKey(AdmissionCharge, on_delete=models.SET_NULL, null=True, blank=True, related_name='supplies')
    notes = models.CharField(max_length=500, blank=True, default='')
    requested_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='+')
    requested_at = models.DateTimeField(auto_now_add=True)
    dispensed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    dispensed_at = models.DateTimeField(null=True, blank=True)
    batches = models.CharField(max_length=500, blank=True, default='')
    cancelled_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancel_reason = models.TextField(blank=True, default='')

    class Meta:
        ordering = ['requested_at', 'id']
