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
        ("drops", "Drops"), ("puffs", "Puffs (Inhaler)"),

    ]


class Product(models.Model):
    EXPIRY_FLAG_IN = [
        ("", "--Select Periods--"),
        ("hours", "Hours"),
        ("days", "Days"),
        ("weeks", "Weeks"),
    ]

    product_name = models.CharField(max_length=200)
    product_id = models.CharField(max_length = 13, help_text="13 Characters max", null=True, blank=True, unique=True) #SKU
    description = models.CharField(blank=True, null=True,max_length=300)
    price = models.DecimalField(max_digits=15, decimal_places=2)
    stock = models.PositiveIntegerField()
    unit = models.PositiveIntegerField(default=0)
    minimum_UoM = models.CharField(choices=UOM, default="", null=True, max_length=22, blank=True) # unit of measurement
    low_stock_threshold = models.PositiveIntegerField(default=10)  # Alert when stock is below this value
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
        return self.product_name
    
    def save(self, *args, **kwargs):
        if not self.product_id or not str(self.product_id).strip():
            from inventory.utils import get_next_isl_sku
            self.product_id = get_next_isl_sku()
        CODE_39 = barcode.get_barcode_class('code39')
        code = CODE_39(f'{self.product_id}', writer=ImageWriter())
        buffer = BytesIO()
        code.write(buffer)
        self.barcode.save('SKU.png',File(buffer), save = False)
        return super().save(*args, **kwargs)

