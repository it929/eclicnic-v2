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
    price = models.PositiveIntegerField(default=0)
    creator = models.ForeignKey('users.User', on_delete=models.CASCADE)
    def __str__(self):
        return f'price updated by {self.creator.fullname}'
    
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
    purpose = models.CharField(null=True, max_length=50)
    price = models.PositiveIntegerField(default=0)
    specialist_id = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f'{self.purpose} - {self.price}'
     
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
    icd10_code = models.CharField(max_length=10)
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

        antenatal_visit = AntenatalVisit.objects.filter(
            patient=self.patient
        ).select_related('current_pregnancy').first()
        if antenatal_visit:
            pregnancy_instance = getattr(
                antenatal_visit,
                'current_pregnancy',
                None
            )
            if pregnancy_instance and pregnancy_instance.last_menstrual_period:
                gest_age = pregnancy_instance.calculate_gestational_age()
                return f"week {gest_age}"
        return ""
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

        antenatal_visit = AntenatalVisit.objects.filter(
            patient=self.patient
        ).select_related('current_pregnancy').first()
        if antenatal_visit:
            pregnancy_instance = getattr(
                antenatal_visit,
                'current_pregnancy',
                None
            )
            if pregnancy_instance and pregnancy_instance.last_menstrual_period:
                gest_age = pregnancy_instance.calculate_gestational_age()
                return f"week {gest_age}"
        return ""

    def __str__(self):
        return f'{self.patient.surname} {self.patient.other_name} {self.patient.first_name} ---  {self.created_date}'
    

class TransactionTb(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.SET_NULL, null=True)
    status = models.PositiveIntegerField(default=0)


class WrittenPrescriptions(models.Model):
    item = models.CharField(null=True, max_length=60)
    instruction = models.TextField(null=True)
    quantity = models.PositiveIntegerField(default=0)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE)
    provider = models.ForeignKey('users.User', on_delete=models.CASCADE)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.quantity} units of {self.item} for {self.patient.surname} {self.patient.first_name}'
