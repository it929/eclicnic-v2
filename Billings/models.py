from django.db import models

class TransactionUpdate(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    invoice_ids = models.CharField(max_length=20, null=True)
    invoice_raised = models.PositiveIntegerField(default=0)
    updated_date = models.DateTimeField(null=True, blank=True)
    receipt_ids = models.CharField(max_length=20, null=True)
    receipt_given = models.PositiveIntegerField(default=0)
    receipt_given_date = models.DateTimeField(null=True, blank=True)
    total_available_items = models.PositiveIntegerField(default=0) 
    total_invoiced_items = models.PositiveIntegerField(default=0)
    completed = models.PositiveIntegerField(default=0)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    
    
    def __str__(self):
        return f"Transaction Update for {self.patient.surname} {self.patient.first_name} ({self.completed}) -- {self.updated_date}"

class Invoice(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    invoice_number = models.CharField(max_length=20, null=True)
    product = models.CharField(max_length=60,null=True)
    qty = models.PositiveIntegerField(default=0)
    discount = models.PositiveIntegerField(default=0)
    price = models.PositiveIntegerField(default=0)
    payment_option = models.CharField(null=True, max_length=12)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    completed = models.PositiveIntegerField(default=0)
    original_source_model = models.CharField(max_length=50, null=True, blank=True) 
    original_source_id = models.PositiveIntegerField(null=True, blank=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)

    def __str__(self):
        return f" Invoice for {self.patient.surname} {self.patient.first_name} (#{self.invoice_number})  - {self.created_date}"
    
class Receipt(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    invoice_number = models.CharField(max_length=20, null=True)
    receipt_number = models.CharField(max_length=20, null=True)
    remarks = models.TextField()
    total_price = models.PositiveIntegerField(default=0)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    payment_type = models.CharField(null=True, max_length=50)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Receipt for {self.patient.surname} {self.payment_type} - {self.created_date} "



PAYMENT_METHOD = [
            ('Cash', 'Cash'),
            ('Transfer', 'Transfer'),
            ('POS', 'POS'),
            ('Bank Deposit', 'Bank Deposit'),
            ('Others', 'Others'),
        ]


class Deposit(models.Model):
    amount = models.IntegerField(default=0)
    invoice_id = models.CharField(null=True, max_length=13, blank=True)
    payment_type = models.CharField(null=True, max_length=50, choices=PAYMENT_METHOD, default='Cash')
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    def __str__(self):
        return f" Deposit for {self.patient.surname} {self.patient.first_name} through ({self.payment_type})"

class Refund(models.Model):
    invoice_id = models.CharField(null=True, max_length=13)
    amount = models.PositiveIntegerField(default=0)
    payment_type = models.CharField(null=True, max_length=12, choices=PAYMENT_METHOD, default='Cash')
    payment_to = models.CharField(null=True, max_length=12)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.CASCADE, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.CASCADE, null=True)
    created_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f" Refund for {self.patient.surname} {self.patient.first_name} destination ({self.payment_to})"