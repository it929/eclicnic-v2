from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.core.validators import EmailValidator
from ANC.models import AntenatalVisit


class BackgroundHealth(models.Model):
    hypertension = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    asthma = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    diabetics = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    epilepsy = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    tuberculosis = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    sickle_cell = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    stroke = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    eye_problem = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    kidney_problem = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    liver_problem = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    mental_illness = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    cancer = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    allergies = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    latex = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    drugs = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    surgical_operation = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    blood_transfution = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")


class PatientBackgroundHealth(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    status = models.PositiveIntegerField(default=0)
    hypertension = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    asthma = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    diabetics = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    epilepsy = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    tuberculosis = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    sickle_cell = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    stroke = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    eye_problem = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    kidney_problem = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    liver_problem = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    mental_illness = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    cancer = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    allergies = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    latex = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    drugs = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    surgical_operation = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    blood_transfution = models.CharField(null=True,max_length=10, choices=(("Yes","Yes"), ("No","No")),  default="No")
    created_date = models.DateTimeField(auto_now_add=True, null=True, db_index=True)

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name}'
    

class RegFee(models.Model):
    plan_name =  models.CharField(null=True,max_length=50,unique=True) 
    price = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.plan_name}"
    
class GetRegistrationFee(models.Model):
    price = models.PositiveIntegerField(default=0)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.SET_NULL, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE)
    completed = models.PositiveIntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return f'registration fee for {self.patient.surname} is {self.price}'
    
class AntenatalFee(models.Model):
    price = models.PositiveIntegerField(default=0)
    completed = models.PositiveIntegerField(default=0)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True) 
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Antenatal fees for {self.patient.surname} {self.patient.first_name} is {self.price}"
    
    
class VisitPurpose(models.Model):
    purpose = models.CharField(null=True, max_length=150)
    price = models.PositiveIntegerField(default=0)
    specialist_id = models.PositiveIntegerField(default=0)
    sponsor = models.ForeignKey('patients.Sponsor', on_delete=models.CASCADE, null=True, blank=True, related_name='visit_purposes')
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True, blank=True, related_name='visit_purposes')
    created_date = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ['purpose', 'sponsor__name', 'plan__plan']

    def __str__(self):
        sponsor_str = f" [{self.sponsor.name}]" if self.sponsor else " [General]"
        plan_str = f" - {self.plan.plan}" if self.plan else ""
        return f"{self.purpose}{sponsor_str}{plan_str} - ₦{self.price}"
class NurseWaitingList(models.Model):
    VISIT_TYPE_CHOICES = [
        ("", "--Select Visit Type--"), 
        ("New-case", "New Case"),
        ("Follow-up", "Follow-up"),
        ("Review", "Review"),
    ]
    attendant = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.SET_NULL, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True)
    waiting_status = models.PositiveIntegerField(default=0)
    purpose = models.CharField(max_length=150, null=True)
    price = models.PositiveIntegerField(default=0)
    visit_type = models.CharField(max_length=18, choices=VISIT_TYPE_CHOICES, default="", null=True)
    critical_request = models.PositiveIntegerField(default=0)
    completed_by  = models.CharField(max_length=32, null=True, blank=True)
    exception_bill = models.BooleanField(default=False)
    completed = models.PositiveIntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    class Meta:
        ordering = ['critical_request','created_date']  
        indexes = [
            models.Index(fields=['category', 'patient', 'created_date']),  
        ]

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name} ---  {self.created_date}'

