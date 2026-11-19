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
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)

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
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)  # request.user.username
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
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
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)  # request.user.username
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    admission_record = models.ForeignKey(AdmissionTable, on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" fees for {self.patient.surname} {self.patient.first_name} is {self.price}"


    # ---------- Notes ---------

class AdmissionNote(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='admission_notes')
    admission_note =  models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"

class DoctorNote(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='doctor_notes')
    doctor_note =  models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"

class NurseNote(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='nurse_notes')
    nurse_note =  models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from {self.staff.fullname}"

class WardRound(models.Model):
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='ward_rounds')
    notes = models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
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
        ('im', 'IM'),
        ('sc', 'Subcutaneous'),
        ('topical', 'Topical'),
        ('inhaled', 'Inhaled'),
    ]

    FREQUENCY = [
        ('od', 'Once Daily (OD)'),
        ('bd', 'Twice Daily (BD)'),
        ('tds', 'Three Times Daily (TDS)'),
        ('qds', 'Four Times Daily (QDS)'),
        ('prn', 'As Required (PRN)'),
        ('stat', 'Stat (Immediate)'),
    ]

    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='prescriptions')
    admission = models.ForeignKey(AdmissionTable, on_delete=models.CASCADE, null=True, blank=True, related_name='drug_prescriptions')
    prescription_type = models.CharField(max_length=20, choices=PRESCRIPTION_TYPES, default='regular')
    drug_name = models.CharField(max_length=200)
    dose = models.CharField(max_length=50)  # e.g., "500mg"
    quantity = models.IntegerField(default=1)
    route = models.CharField(max_length=20, choices=ROUTES)
    frequency = models.CharField(max_length=20, choices=FREQUENCY)
    start_date = models.DateField()
    stop_date = models.DateField(null=True, blank=True)
    prescribed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, related_name='prescribed_drugs')
    prescribed_at = models.DateTimeField(auto_now_add=True)
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True)

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
