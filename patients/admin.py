from django.contrib import admin
from .models import PatientCategory, PatientPlan, PatientProfile, PatientAppointment

class PatientPlanInline(admin.TabularInline):
    model = PatientPlan
    extra = 1

@admin.register(PatientCategory)
class PatientCategoryAdmin(admin.ModelAdmin):
    inlines = [PatientPlanInline]
    list_display = ('category',)

@admin.register(PatientPlan)
class PatientPlanAdmin(admin.ModelAdmin):
    list_display = ('plan', 'code', 'category')
    list_filter = ('category',)
    search_fields = ('plan', 'code')

@admin.register(PatientProfile)
class PatientProfileAdmin(admin.ModelAdmin):
    list_display = ('surname', 'first_name', 'category', 'plan', 'email_address')
    list_filter = ('category', 'gender')
    search_fields = ('surname', 'first_name', 'hospital_number', 'phone_number')
    raw_id_fields = ('category', 'plan')

@admin.register(PatientAppointment)
class PatientPlanAdmin(admin.ModelAdmin):
    list_display = ('purpose', 'visit_type', 'comment')
