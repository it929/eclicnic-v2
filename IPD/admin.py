from django.contrib import admin

from . models import *
admin.site.register([AdmissionTable,AdmissionNote,DoctorNote,NurseNote,WardRound,Ward,Bed,BedAllocation,AdmissionFee, DrugAdministration, DrugPrescription])
