from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta


class ANCRegistration(models.Model):
    """Main ANC Registration model"""
    JOURNEY_STATUS_CHOICES = [
        ('active', 'Active'),
        ('completed', 'Completed'),
    ]

    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='anc_registrations')
    antenatal_visit = models.ForeignKey(
        'AntenatalVisit',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='registrations',
    )
    status = models.CharField(max_length=20, choices=JOURNEY_STATUS_CHOICES, default='active', db_index=True)
    registration_date = models.DateTimeField(auto_now_add=True)
    visit_date = models.DateTimeField(default=timezone.now)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    
    # Current Pregnancy fields
    last_menstrual_period = models.DateField(null=True, blank=True)
    gestational_age_weeks = models.IntegerField(null=True, blank=True)
    expected_delivery_date = models.DateField(null=True, blank=True)
    number_of_foetus = models.IntegerField(default=1)
    
    # Symptoms
    bleeding = models.BooleanField(default=False)
    vomiting = models.BooleanField(default=False)
    oedema = models.BooleanField(default=False)
    placenta_previa = models.BooleanField(default=False)
    blurred_vision = models.BooleanField(default=False)
    breathlessness = models.BooleanField(default=False)
    discharge = models.BooleanField(default=False)
    
    # Stage tracking
    current_stage = models.IntegerField(default=1)  # 1=Obstetric History, 2=Current Pregnancy, 3=General Medical, 4=Tests
    completed = models.BooleanField(default=False)
    
    class Meta:
        ordering = ['-visit_date']
    
    def calculate_gestational_age(self):
        """Calculate gestational age from LMP"""
        if self.last_menstrual_period:
            today = date.today()
            delta = today - self.last_menstrual_period
            self.gestational_age_weeks = delta.days // 7
            return self.gestational_age_weeks
        return None
    
    def calculate_edd(self):
        """Calculate Expected Date of Delivery (Naegele's rule)"""
        if self.last_menstrual_period:
            # Naegele's rule: LMP + 1 year - 3 months + 7 days
            edd = self.last_menstrual_period + relativedelta(years=1, months=-3, days=7)
            self.expected_delivery_date = edd
            return edd
        return None
    
    def save(self, *args, **kwargs):
        if self.last_menstrual_period:
            self.calculate_gestational_age()
            self.calculate_edd()
        super().save(*args, **kwargs)

# First Visit

YES_NO_CHOICES = [
    ('Yes', 'Yes'),
    ('No', 'No'),
    ('N/A', 'N/A'), # Not Applicable, if needed
]

BLOOD_GROUP_CHOICES = [
    ('A+', 'A+'), ('A-', 'A-'),
    ('B+', 'B+'), ('B-', 'B-'),
    ('AB+', 'AB+'), ('AB-', 'AB-'),
    ('O+', 'O+'), ('O-', 'O-'),
    ('Unknown', 'Unknown'),
    ('Awaiting Result', 'Awaiting Result'),
]

GENOTYPE_CHOICES = [
    ('AA', 'AA'), ('AS', 'AS'), ('SS', 'SS'), ('AC', 'AC'), ('CC', 'CC'), ('Unknown', 'Unknown'), ('Awaiting Result', 'Awaiting Result'),
]

RELATIONSHIP2PP_CHOICES = [
    ('0/5', '0/5'), ('1/5', '1/5'), ('2/5', '2/5'), ('3/5', '3/5'), ('4/5', '4/5'), ('5/5', '5/5'), ('N/A', 'N/A'),
]

RHYTHM_FACTOR_CHOICES = [
    ('Positive', 'Positive'), ('Negative', 'Negative'), ('Unknown', 'Unknown'),('Awaiting Result', 'Awaiting Result'),
]

