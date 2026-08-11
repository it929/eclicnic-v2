from django.contrib import admin
from .models import *

admin.site.register(RadiologyLab)
admin.site.register(RadioLabInventory)
admin.site.register(LabResult)
admin.site.register(ScanResult)
