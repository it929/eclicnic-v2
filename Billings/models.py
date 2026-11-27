from django.db import models

class TransactionUpdate(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
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
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    
    
    def __str__(self):
        return f"Transaction Update for {self.patient.surname} {self.patient.first_name} ({self.completed}) -- {self.created_date}"

class Invoice(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    invoice_number = models.CharField(max_length=20, null=True)
    product = models.CharField(max_length=60,null=True)
    qty = models.PositiveIntegerField(default=0)
    discount = models.PositiveIntegerField(default=0)
    price = models.PositiveIntegerField(default=0)
    payment_option = models.CharField(null=True, max_length=20)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    completed = models.PositiveIntegerField(default=0)
    original_source_model = models.CharField(max_length=50, null=True, blank=True) 
    original_source_id = models.PositiveIntegerField(null=True, blank=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True, null=True)
    # HMO pre-authorization (PA) code of a claim line (OPD claims and inpatient CLM- lines)
    pa_code = models.CharField(max_length=60, blank=True, default='')
    # Instalments: how much of this line has been paid so far. The line only becomes completed=1
    # (which releases the drug / test / service) once it is paid in full. Lines settled before
    # instalments existed have completed=1 and are treated as fully paid whatever this says.
    amount_paid = models.PositiveIntegerField(default=0)

    @property
    def balance(self):
        return 0 if int(self.completed or 0) else max(0, int(self.price or 0) - int(self.amount_paid or 0))

    def __str__(self):
        return f" Invoice for {self.patient.surname} {self.patient.first_name} (#{self.invoice_number})  - {self.created_date}"
    
class Receipt(models.Model):
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    invoice_number = models.CharField(max_length=20, null=True)
    receipt_number = models.CharField(max_length=20, null=True)
    remarks = models.TextField()
    total_price = models.PositiveIntegerField(default=0)
    category = models.ForeignKey('patients.PatientCategory', on_delete=models.CASCADE, null=True)
    payment_type = models.CharField(null=True, max_length=50)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    # One-time id sent by the cash desk with each payment: a repeated click returns the first result.
    request_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)

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
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    # Positive rows are money received; negative rows are money taken out ('Withdrawal' = used on
    # a bill, 'Refund' = paid back). The balance is the sum of all rows (same rule as the old pages).
    reference = models.CharField(max_length=60, blank=True, default='')
    slip_number = models.CharField(max_length=20, blank=True, default='')
    note = models.CharField(max_length=300, blank=True, default='')
    request_id = models.CharField(max_length=64, null=True, blank=True, db_index=True)
    # Family deposit: set when the money belongs to the family folder (any member's bill can use
    # it). Empty = the patient's own deposit. `patient` is then the member who paid in / was billed.
    family = models.ForeignKey('patients.FamilyFolder', on_delete=models.PROTECT, null=True, blank=True,
                               related_name='deposits')

    def __str__(self):
        return f" Deposit for {self.patient.surname} {self.patient.first_name} through ({self.payment_type})"

class Refund(models.Model):
    invoice_id = models.CharField(null=True, max_length=13)
    amount = models.PositiveIntegerField(default=0)
    payment_type = models.CharField(null=True, max_length=12, choices=PAYMENT_METHOD, default='Cash')
    payment_to = models.CharField(null=True, max_length=12)
    patient = models.ForeignKey('patients.PatientProfile', on_delete=models.PROTECT, null=True)
    staff = models.ForeignKey('users.User', on_delete=models.PROTECT, null=True)
    created_date = models.DateTimeField(auto_now_add=True)
    reason = models.CharField(max_length=300, blank=True, default='')

    def __str__(self):
        return f" Refund for {self.patient.surname} {self.patient.first_name} destination ({self.payment_to})"

class DocumentCounter(models.Model):
    """Gap-free running numbers (receipts). Read and bumped under a row lock, so two cashiers
    settling bills at the same moment can never get the same number."""
    key = models.CharField(max_length=40, unique=True)
    value = models.PositiveBigIntegerField(default=0)

    def __str__(self):
        return f'{self.key}={self.value}'
