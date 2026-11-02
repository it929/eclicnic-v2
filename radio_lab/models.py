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
    item_id = models.CharField(max_length=64, null=True, blank=True)
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    type = models.CharField(max_length=2, null=True, choices=[('L','Lab'),('R','Scan')])
    test_type = models.CharField(
        max_length=20,
        default='investigation',
        blank=True,
        choices=[('investigation', 'Investigation (Panel)'), ('parameter', 'Parameter (Individual Test)')]
    )
    sponsor = models.ForeignKey('patients.Sponsor', on_delete=models.CASCADE, null=True, blank=True, related_name='lab_tariffs')
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True, blank=True, related_name='lab_tariffs')
    parameter_ids = models.JSONField(default=list, blank=True)
    
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True, null=True)
    
    class Meta:
        ordering = ['item']
        unique_together = ('item_id', 'sponsor', 'plan')  

    def save(self, *args, **kwargs):
        if self.plan and self.plan.sponsor and not self.sponsor:
            self.sponsor = self.plan.sponsor
        super().save(*args, **kwargs)

    def __str__(self):
        status = 'Lab Test' if self.type == 'L' else 'Scan Test'
        sponsor_name = self.sponsor.name if self.sponsor else (self.plan.sponsor.name if self.plan and self.plan.sponsor else "General")
        plan_name = self.plan.plan if self.plan else "All Plans"
        return f'{self.item} - {sponsor_name} ({plan_name}) ({status})'
    
    
class LabResult(models.Model):
    order = models.ForeignKey(RadiologyLab, on_delete=models.CASCADE, null=True, blank=True, related_name='lab_results')
    investigation = models.CharField(max_length=200, null=True)
    results = models.TextField(null=True)
    file_upload = models.FileField(null=True, blank=True, upload_to='lab-results/')
    waiting_status = models.PositiveIntegerField(default=0)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True) 
    created_date = models.DateTimeField(auto_now_add=True)


class ScanResult(models.Model):
    order = models.ForeignKey(RadiologyLab, on_delete=models.CASCADE, null=True, blank=True, related_name='scan_results')
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

# ─────────────────────────────────────────────────────────────────────────────
# LAB INVESTIGATION & PARAMETER SYSTEM
# ─────────────────────────────────────────────────────────────────────────────

class LabParameter(models.Model):
    """Individual lab test parameter (e.g. WBC, Haemoglobin, Glucose)."""

    RESULT_TYPE_CHOICES = [
        ('numeric', 'Numeric'),
        ('text', 'Text / Descriptive'),
        ('qualitative', 'Qualitative (Pos/Neg)'),
    ]

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)   # Haematology, Biochemistry…
    measurement_unit = models.CharField(max_length=50, blank=True)
    result_type = models.CharField(max_length=20, choices=RESULT_TYPE_CHOICES, default='numeric')
    normal_result_description = models.CharField(max_length=200, blank=True)

    # Standalone ordering
    can_be_done_alone = models.BooleanField(default=True)
    base_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)

    # Specimen / collection info
    specimen = models.CharField(max_length=100, blank=True)
    sample_bottle_color = models.CharField(max_length=50, blank=True)
    sample_quantity = models.CharField(max_length=50, blank=True)

    # Display
    display_order = models.PositiveIntegerField(default=0)

    # Interpretation text
    low_interpretation = models.TextField(blank=True)
    high_interpretation = models.TextField(blank=True)
    low_comments = models.TextField(blank=True)
    high_comments = models.TextField(blank=True)
    general_comments = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'display_order', 'name']

    def __str__(self):
        return f'{self.name} ({self.code})'