class Transaction(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    product_names = models.CharField(max_length=200, null=True)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    transaction_type = models.CharField(max_length=10, null=True)
    destination = models.CharField(max_length=30, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    minimum_UoM = models.CharField(max_length=20, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)

    def __str__(self):
        return f"{self.transaction_type} - {self.product.product_name} ({self.quantity} to {self.destination})"
    
    def save(self, *args, **kwargs):
        self.product_names = self.product.product_name
        self.price = self.product.price
        self.minimum_UoM = self.product.minimum_UoM
        return super().save(*args, **kwargs)
    

    
class ProductRequests(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    product_names = models.CharField(max_length=200, null=True)
    quantity = models.PositiveIntegerField()
    price = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    source = models.CharField(max_length=30, null=True)
    destination = models.CharField(max_length=30, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    minimum_UoM = models.CharField(max_length=20, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    staff2 = models.CharField(max_length=50, null=True)
    status = models.PositiveBigIntegerField(default=0)
    def __str__(self):
        return f"{self.product.product_name} ({self.quantity})"

 
class ProductRecipients(models.Model):
    department = models.CharField(max_length=30, null=True)

    def __str__(self):
        return self.department
    

class AdministerDrugs(models.Model):

    item = models.CharField(max_length=200)
    UoM = models.CharField(choices=UOM, default="", null=True, max_length=22, blank=True) # UOM - unit of measurement
    quantity = models.PositiveIntegerField()
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    total = models.DecimalField(max_digits=15, decimal_places=2)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f' -- ({self.quantity} {self.item})'
    

class Expense(models.Model):
    vendor_name = models.CharField(max_length=200)
    vendor_id = models.CharField(max_length=20)
    product_name = models.CharField(max_length=200)
    product_id = models.CharField(max_length=20)
    minimum_UoM = models.CharField(choices=UOM, default="", null=True, max_length=22, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    total_cost = models.DecimalField(max_digits=10, decimal_places=2, default=0.0)
    payment = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    due = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return self.vendor_name
    
    def save(self, *args, **kwargs):
        self.total_cost = (self.unit_price or 0) * (self.quantity or 0)
        self.payment = self.payment or 0
        self.due = self.total_cost - self.payment
        return super().save(*args, **kwargs)



class VendorTransaction(models.Model):
    vendor = models.ForeignKey(Expense, on_delete=models.CASCADE)
    vendor_name = models.CharField(max_length=200, null=True)
    product_name = models.CharField(max_length=200, null=True)
    payment = models.PositiveIntegerField()
    total_cost = models.DecimalField(max_digits=15, decimal_places=2, default=0)
    expense_id = models.PositiveIntegerField(default=0)
    created_date = models.DateTimeField(auto_now_add=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)

    def __str__(self):
        return f" {self.vendor.vendor_name} ({self.payment})"
    
    def save(self, *args, **kwargs):
        self.vendor_name = self.vendor.vendor_name
        self.total_cost = self.vendor.total_cost
        self.product_name = self.vendor.product_name
        return super().save(*args, **kwargs)


class PharmacyTariff(models.Model):
    product_id = models.CharField(max_length=13, db_index=True, blank=True) # SKU
    product_name = models.CharField(max_length=200)
    sponsor = models.ForeignKey('patients.Sponsor', on_delete=models.CASCADE, null=True, blank=True, related_name='medication_tariffs')
    plan = models.ForeignKey('patients.PatientPlan', on_delete=models.CASCADE, null=True, blank=True, related_name='medication_tariffs')
    rate = models.DecimalField(max_digits=15, decimal_places=2)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['product_name']

    def save(self, *args, **kwargs):
        if not self.product_id or not str(self.product_id).strip():
            existing_prod = Product.objects.filter(product_name__iexact=self.product_name.strip()).first()
            if existing_prod and existing_prod.product_id:
                self.product_id = existing_prod.product_id
            else:
                existing_t = PharmacyTariff.objects.filter(
                    product_name__iexact=self.product_name.strip()
                ).exclude(product_id__isnull=True).exclude(product_id='').first()
                if existing_t and existing_t.product_id:
                    self.product_id = existing_t.product_id
                else:
                    from inventory.utils import get_next_isl_sku
                    self.product_id = get_next_isl_sku()
        if self.plan and self.plan.sponsor and not self.sponsor:
            self.sponsor = self.plan.sponsor
        super().save(*args, **kwargs)

    def __str__(self):
        sponsor_name = self.sponsor.name if self.sponsor else (self.plan.sponsor.name if self.plan and self.plan.sponsor else 'General')
        plan_name = self.plan.plan if self.plan else 'All Plans'
        return f"{self.product_name} - {sponsor_name} ({plan_name}) - ₦{self.rate}"


class PharmacyStore(models.Model):
    """
    Physical or logical dispensing unit, pharmacy branch, or central store.
    Enables dynamic creation of unlimited pharmacies without hardcoded apps.
    """
    STORE_TYPES = [
        ('central_store', 'Central Medical Store'),
        ('opd_pharmacy', 'OPD Dispensing Pharmacy'),
        ('ipd_pharmacy', 'IPD / Inpatient Pharmacy'),
        ('emergency_pharmacy', 'Emergency / Satellite Pharmacy'),
        ('ward_pharmacy', 'Ward Pharmacy / Cabinet'),
        ('other', 'Other Store / Department'),
    ]

    name = models.CharField(max_length=150, unique=True, help_text="e.g. Central Medical Store, OPD Pharmacy 1")
    code = models.CharField(max_length=30, unique=True, db_index=True, help_text="e.g. CMS-01, OPD-PHARM-1")
    store_type = models.CharField(max_length=30, choices=STORE_TYPES, default='opd_pharmacy')
    description = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. Ground Floor, West Wing")
    in_charge = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='managed_stores')
    is_active = models.BooleanField(default=True)
    is_central = models.BooleanField(default=False, help_text="Designates this location as the primary central store")
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-is_central', 'name']

    def __str__(self):
        return f"{self.name} ({self.code})"


class StoreStock(models.Model):
    """
    Real-time inventory ledger tracking product stock per pharmacy/store location.
    """
    store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='stocks')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='store_stocks')
    stock = models.PositiveIntegerField(default=0)
    low_stock_threshold = models.PositiveIntegerField(default=10)
    batch_number = models.CharField(max_length=50, blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['store', 'product__product_name']
        unique_together = ('store', 'product')

    def __str__(self):
        return f"{self.store.name} - {self.product.product_name} ({self.stock})"

    @property
    def is_low_stock(self):
        return self.stock <= self.low_stock_threshold

    @property
    def days_until_earliest_expiry(self):
        if not self.expiry_date:
            return None
        from datetime import date
        today = date.today()
        return (self.expiry_date - today).days

    @property
    def expiry_status(self):
        days = self.days_until_earliest_expiry
        if days is None:
            return 'UNKNOWN'
        if days <= 0:
            return 'EXPIRED'
        if days <= 60:
            return 'NEAR_EXPIRY'
        return 'GOOD'


class StoreStockBatch(models.Model):
    """
    Individual batch/lot ledger tracking product stock, batch number, and expiry date
    per pharmacy store location for FEFO management and real-time expiry tracking.
    """
    store_stock = models.ForeignKey(StoreStock, on_delete=models.CASCADE, related_name='batches')
    store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='stock_batches')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='stock_batches')
    batch_number = models.CharField(max_length=50, db_index=True)
    expiry_date = models.DateField(blank=True, null=True, db_index=True)
    quantity = models.PositiveIntegerField(default=0)
    supplier = models.CharField(max_length=200, blank=True, null=True)
    received_date = models.DateField(auto_now_add=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['expiry_date', 'created_date']
        unique_together = ('store', 'product', 'batch_number')

    def __str__(self):
        return f"{self.product.product_name} - Batch {self.batch_number} ({self.quantity} units, Exp: {self.expiry_date})"

    @property
    def days_until_expiry(self):
        if not self.expiry_date:
            return None
        from datetime import date
        today = date.today()
        return (self.expiry_date - today).days

    @property
    def expiry_status(self):
        days = self.days_until_expiry
        if days is None:
            return 'UNKNOWN'
        if days <= 0:
            return 'EXPIRED'
        if days <= 60:
            return 'NEAR_EXPIRY'
        return 'GOOD'


class StockRequisition(models.Model):
    """
    Formal request submitted by a pharmacy requesting drugs from the Central Store.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Approval'),
        ('approved', 'Approved / Processing'),
        ('dispatched', 'Dispatched / In-Transit'),
        ('completed', 'Completed / Received'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    PRIORITY_CHOICES = [
        ('normal', 'Normal'),
        ('urgent', 'Urgent'),
        ('emergency', 'Emergency / Critical'),
    ]

    requisition_number = models.CharField(max_length=30, unique=True, db_index=True)
    requesting_store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='outgoing_requisitions')
    fulfilling_store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='incoming_requisitions')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='normal')
    notes = models.TextField(blank=True, null=True)
    requested_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='requested_requisitions')
    approved_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_requisitions')
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f"Req #{self.requisition_number} ({self.requesting_store.name} -> {self.fulfilling_store.name})"


class StockRequisitionItem(models.Model):
    """
    Line item for a stock requisition.
    """
    requisition = models.ForeignKey(StockRequisition, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity_requested = models.PositiveIntegerField()
    quantity_approved = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.product.product_name} x {self.quantity_requested}"


class StockTransfer(models.Model):
    """
    Stock distribution transfer from Store to Pharmacy (push) or fulfillment of requisition.
    """
    STATUS_CHOICES = [
        ('pending', 'Pending Dispatch'),
        ('in_transit', 'Dispatched / In-Transit'),
        ('received', 'Received & Stocked'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    transfer_number = models.CharField(max_length=30, unique=True, db_index=True)
    source_store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='transfers_out')
    destination_store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='transfers_in')
    requisition = models.ForeignKey(StockRequisition, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    notes = models.TextField(blank=True, null=True)
    dispatched_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='dispatched_stock_transfers')
    dispatched_at = models.DateTimeField(null=True, blank=True)
    received_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True, related_name='received_stock_transfers')
    received_at = models.DateTimeField(null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f"Transfer #{self.transfer_number} ({self.source_store.name} -> {self.destination_store.name})"


class StockTransferItem(models.Model):
    """
    Line item for a stock transfer.
    """
    transfer = models.ForeignKey(StockTransfer, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    quantity_sent = models.PositiveIntegerField()
    quantity_received = models.PositiveIntegerField(default=0)
    batch_number = models.CharField(max_length=50, blank=True, null=True)
    expiry_date = models.DateField(blank=True, null=True)
    notes = models.CharField(max_length=200, blank=True, null=True)

    def __str__(self):
        return f"{self.product.product_name} (Sent: {self.quantity_sent}, Recv: {self.quantity_received})"


class StockMovement(models.Model):
    """
    Immutable stock movement ledger for complete audit trail.
    """
    MOVEMENT_TYPES = [
        ('PURCHASE_GRN', 'Purchase / Goods Received'),
        ('TRANSFER_OUT', 'Stock Distributed / Transferred Out'),
        ('TRANSFER_IN', 'Stock Transferred In'),
        ('DISPENSE', 'Dispensed to Patient'),
        ('ADJUSTMENT', 'Stock Taking Adjustment'),
        ('RETURN', 'Stock Returned'),
    ]

    store = models.ForeignKey(PharmacyStore, on_delete=models.CASCADE, related_name='movements')
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='movements')
    movement_type = models.CharField(max_length=20, choices=MOVEMENT_TYPES)
    quantity = models.IntegerField(help_text="Positive for inward, negative for outward")
    balance_after = models.PositiveIntegerField()
    reference_number = models.CharField(max_length=50, blank=True, null=True)
    notes = models.CharField(max_length=255, blank=True, null=True)
    performed_by = models.ForeignKey('users.User', on_delete=models.SET_NULL, null=True, blank=True)
    created_date = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_date']

    def __str__(self):
        return f"{self.store.name} - {self.product.product_name}: {self.quantity} ({self.movement_type})"


class PharmacyVendor(models.Model):
    """
    Pharmaceutical vendor, manufacturer, and supplier registry.
    """
    name = models.CharField(max_length=200, help_text="Company or supplier name")
    code = models.CharField(max_length=50, blank=True, null=True, help_text="Vendor account or ledger code")
    contact_person = models.CharField(max_length=150, blank=True, null=True)
    phone = models.CharField(max_length=50, blank=True, null=True)
    email = models.CharField(max_length=150, blank=True, null=True)
    address = models.TextField(blank=True, null=True)
    product_lines = models.TextField(blank=True, null=True, help_text="Supplied products or medication lines")
    rating = models.CharField(max_length=10, default="5.0")
    status = models.CharField(max_length=20, default="Active")
    is_active = models.BooleanField(default=True)
    created_date = models.DateTimeField(auto_now_add=True)
    updated_date = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.code or 'No Code'})"