OTHER_CHOICES = [
    ('N/A', 'N/A'),('Myomectomy', 'Myomectomy'), ('Removal of Septum', 'Removal of Septum'), ('Cone Biopsy', 'Cone Biopsy'),('Classical CS', 'Classical CS'),('Cervical Cerclage', 'Cervical Cerclage'),('Others', 'Others'),
]
class AntenatalVisit(models.Model):
    """Represents a single Antenatal Care (ANC) Journey / Pregnancy Episode for a patient."""
    STATUS_ACTIVE = 'active'
    STATUS_COMPLETED = 'completed'
    JOURNEY_STATUS_CHOICES = [
        (STATUS_ACTIVE, 'Active'),
        (STATUS_COMPLETED, 'Completed'),
    ]

    OUTCOME_CHOICES = [
        ('live_birth', 'Live Birth / Delivery Completed'),
        ('miscarriage', 'Miscarriage / Spontaneous Abortion'),
        ('stillbirth', 'Stillbirth / Intrauterine Fetal Demise'),
        ('termination', 'Medical Termination of Pregnancy'),
        ('ectopic', 'Ectopic Pregnancy'),
        ('transferred', 'Transferred Out'),
        ('discontinued', 'Discontinued / Lost to Follow-up'),
        ('other', 'Other'),
    ]

    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='antenatal_visits')
    visit_date = models.DateField(default=timezone.now)
    status = models.CharField(max_length=20, choices=JOURNEY_STATUS_CHOICES, default=STATUS_ACTIVE, db_index=True)
    journey_number = models.PositiveIntegerField(default=1)
    booking_completed = models.BooleanField(default=False)
    booking_completed_at = models.DateTimeField(null=True, blank=True)
    outcome = models.CharField(max_length=30, choices=OUTCOME_CHOICES, null=True, blank=True)
    outcome_date = models.DateField(null=True, blank=True)
    outcome_notes = models.TextField(null=True, blank=True)
    ended_at = models.DateTimeField(null=True, blank=True)
    ended_by = models.ForeignKey(
        'users.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='ended_anc_journeys',
    )
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)

    def get_gestational_age_weeks(self, reference_date=None):
        """Return gestational age in weeks from CurrentPregnancy LMP, ANCRegistration, or visit date."""
        if reference_date is None:
            reference_date = timezone.localdate()

        # 1. Check CurrentPregnancy LMP
        preg = getattr(self, 'current_pregnancy', None)
        if preg and preg.last_menstrual_period:
            return preg.calculate_gestational_age(reference_date)

        # 2. Check related ANCRegistration LMP
        reg = self.registrations.filter(last_menstrual_period__isnull=False).order_by('-id').first()
        if reg and reg.last_menstrual_period:
            delta = reference_date - reg.last_menstrual_period
            return max(0, delta.days // 7)

        # 3. Fallback: duration from visit_date or created_at
        start_date = self.visit_date or (self.created_at.date() if self.created_at else None)
        if start_date:
            delta = reference_date - start_date
            return max(0, delta.days // 7)

        return 0

    def check_and_auto_end_if_expired(self, reference_date=None):
        """
        Automatically end/complete this ANC Journey if gestational age reaches or exceeds 52 weeks
        (1 full year from LMP / episode inception).
        """
        if self.status != self.STATUS_ACTIVE:
            return False

        weeks = self.get_gestational_age_weeks(reference_date)
        if weeks is not None and weeks >= 52:
            ref = reference_date or timezone.localdate()
            preg = getattr(self, 'current_pregnancy', None)
            lmp = preg.last_menstrual_period if preg else None

            # Outcome date defaults to ~40 weeks (EDD) or reference date
            outcome_dt = (lmp + timedelta(days=280)) if lmp else (self.visit_date + timedelta(days=280) if self.visit_date else ref)
            if outcome_dt > ref:
                outcome_dt = ref

            self.status = self.STATUS_COMPLETED
            self.outcome = 'live_birth'
            self.outcome_date = outcome_dt
            self.outcome_notes = f"Auto-ended: Antenatal journey reached {weeks} weeks (maximum 52-week clinical gestation threshold)."
            self.ended_at = timezone.now()
            self.save(update_fields=['status', 'outcome', 'outcome_date', 'outcome_notes', 'ended_at'])

            # Close associated active registrations
            self.registrations.filter(status='active').update(status='completed')
            return True

        return False

    @classmethod
    def auto_end_all_expired_journeys(cls):
        """Scans all active ANC journeys across the system and auto-completes those reaching 52+ weeks."""
        active_visits = cls.objects.filter(status=cls.STATUS_ACTIVE).select_related('current_pregnancy')
        ended_count = 0
        for v in active_visits:
            if v.check_and_auto_end_if_expired():
                ended_count += 1
        return ended_count

    @classmethod
    def get_active_for_patient(cls, patient):
        """Return the patient's currently active ANC Journey, if any (strictly female patients only)."""
        if not patient:
            return None
        gender = getattr(patient, 'gender', '') or ''
        if str(gender).strip().lower() != 'female':
            return None

        active_visit = (
            cls.objects.filter(patient=patient, status=cls.STATUS_ACTIVE)
            .select_related('current_pregnancy')
            .order_by('-visit_date', '-id')
            .first()
        )
        if active_visit:
            # Check if this journey reached 52 weeks and should be auto-ended
            if active_visit.check_and_auto_end_if_expired():
                return None
        return active_visit

    @classmethod
    def get_active_anc_weeks_label(cls, patient):
        """Return gestational age label ('week N') only when an active ANC journey exists."""
        active_visit = cls.get_active_for_patient(patient)
        if not active_visit:
            return ""
        pregnancy_instance = getattr(active_visit, 'current_pregnancy', None)
        if pregnancy_instance and pregnancy_instance.last_menstrual_period:
            gest_age = pregnancy_instance.calculate_gestational_age()
            return f"week {gest_age}"
        return ""

    def has_completed_booking(self):
        """Determine whether First Consultation Booking is completed for this ANC Journey."""
        if self.booking_completed:
            return True
        if self.registrations.filter(completed=True).exists():
            return True
        preg = getattr(self, 'current_pregnancy', None)
        if preg and preg.last_menstrual_period:
            return True
        return False

    def __str__(self):
        status_label = self.get_status_display()
        if self.patient:
            return f"ANC Journey #{self.journey_number} ({status_label}) - {self.patient.surname} on {self.visit_date}"
        return f"Antenatal Visit on {self.visit_date} (ID: {self.id})"

# --- 1. Obstetric History ---
class ObstetricHistory(models.Model):
    visit = models.OneToOneField(AntenatalVisit, on_delete=models.CASCADE, null=True, related_name='obstetric_history')
    is_first_pregnancy = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    history_spontaneous_abortions = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    birthweight_gt_4500g = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    previous_caesarean_section = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    previous_surgery_reproductive_tract = models.CharField(max_length=100, null=True, choices=OTHER_CHOICES, default='N/A') # Text field for 'Others'
    age_gt_40_years = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    vaginal_bleeding = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    diastolic_bp_gt_90 = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    family_history_twins = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    previous_stillbirth_neonatal_loss = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    birthweight_lt_2500g = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    last_pregnancy_hospital_admission = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    multiple_pregnancy = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    age_lt_16_years = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    isoimmunization_rh = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    pelvic_mass = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    insulin_dependent_diabetes = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)

    def __str__(self):
        if self.visit and self.visit.patient:
            return f"Obstetric History for {self.visit.patient.surname}"
        return f"Obstetric History (ID: {self.id}) - No patient associated"

# --- 2. Current Pregnancy ---
class CurrentPregnancy(models.Model):
    visit = models.OneToOneField(AntenatalVisit, on_delete=models.CASCADE, null=True, related_name='current_pregnancy')
    last_menstrual_period = models.DateField(null=True, blank=True)
    gestational_age_weeks = models.IntegerField(null=True, blank=True)
    expected_date_of_delivery = models.DateField(null=True, blank=True)
    number_of_foetus = models.IntegerField(default=1) # Assuming minimum 1
    gestational_period_from_ultrasound = models.BooleanField(default=False)
    bleeding = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    vomiting = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    oedema = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    placenta_previa = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    blurred_vision = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    breathlessness = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    discharge = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    history_of_present_pregnancy = models.TextField(null=True, blank=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)


    def __str__(self):
        if self.visit and self.visit.patient:
            return f"Current Pregnancy for {self.visit.patient.surname}"
        return f"Current Pregnancy (ID: {self.id}) - No patient associated"

    def calculate_gestational_age(self, reference_date=None):
        """Calculates gestational age in weeks based on LMP and a reference date."""
        if not self.last_menstrual_period:
            return None
        
        if reference_date is None:
            reference_date = timezone.localdate() 

        delta = reference_date - self.last_menstrual_period
        gestational_weeks = delta.days // 7
        return max(0, gestational_weeks) # Ensure it's not negative

    def calculate_edd(self):
        """Calculates Expected Date of Delivery (280 days from LMP)."""
        if not self.last_menstrual_period:
            return None
        return self.last_menstrual_period + timedelta(days=280)

    # Keep the save method for historical saving logic
    def save(self, *args, **kwargs):
        # Update gestational_age_weeks field with age at visit date or current date if visit date is not set
        if self.last_menstrual_period and not self.gestational_period_from_ultrasound:
            reference_date_for_save = self.visit.visit_date if self.visit and self.visit.visit_date else timezone.localdate()
            self.gestational_age_weeks = self.calculate_gestational_age(reference_date=reference_date_for_save)
            self.expected_date_of_delivery = self.calculate_edd()
        super().save(*args, **kwargs)

# --- 3. General Medical ---
class GeneralMedical(models.Model):
    visit = models.OneToOneField(AntenatalVisit, on_delete=models.CASCADE, null=True, related_name='general_medical')
    known_substance_abuse = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    # Previous Medical History
    severe_anaemia = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    sickle_cell_disease = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    hypertension = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    diabetes_mellitus = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    cardiac_disease = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    chronic_cough_tuberculosis = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    breast_cancer = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    liver_disease_jaundice = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    gall_bladder_disease = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    thyroid_disease = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    renal_disease = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    epilepsy = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    peptic_ulcer_disease = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    asthma = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    others_medical_history = models.TextField(null=True, blank=True)
    family_history = models.TextField(null=True, blank=True) 
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)

    def __str__(self):
        if self.visit and self.visit.patient:
            return f"General Medical for {self.visit.patient.surname}"
        return f"General Medical (ID: {self.id}) - No patient associated"