class LabInvestigation(models.Model):
    """A named panel/investigation that groups many parameters (e.g. FBC, LFTs)."""

    code = models.CharField(max_length=50, unique=True)
    name = models.CharField(max_length=200)
    category = models.CharField(max_length=100, blank=True)

    # Specimen / collection info
    specimen = models.CharField(max_length=100, blank=True)
    sample_bottle_color = models.CharField(max_length=50, blank=True)
    sample_quantity = models.CharField(max_length=50, blank=True)

    # Pricing
    base_price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    use_accumulated_price = models.BooleanField(
        default=True,
        help_text='If True, price = sum of mapped parameter prices; otherwise use base_price'
    )

    is_panel = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['category', 'name']

    def get_accumulated_price(self):
        """Sum of all mapped parameter base_prices."""
        total = sum(
            m.parameter.base_price
            for m in self.parameter_mappings.select_related('parameter').all()
        )
        return total

    def effective_price(self):
        if self.use_accumulated_price:
            return self.get_accumulated_price()
        return self.base_price

    def __str__(self):
        return f'{self.name} ({self.code})'


class LabInvestigationParameter(models.Model):
    """Mapping table: which parameters belong to which investigation."""

    investigation = models.ForeignKey(
        LabInvestigation, on_delete=models.CASCADE, related_name='parameter_mappings'
    )
    parameter = models.ForeignKey(
        LabParameter, on_delete=models.CASCADE, related_name='investigation_mappings'
    )
    order = models.PositiveIntegerField(default=0)
    is_required = models.BooleanField(default=True)

    class Meta:
        unique_together = ('investigation', 'parameter')
        ordering = ['order']

    def __str__(self):
        return f'{self.investigation.name} → {self.parameter.name}'


class LabParameterReferenceRange(models.Model):
    """Age/gender-specific normal & critical ranges for a parameter."""

    DEMOGRAPHIC_CHOICES = [
        ('adult_male', 'Adult Male'),
        ('adult_female', 'Adult Female'),
        ('neonate_0_3d', '0–3 Days'),
        ('neonate_4_14d', '4–14 Days'),
        ('infant_15d_3m', '15 Days – 3 Months'),
        ('infant_3m_6m', '3–6 Months'),
        ('infant_6m_1y', '6 Months – 1 Year'),
        ('child_1_2y', '1–2 Years'),
        ('child_2_5y', '2–5 Years'),
        ('child_5_12y', '5–12 Years'),
        ('general', 'General'),
    ]

    parameter = models.ForeignKey(
        LabParameter, on_delete=models.CASCADE, related_name='reference_ranges'
    )
    demographic_group = models.CharField(max_length=30, choices=DEMOGRAPHIC_CHOICES)
    common_value = models.CharField(max_length=200, blank=True)
    low_boundary = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    high_boundary = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    low_critical = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    high_critical = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    high_level = models.CharField(max_length=100, blank=True)
    low_level = models.CharField(max_length=100, blank=True)

    class Meta:
        unique_together = ('parameter', 'demographic_group')

    def __str__(self):
        return f'{self.parameter.name} – {self.get_demographic_group_display()}'


class LabOrderResultItem(models.Model):
    """Structured result row linking a RadiologyLab order to a specific parameter."""

    FLAG_CHOICES = [
        ('', 'Not set'),
        ('NORMAL', 'Normal'),
        ('LOW', 'Low'),
        ('HIGH', 'High'),
        ('CRITICAL_LOW', 'Critical Low'),
        ('CRITICAL_HIGH', 'Critical High'),
    ]

    order = models.ForeignKey(
        RadiologyLab, on_delete=models.CASCADE, related_name='parameter_results'
    )
    parameter = models.ForeignKey(
        LabParameter, on_delete=models.SET_NULL, null=True, blank=True
    )
    investigation = models.ForeignKey(
        LabInvestigation, on_delete=models.SET_NULL, null=True, blank=True
    )

    # Snapshots (so historic results survive parameter edits)
    parameter_name = models.CharField(max_length=200)
    result_value = models.CharField(max_length=500, blank=True)
    unit = models.CharField(max_length=50, blank=True)
    reference_range_display = models.CharField(max_length=200, blank=True)
    flag = models.CharField(max_length=20, blank=True, choices=FLAG_CHOICES)
    display_order = models.PositiveIntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['display_order', 'parameter_name']

    def __str__(self):
        return f'{self.order} – {self.parameter_name}: {self.result_value}'
