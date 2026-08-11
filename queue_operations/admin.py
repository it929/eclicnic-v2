from django.contrib import admin
from . models import BackgroundHealth,PatientBackgroundHealth,VisitPurpose,NurseWaitingList,DoctorWaitingList,Transcript, ICD11Category, ICD11Code, Diagnosis, PresentingComplaint, PatientEncounter, PatientReferral,PatientFollowUp,PatientOtherDetails,OtherService,TransactionTb,RegFee,GetRegistrationFee,PatientDiagnosis, WrittenPrescriptions
admin.site.register(BackgroundHealth)
admin.site.register(PatientBackgroundHealth)
admin.site.register(VisitPurpose)
admin.site.register(NurseWaitingList)
admin.site.register(DoctorWaitingList)
admin.site.register(Transcript)
admin.site.register(PresentingComplaint)
admin.site.register(PatientDiagnosis)
admin.site.register(PatientEncounter)
admin.site.register(PatientReferral)
admin.site.register(PatientFollowUp)
admin.site.register(PatientOtherDetails)
admin.site.register(OtherService)
admin.site.register(WrittenPrescriptions)
admin.site.register(RegFee)
admin.site.register(GetRegistrationFee)
admin.site.register(TransactionTb)



@admin.register(ICD11Category)
class ICD11CategoryAdmin(admin.ModelAdmin):
    list_display = ['code', 'title', 'parent', 'level']
    list_filter = ['level']
    search_fields = ['code', 'title']

@admin.register(ICD11Code)
class ICD11CodeAdmin(admin.ModelAdmin):
    list_display = ['code', 'title', 'category', 'is_leaf']
    list_filter = ['category', 'is_leaf']
    search_fields = ['code', 'title', 'description']

@admin.register(Diagnosis)
class DiagnosisAdmin(admin.ModelAdmin):
    list_display = ['patient', 'icd11_code', 'diagnosis_date', 'confirmed', 'primary_diagnosis']
    list_filter = ['diagnosis_date', 'confirmed', 'primary_diagnosis']
    search_fields = ['patient__patient_id', 'icd11_code__code', 'icd11_code__title']