# --- 4. Tests ---
class LabTests(models.Model):
    visit = models.OneToOneField(AntenatalVisit, on_delete=models.CASCADE, null=True, related_name='tests')

    # Lab Test Results
    vdrl = models.CharField(max_length=20, default='Awaiting Result',choices=RHYTHM_FACTOR_CHOICES) 
    hiv = models.CharField(max_length=20, default='Negative', choices=RHYTHM_FACTOR_CHOICES)
    blood_group = models.CharField(max_length=30, choices=BLOOD_GROUP_CHOICES, default='Unknown')
    genotype = models.CharField(max_length=30, choices=GENOTYPE_CHOICES, default='Unknown')
    hepatitis_b = models.CharField(max_length=20, default='Negative', choices=RHYTHM_FACTOR_CHOICES)
    hepatitis_c = models.CharField(max_length=20, default='Negative', choices=RHYTHM_FACTOR_CHOICES)
    rhesus_factor = models.CharField(max_length=20, default='Negative', choices=RHYTHM_FACTOR_CHOICES)
    hb = models.DecimalField(max_digits=4, decimal_places=2, null=True, blank=True) # Hemoglobin
    urine_protein = models.CharField(max_length=20, default='Negative') 
    urine_glucose = models.CharField(max_length=20, default='Negative') 
    pregnancy_test = models.CharField(max_length=20, default='Positive') 
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)


    def __str__(self):
        if self.visit and self.visit.patient:
            return f"Lab Tests for {self.visit.patient.surname}"
        return f"Lab Tests (ID: {self.id}) - No patient associated"


