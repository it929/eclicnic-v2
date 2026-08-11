from django.db import models
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType

class AdmissionTable(models.Model):
    doctor_admitted = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
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

    @property
    def current_allocation(self):
        return self.bedallocation_set.first()

    def __str__(self):
        return f' {self.patient.surname} {self.patient.first_name} admitted on ({self.doctor_admit_date})'

class Ward(models.Model):
    ward_name =  models.CharField(null=True,max_length=50,unique=True) 
    price = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.ward_name}"

class Bed(models.Model):
    ward = models.ForeignKey(Ward, on_delete=models.CASCADE, related_name='beds', null=True)
    bed_name =  models.CharField(null=True,max_length=50) 
    bed_status = models.PositiveIntegerField(default=0)
    is_occupied = models.BooleanField(default=False)
    class Meta:
        unique_together = ('ward', 'bed_name')
        
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
    
    class Meta:
        ordering = ['-created_date']
    
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
    admission_note =  models.TextField(null=True) 
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from Dr. {self.staff.fullname}"

class DoctorNote(models.Model):
    doctor_note =  models.TextField(null=True) 
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from Dr. {self.staff.fullname}"

class NurseNote(models.Model):
    nurse_note =  models.TextField(null=True) 
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from Dr. {self.staff.fullname}"
    
class WardRound(models.Model):
    notes = models.TextField(null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Notes for {self.patient.surname} {self.patient.first_name} - from Dr. {self.staff.fullname}"
    


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