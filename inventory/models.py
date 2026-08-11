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
    product_id = models.CharField(max_length = 13, help_text="13 Characters max", null=True, unique=True) #SKU
    description = models.CharField(blank=True, null=True,max_length=300)
    price = models.DecimalField(max_digits=15, decimal_places=2)
    stock = models.PositiveIntegerField()
    minimum_UoM = models.CharField(choices=UOM, default="", null=True, max_length=22, blank=True) # UOM - unit of measurement
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