# Profile/Subsequent Visits


YES_NO = (
    ("Yes", "Yes"),
    ("No", "No"),
)
URINE_ATTR = (
    ("Negative", "Negative"), ("Trace", "Trace"), ("Positive +", "Positive +"), ("Positive ++", "Positive ++"), ("Positive +++", "Positive +++"),  
)

FOETAL_HEART = (
    ("Foetal heart heard(FHH)", "Foetal heart heard(FHH)"), ("Mutiple foetal heart heard (MFHH)", "Mutiple foetal heart heard (MFHH)"), ("mutiple foetal heart not heard (MFHNH)", "mutiple foetal heart not heard (MFHNH)"),  
)

FOETAL_MOVEMENT = (
    ("Foetal movement felt (FMF)", "Foetal movement felt (FMF)"), ("Foetal movement not felt (FMNF)", "Foetal movement not felt (FMNF)"), ("Multiple foetal movement felt (MFMF)", "Multiple foetal movement felt (MFMF)"),  
)

FOETAL_PRESENTATION = (
    ("N/A", "N/A"), ("Cephalic", "Cephalic"), ("Breech", "Breech"), ("Transperse", "Transperse"), ("Oblique", "Oblique"),  
)

POSITION = (
    ("N/A", "N/A"), ("Right Occiput Anterior", "Right Occiput Anterior"), ("Right Occiput Transperse", "Right Occiput Transperse"), ("Right Occiput Posterior", "Right Occiput Posterior"), ("Left Occiput Anterior", "Left Occiput Anterior"), ("Left Occiput Transperse", "Left Occiput Transperse"), ("Left Occiput Posterior", "Left Occiput Posterior"),  
)

