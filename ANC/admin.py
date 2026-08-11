from django.contrib import admin

from . models import *
admin.site.register([AntenatalVisit, ANCRegistration, ObstetricHistory, LabTests, CurrentPregnancy, GeneralMedical, ANCDetails, Examination])