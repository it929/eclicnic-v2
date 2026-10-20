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


class Sponsor(models.Model):
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, null=True, blank=True)
    category = models.ForeignKey(PatientCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='sponsors')
    created_date = models.DateTimeField(auto_now_add=True, null=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code})" if self.code else self.name


class PatientPlan(models.Model):
    plan = models.CharField(max_length=100, null=True)
    code = models.CharField(max_length=100, null=True, blank=True)
    sponsor = models.ForeignKey(Sponsor, on_delete=models.CASCADE, related_name='plans', null=True, blank=True)
    category = models.ForeignKey(PatientCategory, on_delete=models.CASCADE, related_name='plans', null=True)

    def __str__(self):
        if self.sponsor:
            return f"{self.sponsor.name} - {self.plan}"
        return self.plan or ""


def format_family_number(base_hospital_number):
    """
    Given a hospital number (e.g. 'ISLH/ISL-4572' or 'ISL-4572'),
    derives the family number 'F/ISLH/ISL-4572'.
    """
    import re
    if not base_hospital_number:
        return ""
    s = str(base_hospital_number).strip()
    if s.upper().startswith('F/'):
        s = s[2:]
    s = re.sub(r'-[A-Z]+$', '', s)
    return f"F/{s}"


class FamilyFolder(models.Model):
    FOLDER_TYPE_CHOICES = [
        ('private_folder', 'Private Family Folder'),
        ('hmo_group', 'HMO Family Group'),
    ]

    family_name = models.CharField(max_length=200, help_text="e.g. Adebayo Family")
    family_number = models.CharField(max_length=120, unique=True, db_index=True, help_text="e.g. F/ISLH/ISL-4572")
    category = models.ForeignKey(PatientCategory, on_delete=models.SET_NULL, null=True, blank=True)
    sponsor = models.ForeignKey(Sponsor, on_delete=models.SET_NULL, null=True, blank=True, help_text="HMO Sponsor if applicable")
    folder_type = models.CharField(max_length=30, choices=FOLDER_TYPE_CHOICES, default='private_folder')

    # Physical folder tracking for private families
    physical_folder_number = models.CharField(max_length=100, null=True, blank=True, help_text="Physical Folder / File Jacket No.")
    storage_location = models.CharField(max_length=150, null=True, blank=True, help_text="Filing Room / Shelf / Cabinet Location")

    principal_patient = models.ForeignKey('PatientProfile', on_delete=models.SET_NULL, null=True, blank=True, related_name='principal_for_families')
    phone_number = models.CharField(max_length=50, null=True, blank=True)
    address = models.TextField(null=True, blank=True)
    notes = models.TextField(null=True, blank=True)

    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    updated_date = models.DateTimeField(auto_now=True, null=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f"{self.family_name} ({self.family_number})"

    @property
    def member_count(self):
        if not self.pk:
            return 0
        return self.members.count()

    def get_next_letter_suffix(self):
        """Generates next letter: 0->A, 1->B, 2->C, ..., 25->Z, 26->AA, etc."""
        if not self.pk:
            return 'A'
        used = set(self.members.values_list('letter_suffix', flat=True))
        index = 0
        while True:
            suffix = ""
            n = index
            while n >= 0:
                suffix = chr(n % 26 + ord('A')) + suffix
                n = n // 26 - 1
            if suffix not in used:
                return suffix
            index += 1

    def sync_members_to_principal(self):
        """
        Ensures all members of this family folder maintain the exact same
        sponsor and plan (and category) as the Principal Member.
        """
        principal = self.principal_patient
        if not principal:
            head_member = self.members.filter(is_principal=True).first() or self.members.filter(letter_suffix='A').first()
            if head_member and head_member.patient:
                principal = head_member.patient
                self.principal_patient = principal
                self.save(update_fields=['principal_patient'])

        if not principal:
            return

        for mem in self.members.exclude(patient_id=principal.pk).select_related('patient'):
            pat = mem.patient
            if not pat:
                continue
            updated_fields = []
            if pat.sponsor_id != principal.sponsor_id:
                pat.sponsor = principal.sponsor
                updated_fields.append('sponsor')
            if pat.plan_id != principal.plan_id:
                pat.plan = principal.plan
                updated_fields.append('plan')
            if pat.category_id != principal.category_id:
                pat.category = principal.category
                updated_fields.append('category')
            if getattr(principal, 'insurance_policy_number', None) and not pat.insurance_policy_number:
                pat.insurance_policy_number = principal.insurance_policy_number
                updated_fields.append('insurance_policy_number')
            if updated_fields:
                pat.save(update_fields=updated_fields)


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
    sponsor = models.ForeignKey(Sponsor, on_delete=models.SET_NULL, null=True, blank=True)
    plan = models.ForeignKey(PatientPlan, on_delete=models.SET_NULL, null=True)
    email_address = models.EmailField(unique=True, null=True)
    hospital_number = models.CharField(max_length=100, null=True, db_index=True)
    full_name = models.CharField(max_length=100, null=True, help_text="Next of Kin Full Name (legacy)")
    relationship_to_patient = models.CharField(max_length=100, null=True, help_text="Relationship to Patient (legacy)")
    phone_numbers = models.CharField(max_length=100, null=True, help_text="Next of Kin Phone Number (legacy)")
    next_of_kin_name = models.CharField(max_length=150, null=True, blank=True, db_index=True, help_text="Next of Kin Full Name")
    next_of_kin_relationship = models.CharField(max_length=100, null=True, blank=True, help_text="Next of Kin Relationship")
    next_of_kin_phone = models.CharField(max_length=100, null=True, blank=True, help_text="Next of Kin Phone Number")
    insurance_policy_number = models.CharField(max_length=100, null=True, blank=True)
    avatar = models.ImageField(null=True, default="patient-profile/avatar.svg", upload_to="patient-profile/")
    allergies = models.TextField(null=True, blank=True)
    active = models.PositiveIntegerField(default=1, db_index=True)
    packages = models.PositiveIntegerField(default=0, blank=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    created_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True)
    family_folder = models.ForeignKey(FamilyFolder, on_delete=models.SET_NULL, null=True, blank=True, related_name='patients')
    family_member_suffix = models.CharField(max_length=10, null=True, blank=True, help_text="A, B, C...")
    deactivated_date = models.DateTimeField(auto_now_add=False, null=True, blank=True)
    deactivated_by = models.CharField(max_length=100, null=True, blank=True)
    
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
        if self.sponsor:
            return self.sponsor.name
        if self.plan and self.plan.sponsor:
            return self.plan.sponsor.name
        return self.plan.plan if self.plan else "N/A"

    def save(self, *args, **kwargs):
        # Sync next_of_kin_name and legacy full_name
        if self.next_of_kin_name and not self.full_name:
            self.full_name = self.next_of_kin_name
        elif self.full_name and not self.next_of_kin_name:
            self.next_of_kin_name = self.full_name

        # Sync next_of_kin_relationship and legacy relationship_to_patient
        if self.next_of_kin_relationship and not self.relationship_to_patient:
            self.relationship_to_patient = self.next_of_kin_relationship
        elif self.relationship_to_patient and not self.next_of_kin_relationship:
            self.next_of_kin_relationship = self.relationship_to_patient

        # Sync next_of_kin_phone and legacy phone_numbers
        if self.next_of_kin_phone and not self.phone_numbers:
            self.phone_numbers = self.next_of_kin_phone
        elif self.phone_numbers and not self.next_of_kin_phone:
            self.next_of_kin_phone = self.phone_numbers

        super().save(*args, **kwargs)

        # Propagate sponsor, plan, and category to all family members if this patient is a principal
        if self.pk:
            try:
                for fam in self.principal_for_families.all():
                    fam.sync_members_to_principal()
            except Exception:
                pass


class FamilyMember(models.Model):
    RELATIONSHIP_CHOICES = [
        ('Principal', 'Principal / Head of Family'),
        ('Spouse', 'Spouse'),
        ('Child', 'Child'),
        ('Father', 'Father'),
        ('Mother', 'Mother'),
        ('Sibling', 'Sibling'),
        ('Dependent', 'Dependent'),
        ('Other', 'Other Relative'),
    ]

    family = models.ForeignKey(FamilyFolder, on_delete=models.CASCADE, related_name='members')
    patient = models.OneToOneField(PatientProfile, on_delete=models.CASCADE, related_name='family_membership')
    letter_suffix = models.CharField(max_length=10, help_text="e.g. A, B, C...")
    assigned_hospital_number = models.CharField(max_length=120, help_text="e.g. F/ISLH/ISL-4572-A")
    original_hospital_number = models.CharField(max_length=120, null=True, blank=True)
    relationship = models.CharField(max_length=50, choices=RELATIONSHIP_CHOICES, default='Dependent')
    is_principal = models.BooleanField(default=False)
    added_date = models.DateTimeField(auto_now_add=True, null=True)
    added_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['letter_suffix']
        unique_together = [['family', 'letter_suffix']]

    def __str__(self):
        return f"{self.patient} - {self.assigned_hospital_number} ({self.letter_suffix})"
    
    
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
        return self.arrival_date < timezone.localdate() and self.completed == 0
    @property
    def is_completed(self):
        return self.completed == 1
    
    @property
    def is_cancelled(self):
        return self.completed == 2

    def has_actions_taken(self):
        """
        Check if any clinical or administrative action has already been taken
        on this appointment (such as taking vitals, queueing, consultation encounters,
        lab/radiology requests, or billing/invoices).
        If action has been taken, the appointment cannot be cancelled.
        """
        if not self.patient_id:
            return False

        if self.completed in (1, 2):
            return True

        from django.utils import timezone
        today = timezone.localdate()
        target_date = self.arrival_date or today

        # 1. Check for vitals or Doctor waiting queue
        try:
            from queue_operations.models import DoctorWaitingList
            dwl = DoctorWaitingList.objects.filter(
                patient_id=self.patient_id,
                created_date__date=target_date
            )
            if not dwl.exists() and target_date != today and self.created_date:
                dwl = DoctorWaitingList.objects.filter(
                    patient_id=self.patient_id,
                    created_date__gte=self.created_date
                )
            if dwl.exists():
                return True
        except Exception:
            pass

        # 2. Check for Nurse waiting queue
        try:
            from queue_operations.models import NurseWaitingList
            nwl = NurseWaitingList.objects.filter(
                patient_id=self.patient_id,
                created_date__date=target_date
            )
            if not nwl.exists() and target_date != today and self.created_date:
                nwl = NurseWaitingList.objects.filter(
                    patient_id=self.patient_id,
                    created_date__gte=self.created_date
                )
            if nwl.exists():
                return True
        except Exception:
            pass

        # 3. Check for Consultation encounters
        try:
            from queue_operations.models import PatientEncounter
            encounters = PatientEncounter.objects.filter(
                patient_id=self.patient_id,
                created_at__date=target_date
            )
            if not encounters.exists() and target_date != today and self.created_date:
                encounters = PatientEncounter.objects.filter(
                    patient_id=self.patient_id,
                    created_at__gte=self.created_date
                )
            if encounters.exists():
                return True
        except Exception:
            pass

        # 4. Check for Radiology / Laboratory requests
        try:
            from radio_lab.models import RadiologyLab
            rl = RadiologyLab.objects.filter(
                patient_id=self.patient_id,
                created_date__date=target_date
            )
            if not rl.exists() and target_date != today and self.created_date:
                rl = RadiologyLab.objects.filter(
                    patient_id=self.patient_id,
                    created_date__gte=self.created_date
                )
            if rl.exists():
                return True
        except Exception:
            pass

        # 5. Check for Invoices / Billings
        try:
            from Billings.models import Invoice
            inv = Invoice.objects.filter(
                patient_id=self.patient_id,
                created_date__date=target_date
            )
            if not inv.exists() and target_date != today and self.created_date:
                inv = Invoice.objects.filter(
                    patient_id=self.patient_id,
                    created_date__gte=self.created_date
                )
            if inv.exists():
                return True
        except Exception:
            pass

        return False

    @property
    def can_cancel(self):
        return self.completed == 0 and not self.has_actions_taken()
    
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