VAGINA_POSITION = (
    ("Normal", "Normal"), ("Spotting", "Spotting"), ("Discharge", "Discharge"), ("Bleeding", "Bleeding"), ("Warts", "Warts"),  
)
class ANCDetails(models.Model):
    patient = models.OneToOneField(
        'patients.PatientProfile',
        on_delete=models.CASCADE,
        related_name="anc_details"
    )

    # ================= INVESTIGATIONS =================
    syphilis_test_done = models.CharField(max_length=3, choices=YES_NO, blank=True)
    syphilis_positive = models.CharField(max_length=3, choices=YES_NO, blank=True)
    syphilis_treated = models.CharField(max_length=3, choices=YES_NO, blank=True)
    hepatitis_b_test_done = models.CharField(max_length=3, choices=YES_NO, blank=True)
    hepatitis_b_positive = models.CharField(max_length=3, choices=YES_NO, blank=True)
    hepatitis_b_referred = models.CharField(max_length=3, choices=YES_NO, blank=True)
    hepatitis_c_test_done = models.CharField(max_length=3, choices=YES_NO, blank=True)
    hepatitis_c_positive = models.CharField(max_length=3, choices=YES_NO, blank=True)
    hepatitis_c_referred = models.CharField(max_length=3, choices=YES_NO, blank=True)
    severe_anaemia = models.CharField(max_length=3, choices=YES_NO, blank=True)
    proteinuria = models.CharField(max_length=3, choices=YES_NO, blank=True)
    # ================= TREATMENT =================
    received_tt = models.CharField(max_length=3, choices=YES_NO, blank=True)
    family_planning_counseled = models.CharField(max_length=3, choices=YES_NO, blank=True)
    received_llin = models.CharField(max_length=3, choices=YES_NO, blank=True)
    malaria_ipt1 = models.CharField(max_length=3, choices=YES_NO, blank=True)
    malaria_ipt2 = models.CharField(max_length=3, choices=YES_NO, blank=True)
    malaria_ipt3 = models.CharField(max_length=3, choices=YES_NO, blank=True)
    maternal_nutrition_counseled = models.CharField(max_length=3, choices=YES_NO, blank=True)
    haematinics_received = models.CharField(max_length=3, choices=YES_NO, blank=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"ANC Details - {self.patient}"

class Examination(models.Model):
    weight = models.CharField(null=True, max_length=50, blank=True)
    bp = models.CharField(null=True, max_length=50, blank=True)
    temperature = models.CharField(null=True, max_length=50, blank=True)
    pulse_rate = models.CharField(null=True, max_length=50, blank=True) 
    oedema = models.CharField(max_length=50, choices=YES_NO_CHOICES, default='No')
    urine_protein = models.CharField(max_length=60, choices=URINE_ATTR, default='Negative')
    urine_sugar = models.CharField(max_length=60, choices=URINE_ATTR, default='Negative')
    foetal_heart = models.CharField(max_length=50, choices=FOETAL_HEART, default='Foetal heart heard(FHH)')
    foetal_heart_rate = models.CharField(max_length=50, null=True)
    foetal_presentation = models.CharField(max_length=50, choices=FOETAL_PRESENTATION, default='N/A')
    foetal_movement = models.CharField(max_length=50, choices=FOETAL_MOVEMENT, default='Foetal movement felt (FMF)')
    position = models.CharField(max_length=50, choices=POSITION, default='N/A')
    relationship_of_pp_to_brim = models.CharField(max_length=50, choices=RELATIONSHIP2PP_CHOICES, default='N/A')
    condition_of_vagina = models.CharField(max_length=50, choices=VAGINA_POSITION, default='Normal')
    pvc = models.CharField(null=True, max_length=50, blank=True)
    comment = models.TextField(null=True, max_length=60, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    antenatal_visit = models.ForeignKey(
        AntenatalVisit,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='examinations',
    )
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.SET_NULL, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, db_index=True)
    class Meta:
        ordering = ['created_date']

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name} {self.created_date}'
