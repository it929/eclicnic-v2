from django.db import models
from django.utils import timezone
from ANC.models import AntenatalVisit  
from Billings.models import TransactionUpdate


class RadiologyLab(models.Model):

    item = models.CharField(max_length=200)
    item_type = models.CharField(max_length=2,null=True)
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    samples = models.CharField(max_length=100,null=True, blank=True)
    emergency = models.CharField(max_length=20,null=True, blank=True)
    comment = models.TextField(null=True, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)

    radiolab_waiting_status = models.PositiveIntegerField(default=0)
    doctor_waiting_status = models.PositiveIntegerField(default=0)
    billing_waiting_status = models.PositiveIntegerField(default=0)
    exception_bill = models.BooleanField(default=False)
    completed = models.PositiveIntegerField(default=0)

    created_date = models.DateTimeField(auto_now_add=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)

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

    def save(self, *args, **kwargs):
        # update TransactionUpdate model from Billings app
        obj, created = TransactionUpdate.objects.get_or_create(
            patient=self.patient,
            completed=0,
            defaults={
                'invoice_raised': 0, 
                'receipt_given': 0
            }
        )
        # Auto-calculate before saving
        self.anc_weeks = self.calculate_anc_weeks()
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.patient.surname} {self.patient.first_name} -- ({self.item})'
    

class RadioLabInventory(models.Model):
    item = models.CharField(max_length=200) 
    item_id = models.CharField(max_length=12,null=True)
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    type = models.CharField(max_length=2, null=True, choices=[('L','Lab'),('R','Scan')])
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True, related_name='lab_tariffs')
    
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-created_date']
        unique_together = ('item_id', 'plan')  

    def __str__(self):
        status = 'Lab Test' if self.type == 'L' else 'Scan Test'
        plan_name = self.plan.plan if self.plan else "No Plan"
        return f'{self.item} - {plan_name} ({status})'
    
    
class LabResult(models.Model):
    investigation = models.CharField(max_length=200, null=True)
    results = models.TextField(null=True)
    waiting_status = models.PositiveIntegerField(default=0)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True) 
    created_date = models.DateTimeField(auto_now_add=True)


class ScanResult(models.Model):
    investigation = models.CharField(max_length=200, null=True)
    results = models.TextField(null=True)
    scan = models.ImageField(null=True, blank=True, upload_to='scan-image/')
    waiting_status = models.PositiveIntegerField(default=0)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True) 
    created_date = models.DateTimeField(auto_now_add=True)
    
    def can_edit_delete(self):
        """Check if result can be edited/deleted (within 24 hours)"""
        time_diff = timezone.now() - self.created_date
        return time_diff.total_seconds() <= 86400  # 24 hours in seconds