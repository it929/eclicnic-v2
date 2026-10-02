from django.db import models
import barcode
from barcode.writer import ImageWriter
from io import BytesIO
from django.core.files import File

UOM = [
        ("", "--Select Units--"),("ampoules", "Ampoules"),("bottles", "Bottles"),("boxes", "Boxes"),
        ("cartons", "Cartons"),("rolls", "Rolls"),("packs", "Packs"),("pieces", "Pieces"),
        ("prefilled_syringe", "Prefilled Syringe"),("sachets", "Sachets"),("syringes", "Syringes"),
        ("tins", "Tins"),("tubes", "Tubes"),("vial", "Vial"),("others", "Others"),("each", "Each"),
        ("mls", "mls (mililiters)"), ("mg", "mg"), ("mcg", "mcg"), ("g", "grams"), ("IU", "IU"),
        ("capsules", "Capsules"), ("tablets", "Tablets"), ("suppository", "Suppository"), ("pessary", "Pessary"),
        ("drops", "Drops"), ("immuno", "Immuno"), ("puffs", "Puffs (Inhaler)"),

    ]

class Drugs(models.Model):
    EXPIRY_FLAG_IN = [
        ("", "--Select Periods--"),
        ("hours", "Hours"),
        ("days", "Days"),
        ("weeks", "Weeks"),
    ]

    product_name = models.CharField(max_length=200)
    product_id = models.CharField(max_length = 13, help_text="13 Characters max", null=True, unique=True) #SKU
    description = models.CharField(blank=True, null=True,max_length=300)
    price = models.DecimalField(max_digits=15, decimal_places=2)
    stock = models.PositiveIntegerField()
    minimum_UoM = models.CharField(choices=UOM, default="", null=True, max_length=18, blank=True) # UOM - unit of measurement
    unit = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=10) 
    status = models.IntegerField(default=1, null=True)
    activation_status = models.IntegerField(default=1, null=True)
    barcode = models.ImageField(blank=True, null=True, upload_to='barcode_image')
    manufacturing_date = models.DateField(null=True, blank=True)
    expiry_date = models.DateField(null=True, blank=True)
    expiry_flag_in = models.CharField(choices=EXPIRY_FLAG_IN, default="", null=True, max_length=10, blank=True)
    expiry_flag_in_num = models.IntegerField(blank=True, null=True, default=0)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f'{self.product_name} {self.low_stock_threshold - self.status}'
    
    def save(self, *args, **kwargs):
        self.status = self.stock - self.low_stock_threshold
        CODE_39 = barcode.get_barcode_class('code39')
        code = CODE_39(f'{self.product_id}', writer=ImageWriter())
        buffer = BytesIO()
        code.write(buffer)
        self.barcode.save('SKU.png',File(buffer), save = False)
        return super().save(*args, **kwargs)

class DrugsUpdate(models.Model):
    product = models.ForeignKey(Drugs, on_delete=models.CASCADE)
    product_names = models.CharField(max_length=200, null=True)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    transaction_type = models.CharField(max_length=10, null=True)
    destination = models.CharField(max_length=30, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    minimum_UoM = models.CharField(max_length=20, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    transaction_id = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.transaction_type} - {self.product.product_name} ({self.quantity})"
    
    def save(self, *args, **kwargs):
        self.product_names = self.product.product_name
        self.price = self.product.price
        self.minimum_UoM = self.product.minimum_UoM
        return super().save(*args, **kwargs)
    

class IPDAdministeredDrugs(models.Model):
    product = models.ForeignKey(Drugs, on_delete=models.CASCADE, null=True)
    item = models.CharField(max_length=200)
    UoM = models.CharField(choices=UOM, default="", null=True, max_length=18, blank=True) # UOM - unit of measurement
    quantity = models.PositiveIntegerField()
    route = models.CharField(max_length=20, null=True)
    frequency = models.CharField(max_length=20, null=True)
    dose = models.PositiveIntegerField(null=True)
    duration = models.PositiveIntegerField(null= True)
    notes = models.TextField(null=True, blank=True, max_length=500)
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    # total = models.DecimalField(max_digits=15, decimal_places=2)
    start_date = models.DateField(null=True, blank=True)
    anc_weeks = models.CharField(max_length=12, null=True, blank=True)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    doctor_waiting_status = models.IntegerField(default=0, null=True)
    billing_waiting_status = models.IntegerField(default=0, null=True)
    completed = models.IntegerField(default=0, null=True)
    pharm_waiting_status = models.IntegerField(default=0, null=True)
    pharm_staff = models.CharField(max_length=30, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f' {self.item} ({self.completed}) -- start date:  {self.created_date}'
    
    @property
    def instructions(self):
         # Frequency Mapping
        freq_map = {
            'stat': 'immediately',
            'om': 'once daily in the morning',
            'bd': '2 times daily',
            'tds': '3 times daily',
            'qds': '4 times daily',
            'nocte': 'once daily at night',
            'weekly': 'once weekly',
            'monthly': 'once monthly',
            'prn': 'as needed',
            'mane': 'once daily in the morning',
            'alt_die': 'every other day',
            'ac': 'before meals',
            'pc': 'after meals',
            'others': 'as directed by the physician',
        }
        
        # Route Mapping
        route_map = {
            'Oral': 'by mouth',
            'Tab': 'by mouth (tablet)',
            'Syp': 'by mouth (syrup)',
            'IV': 'via intravenous infusion',
            'IM': 'via intramuscular injection',
            'SC': 'via subcutaneous injection',
            'ID': 'via intradermal injection',
            'Topical': 'topically to the affected area', 
            'SL': 'under the tongue (sublingual)',
            'PR': 'rectally',
            'PV': 'vaginally',
            'Inhalation': 'via inhalation',
            'Nasal': 'into the nostrils',
            'Ocular': 'into the eye(s)',
            'Otic': 'into the ear(s)',
        }
        
        # Verb mapping based on route
        route_lower = str(self.route).lower() if self.route else ''
        
        if route_lower in ['topical']:
            verb = "Apply"
        elif route_lower in ['ocular', 'otic', 'nasal']:
            verb = "Instill"
        elif route_lower in ['iv', 'im', 'sc', 'id']:
            verb = "Administer"
        elif route_lower in ['inhalation']:
            verb = "Inhale"
        else:
            verb = "Take"
        
        # Get mapped values with proper fallbacks
        freq_text = freq_map.get(self.frequency, f"as scheduled ({self.frequency})") if self.frequency else "as directed"
        route_text = route_map.get(self.route, f"via {self.route.lower()}") if self.route else "as specified"
        
        # Handle UOM display
        uom_display = self.get_UoM_display() if self.UoM else "units"
        uom = uom_display.lower() if uom_display else "units"
        
        # Clean up UOM text
        if "--select" in uom or "select" in uom:
            uom = "units"

        if self.UoM.lower() == 'bottles':
            self.dose = '(' + str(self.dose) + 'ml) from this '
        
        # Build the instruction
        instruction = f"{verb} {self.dose} {uom} {freq_text} {route_text}."
        
        #  duration if specified
        if self.duration and self.duration > 0:
            duration_text = "day" if self.duration == 1 else "days"
            instruction += f" Continue for {self.duration} {duration_text}."
        
        # notes if available
        if self.notes and self.notes.strip():
            instruction += f" {self.notes}"
        
        # start date if available and future dated
        if self.start_date:
            from datetime import date
            if self.start_date > date.today():
                instruction += f" Start on {self.start_date.strftime('%B %d, %Y')}."
        
        return instruction


