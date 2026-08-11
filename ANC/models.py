from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import datetime, date, timedelta
from dateutil.relativedelta import relativedelta


class ANCRegistration(models.Model):
    """Main ANC Registration model"""
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='anc_registrations')
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
]

GENOTYPE_CHOICES = [
    ('AA', 'AA'), ('AS', 'AS'), ('SS', 'SS'), ('AC', 'AC'), ('CC', 'CC'), ('Unknown', 'Unknown'),
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
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='antenatal_visits')
    visit_date = models.DateField(default=timezone.now)

    def __str__(self):
        if self.patient:
            return f"Antenatal Visit for {self.patient.surname} on {self.visit_date}"
        return f"Antenatal Visit on {self.visit_date} (ID: {self.id})"

# --- 1. Obstetric History ---
class ObstetricHistory(models.Model):
    visit = models.OneToOneField(AntenatalVisit, on_delete=models.CASCADE, null=True, related_name='obstetric_history')
    is_first_pregnancy = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    history_spontaneous_abortions = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    birthweight_gt_4500g = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    previous_caesarean_section = models.CharField(max_length=3, choices=YES_NO_CHOICES, default='No')
    previous_surgery_reproductive_tract = models.CharField(max_length=20, null=True, choices=OTHER_CHOICES, default='N/A') # Text field for 'Others'
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
    blood_group = models.CharField(max_length=8, choices=BLOOD_GROUP_CHOICES, default='Unknown')
    genotype = models.CharField(max_length=8, choices=GENOTYPE_CHOICES, default='Unknown')
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
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.SET_NULL, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, db_index=True)
    class Meta:
        ordering = ['created_date']

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name} {self.created_date}'