# patient's vital signs for doctor's waiting list
class DoctorWaitingList(models.Model):
    height = models.FloatField(null=True, blank=True)
    unit = models.CharField(null=True, max_length=2, blank=True, default='cm')
    weight = models.FloatField(null=True, blank=True)
    bp = models.CharField(null=True, max_length=12, blank=True)
    bmi = models.FloatField(null=True, blank=True)
    temperature = models.FloatField(null=True, blank=True)
    respiratory_rate = models.FloatField(null=True, blank=True) 
    urine_ph = models.FloatField(null=True, blank=True)
    sp_02 = models.FloatField(null=True, blank=True)
    oxygen_volume = models.FloatField(null=True, blank=True)
    urine_glucose = models.FloatField(null=True, blank=True)
    blood_glucose = models.FloatField(null=True, blank=True)
    urine_protein = models.FloatField(null=True, blank=True)
    pulse = models.IntegerField(null=True, blank=True)
    purpose = models.CharField(max_length=32, null=True)
    comment = models.TextField(null=True, max_length=60, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.SET_NULL, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    encounter_status = models.PositiveIntegerField(default=0)
    waiting_status = models.PositiveIntegerField(default=0)
    critical_request = models.PositiveIntegerField(default=0)
    completed_by = models.CharField(max_length=32, null=True, blank=True)
    completed = models.PositiveIntegerField(default=0, db_index=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, db_index=True)
    class Meta:
        ordering = ['-critical_request','created_date']

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name} {self.created_date}'

    def save(self, *args, **kwargs):
        if self.height is not None and self.weight is not None:
            if self.unit =='cm':
                self.bmi = round((float(self.weight)/((float(self.height)/100)*(float(self.height)/100))),2)
            else:
                self.bmi = round((float(self.weight)/(float(self.height) * float(self.height))),2)
        else:  
            self.bmi = 0
        return super().save(*args, **kwargs)


class Transcript(models.Model):
    content = models.TextField()
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)


class ICD11Category(models.Model):
    code = models.CharField(max_length=10, unique=True)
    title = models.TextField()
    description = models.TextField(blank=True, null=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    level = models.IntegerField(default=0)
    
    class Meta:
        verbose_name_plural = "ICD-11 Categories"
    
    def __str__(self):
        return f"{self.code} - {self.title}"

class ICD11Code(models.Model):
    code = models.CharField(max_length=15, unique=True)
    title = models.TextField()
    description = models.TextField(blank=True, null=True)
    category = models.ForeignKey(ICD11Category, on_delete=models.CASCADE, related_name='codes')
    foundation_uri = models.URLField(blank=True, null=True)
    linearization_uri = models.URLField(blank=True, null=True)
    
    # Additional metadata
    is_leaf = models.BooleanField(default=True)
    inclusion_terms = models.TextField(blank=True, null=True)
    exclusion_terms = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name_plural = "ICD-11 Codes"
    
    def __str__(self):
        return f"{self.code} - {self.title}"


class Diagnosis(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='diagnoses')
    icd11_code = models.ForeignKey(ICD11Code, on_delete=models.PROTECT, related_name='diagnoses')
    diagnosis_date = models.DateField()
    confirmed = models.BooleanField(default=False)
    primary_diagnosis = models.BooleanField(default=False)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name_plural = "Diagnoses"
        ordering = ['-diagnosis_date', '-primary_diagnosis']
    
    def __str__(self):
        return f"{self.patient.patient_id} - {self.icd11_code.code}"
    
class PatientDiagnosis(models.Model):
    category = models.CharField(max_length=50)
    description = models.CharField(max_length=255) 
    icd10_code = models.CharField(max_length=10, blank=True, null=True, default='')
    icd11_code = models.CharField(max_length=20, blank=True, null=True, default='')
    is_active = models.BooleanField(default=True)
    class Meta:
        ordering = ['category', 'description']

    def __str__(self):
        return f" {self.description}"

    

class PresentingComplaint(models.Model):
    CATEGORY_CHOICES = [
        ('general', 'General / Constitutional'),
        ('neurological', 'Neurological'),
        ('cardiovascular', 'Cardiovascular & Respiratory'),
        ('gastrointestinal', 'Gastrointestinal'),
        ('musculoskeletal', 'Musculoskeletal'),
        ('genitourinary', 'Genitourinary & Gynecological'),
        ('ent', 'ENT & Dental'),
        ('dermatological', 'Dermatological'),
        ('psychiatric', 'Psychiatric / Behavioral Health'),
        ('eye', 'Eye & Vision'),
        ('endocrine', 'Endocrine / Metabolic'),
        ('pediatric', 'Pediatric-Specific'),
        ('administrative', 'Administrative / Non-Acute'),
    ]
    
    name = models.CharField(max_length=255)
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['category', 'name']
    
    def __str__(self):
        return f"{self.get_category_display()} - {self.name}"

class PatientEncounter(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE)
    provider = models.ForeignKey('users.User', on_delete=models.CASCADE)
    chief_complaint = models.CharField(max_length=500,null=True, blank=True)
    history_of_present_illness = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    diagnosis = models.CharField(max_length=500, blank=True, null=True)
    comments_on_diagnosis = models.TextField(blank=True, null=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)

    def is_editable(self):
        """Check if encounter can be edited (within 24 hours)"""
        time_diff = timezone.now() - self.created_at
        return time_diff < timedelta(hours=24)
    
    def calculate_anc_weeks(self):
        """
        Get gestational age from AntenatalVisit
        """
        if not self.patient:
            return ""

        return AntenatalVisit.get_active_anc_weeks_label(self.patient)
    def save(self, *args, **kwargs):
        
        self.anc_weeks = self.calculate_anc_weeks()
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.patient} - {self.diagnosis}"

