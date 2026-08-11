from django.db import models
from django.utils import timezone
from datetime import timedelta
from django.db.models import Q
from datetime import date
from django.dispatch import receiver
from IPD.models import AdmissionTable
from ANC.models import AntenatalVisit

class PatientCategory(models.Model):
    category = models.CharField(max_length=100, unique=True, null=True)

    def __str__(self):
        return self.category
    
class PatientPlan(models.Model):
    plan = models.CharField(max_length=100, null=True)
    code = models.CharField(max_length=100, null=True)
    category = models.ForeignKey(PatientCategory, on_delete=models.CASCADE, related_name='plans', null=True)

    def __str__(self):
        return self.plan
    
class PatientProfile(models.Model):
    GENDER_CHOICES = [
        ("", "--Select Gender--"),
        ("Female", "Female"),
        ("Male", "Male"),

    ]
    PATIENT_TYPE_CHOICES = [
        ("", "--Select Marital Status--"),
        ("Married", "Married"),
        ("Single", "Single"),
        ("Others", "Others"),
    ]
    surname = models.CharField(max_length=100,db_index=True)
    first_name = models.CharField(max_length=100,db_index=True)
    other_name = models.CharField(max_length=100, blank=True, null=True)
    dob = models.DateField()
    gender = models.CharField(max_length=18, choices=GENDER_CHOICES, default="")
    patient_type = models.CharField(max_length=18, choices=PATIENT_TYPE_CHOICES, default="", blank=True)
    phone_number = models.CharField(max_length=100, db_index=True)
    address = models.TextField(null=True)
    category = models.ForeignKey(PatientCategory, on_delete=models.SET_NULL, null=True,db_index=True)
    plan = models.ForeignKey(PatientPlan, on_delete=models.SET_NULL, null=True)
    email_address = models.EmailField(unique=True, null=True)
    hospital_number = models.CharField(max_length=100, null=True,db_index=True)
    full_name = models.CharField(max_length=100, null=True)
    relationship_to_patient = models.CharField(max_length=100, null=True)
    phone_numbers = models.CharField(max_length=100, null=True)
    insurance_policy_number = models.CharField(max_length=100, null=True, blank=True)
    avatar = models.ImageField(null=True, default="patient-profile/avatar.svg", upload_to="patient-profile/")
    allergies = models.TextField(null=True, blank=True)
    active = models.PositiveIntegerField(default=1, db_index=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    deactivated_date = models.DateTimeField(auto_now_add=False, null=True)
    deactivated_by = models.CharField(max_length=100, null=True)
    
    class Meta: 
        ordering = ['-created_date']

    @property
    def get_age(self):
        today = date.today()
        if self.dob:
            return today.year - self.dob.year - ((today.month, today.day) < (self.dob.month, self.dob.day))
        return None
    def is_admitted(self):
        return AdmissionTable.objects.filter(
            doctor_discharge_status=0,
            patient=self
        ).exists()
    
    def __str__(self):
        return f"{self.surname} {self.first_name} ({self.email_address})"
    
    def get_full_name(self):
        return f"{self.surname} {self.first_name} {self.other_name or ''}".strip()
        
    def get_sponsor_name(self):
            return self.plan.plan if self.plan else "N/A"
    
    
class PatientAppointment(models.Model):

    VISIT_TYPE_CHOICES = [
        ("", "--Select Visit Type--"),
        ("New-case", "New Case"),
        ("Follow-up", "Follow-up"),
        ("Review", "Review"),
        ("First visit after discharge", "First visit after discharge"),
        ("Drug-refill", "Drug refill"),
    ]
    patient = models.ForeignKey(PatientProfile, on_delete=models.SET_NULL, null=True)
    provider = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    clinician = models.CharField(max_length=40, null=True)
    purpose = models.CharField(max_length=58, null=True)
    visit_type = models.CharField(max_length=38, choices=VISIT_TYPE_CHOICES, default="")
    arrival_date = models.DateField(null=True)
    arrival_time = models.TimeField(null=True)
    comment = models.TextField(null=True, blank=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, db_index=True)
    completed = models.PositiveIntegerField(default=0)
    
    def can_modify(self):
        """Allow edit/delete within 24 hours"""
        return timezone.now() <= self.created_date + timedelta(hours=24)
    
    def __str__(self):
        return f"{self.patient} - {self.arrival_date} {self.arrival_time}"

    @property
    def is_today(self):
        return self.arrival_date == timezone.localdate()

    @property
    def is_upcoming(self):
        return self.arrival_date > timezone.localdate()

    @property
    def is_expired(self):
        now = timezone.localtime()
        return (
            self.arrival_date < timezone.localdate() or
            (self.arrival_date == timezone.localdate() and self.arrival_time < now.time())
        )
    @property
    def is_completed(self):
        return self.completed == 1
    
    @property
    def is_cancelled(self):
        return self.completed == 2
    
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

    # created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    # is_active = models.BooleanField(default=True, db_index=True)
    
    # class Meta:
    #     ordering = ['-created_date']
    #     indexes = [
    #         models.Index(fields=['is_active', 'created_date']),
    #  

    # @property
    # def is_expired(self):
    #     return timezone.now() > (self.created_date + timezone.timedelta(hours=24))
    
    # @classmethod
    # def get_active_appointments(cls):
    #     expiration_threshold = timezone.now() - timezone.timedelta(hours=24)
    #     return cls.objects.filter(
    #         is_active=True,
    #         created_date__gt=expiration_threshold
    #     )
    
    # @classmethod
    # def deactivate_expired(cls):
    #     """Mark appointments older than 24 hours as inactive"""
    #     expiration_threshold = timezone.now() - timezone.timedelta(hours=24)
    #     return cls.objects.filter(
    #         is_active=True,
    #         created_date__lte=expiration_threshold
    #     ).update(is_active=False)