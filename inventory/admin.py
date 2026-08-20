from django.contrib import admin
from . models import *
# Register your models here.
admin.site.register(Product)
admin.site.register(Transaction)
admin.site.register(ProductRecipients)
admin.site.register(AdministerDrugs)
admin.site.register(ProductRequests)
admin.site.register(Expense)
admin.site.register(VendorTransaction)
admin.site.register(PharmacyTariff)