class PatientReferral(models.Model):
        # referrer
    referring_clinic = models.CharField(max_length=255, blank=True, null=True)
    referrer_phone = models.CharField(max_length=20, blank=True, null=True)
    referrer_address = models.TextField(blank=True, null=True)
    referring_physician = models.CharField(max_length=255, blank=True, null=True)
    referrer_email = models.EmailField(blank=True, null=True, validators=[EmailValidator()])
    # External Referral Information
    clinic_referred_to = models.CharField(max_length=255, blank=True, null=True)
    referred_to_phone = models.CharField(max_length=20, blank=True, null=True)
    referred_to_address = models.TextField(blank=True, null=True)
    physician_referred_to = models.CharField(max_length=255, blank=True, null=True)
    referred_to_email = models.EmailField(blank=True, null=True, validators=[EmailValidator()])
    # Internal Referral Information
    referred_department_clinic = models.CharField(max_length=255, blank=True, null=True)
    refer_to_clinician = models.CharField(max_length=255, blank=True, null=True)
    reason_for_referring = models.TextField(blank=True, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE)
    provider = models.ForeignKey('users.User', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        verbose_name = "Referral"
        verbose_name_plural = "Referrals"
    def __str__(self):
        return f"{self.patient} - {self.provider}"
    
    def is_editable(self):
        """Check if referral can be edited (within 24 hours)"""
        time_diff = timezone.now() - self.created_at
        return time_diff < timedelta(hours=24)


class PatientFollowUp(models.Model):
    summary_notes = models.TextField(blank=True, null=True)
    # follow up
    visit_type = models.CharField(max_length=50, null=True, blank=True)
    treatment_progress = models.CharField(max_length=50, null=True, blank=True)
    drugs_compliance = models.CharField(max_length=50, null=True, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE)
    provider = models.ForeignKey('users.User', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient} - {self.provider}"
    
    def is_editable(self):
        """Check if follow-up can be edited (within 24 hours)"""
        time_diff = timezone.now() - self.created_at
        return time_diff < timedelta(hours=24)
    

class PatientOtherDetails(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE)
    provider = models.ForeignKey('users.User', on_delete=models.CASCADE)
    condition_status = models.CharField(max_length=500,null=True, blank=True)
    to_be_admitted = models.CharField(max_length=500,null=True, blank=True)
    assigned_doctor = models.CharField(max_length=500,null=True, blank=True)
    be_referred_out = models.CharField(max_length=500,null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.patient} - {self.provider}"
    
    def is_editable(self):
        """Check if other details can be edited (within 24 hours)"""
        time_diff = timezone.now() - self.created_at
        return time_diff < timedelta(hours=24)
    
class OtherService(models.Model):
    provider = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.SET_NULL, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.SET_NULL, null=True)
    waiting_status = models.PositiveIntegerField(default=0)
    purpose = models.CharField(max_length=150, null=True)
    price = models.PositiveIntegerField(default=0)
    exception_bill = models.BooleanField(default=False)
    completed = models.PositiveIntegerField(default=0)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    class Meta:
        ordering = ['-created_date']  
    
    def calculate_anc_weeks(self):
        """
        Get gestational age from AntenatalVisit
        """
        if not self.patient:
            return ""

        return AntenatalVisit.get_active_anc_weeks_label(self.patient)

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name} ---  {self.created_date}'
    

class TransactionTb(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    status = models.PositiveIntegerField(default=0)


class WrittenPrescriptions(models.Model):
    item = models.CharField(null=True, max_length=200)
    instruction = models.TextField(null=True, blank=True)
    quantity = models.PositiveIntegerField(default=0)
    dosage_form = models.CharField(max_length=50, null=True, blank=True)
    route = models.CharField(max_length=60, null=True, blank=True)
    strength = models.CharField(max_length=100, null=True, blank=True)
    dose_qty = models.CharField(max_length=50, null=True, blank=True)
    dose_unit = models.CharField(max_length=50, null=True, blank=True)
    frequency = models.CharField(max_length=100, null=True, blank=True)
    duration = models.CharField(max_length=50, null=True, blank=True)
    duration_unit = models.CharField(max_length=50, null=True, blank=True)
    dispense_unit = models.CharField(max_length=50, null=True, blank=True)
    dispense_quantity = models.PositiveIntegerField(default=0)
    dispense_detail = models.CharField(max_length=200, null=True, blank=True)
    comment = models.CharField(max_length=255, null=True, blank=True)
    start_date = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=30, default='pending')
    dispensed_at = models.DateTimeField(null=True, blank=True)
    dispensed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='dispensed_prescriptions')
    is_anc_template = models.BooleanField(default=False, db_index=True)
    anc_template_name = models.CharField(max_length=150, null=True, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE)
    provider = models.ForeignKey('users.User', on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f'{self.dispense_detail or self.quantity} of {self.item} for {self.patient.surname} {self.patient.first_name}'


class ConsultationDraft(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='consultation_drafts')
    doctor = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    appointment = models.ForeignKey('patients.PatientAppointment', on_delete=models.SET_NULL, null=True, blank=True)
    draft_data = models.JSONField(default=dict)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-updated_at']

    def __str__(self):
        return f"Consultation Draft for {self.patient} ({self.updated_at})"


class ImmunizationRecord(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, related_name='immunizations')
    appointment = models.ForeignKey('patients.PatientAppointment', on_delete=models.SET_NULL, null=True, blank=True)
    vaccine_name = models.CharField(max_length=200)
    vaccine_code = models.CharField(max_length=50, blank=True, null=True)
    dose_stage = models.CharField(max_length=50, default='1st Dose')  # e.g. 'Birth Dose', '1st Dose', '2nd Dose', '3rd Dose', 'Booster'
    schedule_stage = models.CharField(max_length=50, blank=True, null=True)  # e.g. 'At Birth', '6 Weeks', '10 Weeks', '14 Weeks', '9 Months', etc.
    route = models.CharField(max_length=50, default='Intramuscular')  # Oral, Intramuscular, Subcutaneous, Intradermal
    site = models.CharField(max_length=100, default='Left Anterolateral Thigh')  # Left Deltoid, Right Deltoid, Left Thigh, Right Thigh, Oral
    batch_number = models.CharField(max_length=100, blank=True, null=True)
    expiry_date = models.DateField(null=True, blank=True)
    manufacturer = models.CharField(max_length=150, blank=True, null=True)
    administered_date = models.DateField(default=timezone.now)
    administered_time = models.TimeField(null=True, blank=True)
    administered_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    administered_by_name = models.CharField(max_length=150, blank=True, null=True)
    next_due_date = models.DateField(null=True, blank=True)
    fee = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    is_billable = models.BooleanField(default=False)
    payment_mode = models.CharField(max_length=50, default='free')  # 'free', 'covered', 'pay_from_purse', 'cash'

    # Pricing & billing trail (price always comes from the sponsor/plan PharmacyTariff)
    BILLING_STATUS_CHOICES = [
        ('not_billable', 'Not Billable (Free EPI)'),
        ('pending', 'Awaiting Billing / HMO Approval'),
        ('billed', 'Billed'),
    ]
    tariff_id = models.PositiveIntegerField(null=True, blank=True)
    tariff_name = models.CharField(max_length=200, blank=True, null=True)
    price_source = models.CharField(max_length=20, blank=True, null=True)  # 'plan' | 'sponsor' | 'general'
    billing_status = models.CharField(max_length=20, choices=BILLING_STATUS_CHOICES, default='not_billable', db_index=True)

    # Two-step workflow for billable vaccines:
    #   1. authorized (PIN) -> sent to billing
    #   2. after payment / HMO approval the nurse confirms the injection with their PIN
    # Free EPI vaccines are confirmed at authorization.
    authorized_by_name = models.CharField(max_length=150, blank=True, null=True)
    administration_confirmed = models.BooleanField(default=False, db_index=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)

    notes = models.TextField(blank=True, null=True)
    aefi_reported = models.BooleanField(default=False)
    aefi_notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-administered_date', '-id']

    def __str__(self):
        return f"{self.vaccine_name} ({self.dose_stage}) for {self.patient}"



class ImmunizationDrugRecord(models.Model):
    """
    Immunization clinic daily drug / vaccine register against the Central Medical Store (CMS).

    Lifecycle (one row per drug requested):
        requested       nurse asks CMS for a quantity (expected patients noted)
        in_transit      CMS issues with PIN -> central stock is deducted
        issued          clinic counts and receives it with PIN (who/when/how many) -> in use
        return_pending  nurse records usage and sends the unused balance back (PIN)
        closed          CMS receives the return with PIN -> central stock is credited back
                        (also closed directly when nothing is returned)
        rejected / cancelled
    """
    STATUS_CHOICES = [
        ('requested', 'Requested from Central Store'),
        ('in_transit', 'Issued - awaiting clinic receipt'),
        ('issued', 'Received by clinic / in use'),
        ('return_pending', 'Return Awaiting Central Store'),
        ('closed', 'Closed / Reconciled'),
        ('rejected', 'Rejected by Central Store'),
        ('cancelled', 'Cancelled'),
    ]

    reference_number = models.CharField(max_length=40, unique=True, db_index=True)
    record_date = models.DateField(default=timezone.localdate, db_index=True)
    product = models.ForeignKey('inventory.Product', on_delete=models.PROTECT, related_name='immunization_drug_records')
    product_name = models.CharField(max_length=200)
    central_store = models.ForeignKey('inventory.PharmacyStore', on_delete=models.SET_NULL, null=True, blank=True, related_name='immunization_drug_records')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='requested', db_index=True)

    # 1. Request (nurse)
    quantity_requested = models.PositiveIntegerField()
    expected_patients = models.PositiveIntegerField(default=0)
    request_notes = models.TextField(blank=True, default='')
    requested_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='imm_drug_requests')
    requested_by_name = models.CharField(max_length=150, blank=True, default='')
    requested_at = models.DateTimeField(auto_now_add=True)

    # 2. Issue (Central Store, PIN) = quantity received by the clinic
    quantity_issued = models.PositiveIntegerField(default=0)
    batch_number = models.CharField(max_length=100, blank=True, default='')
    expiry_date = models.DateField(null=True, blank=True)
    issued_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='imm_drug_issues')
    issued_by_name = models.CharField(max_length=150, blank=True, default='')
    issued_at = models.DateTimeField(null=True, blank=True)
    store_notes = models.TextField(blank=True, default='')

    # 2b. Receipt by the requesting section (PIN): what physically arrived
    quantity_received = models.PositiveIntegerField(default=0)
    received_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='imm_drug_receipts')
    received_by_name = models.CharField(max_length=150, blank=True, default='')
    received_at = models.DateTimeField(null=True, blank=True)
    receipt_notes = models.TextField(blank=True, default='')

    # 3. Usage (nurse)
    quantity_used = models.PositiveIntegerField(default=0)
    patients_served = models.PositiveIntegerField(default=0)
    usage_notes = models.TextField(blank=True, default='')

    # 4. Return to Central Store (nurse, PIN)
    quantity_returned = models.PositiveIntegerField(default=0)
    returned_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='imm_drug_returns')
    returned_by_name = models.CharField(max_length=150, blank=True, default='')
    returned_at = models.DateTimeField(null=True, blank=True)

    # 5. Return received by Central Store (PIN) -> central stock credited
    quantity_return_received = models.PositiveIntegerField(default=0)
    return_received_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='imm_drug_return_receipts')
    return_received_by_name = models.CharField(max_length=150, blank=True, default='')
    return_received_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-record_date', '-id']

    def __str__(self):
        return f"{self.reference_number} {self.product_name} ({self.get_status_display()})"

    @property
    def unaccounted(self):
        """Received quantity not used and not returned (wastage / open-vial loss / missing)."""
        if self.status in ('requested', 'in_transit', 'rejected', 'cancelled'):
            return 0
        return max(0, int(self.quantity_received) - int(self.quantity_used) - int(self.quantity_returned))

    @property
    def transit_shortfall(self):
        """Issued by the store but not received by the clinic (lost between the two)."""
        if self.status in ('requested', 'in_transit', 'rejected', 'cancelled'):
            return 0
        return max(0, int(self.quantity_issued) - int(self.quantity_received))

    @property
    def on_hand(self):
        """Still held by the clinic while the record is open."""
        if self.status != 'issued':
            return 0
        return max(0, int(self.quantity_received) - int(self.quantity_used))
