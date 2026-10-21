from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import task_manager_views as tm_views
from . import tariff_views
from . import rbac_views
from .views import (
    LoginView,
    CurrentUserView,
    LogoutView,
    DepartmentListView,
    DashboardStatsView,
    PatientViewSet,
    PatientCategoryViewSet,
    PatientPlanViewSet,
    SponsorViewSet,
    NurseWaitingListViewSet,
    DoctorWaitingListViewSet,
    PatientEncounterViewSet,
    ConsultationDraftViewSet,
    PatientDiagnosisViewSet,
    PresentingComplaintViewSet,
    VisitPurposeViewSet,
    PatientAppointmentViewSet,
    InvoiceViewSet,
    ReceiptViewSet,
    DepositViewSet,
    RefundViewSet,
    AdmissionViewSet,
    WardViewSet,
    BedAllocationViewSet,
    ANCRegistrationViewSet,
    PharmacyDrugViewSet,
    RadioLabViewSet,
    InventoryProductViewSet,
    InventoryTransactionViewSet,
    InventoryProductRequestViewSet,
    WrittenPrescriptionViewSet,
    FamilyFolderViewSet,
    UserProfileView,
    UserAvatarUploadView,
    ChangePasswordView,
    UpdatePinView,
)

router = DefaultRouter()
# Patients & Queues
router.register(r'patients', PatientViewSet, basename='patient')
router.register(r'family-folders', FamilyFolderViewSet, basename='family-folder')
router.register(r'patient-categories', PatientCategoryViewSet, basename='patient-category')
router.register(r'sponsors', SponsorViewSet, basename='sponsor')
router.register(r'patient-plans', PatientPlanViewSet, basename='patient-plan')
router.register(r'queues', NurseWaitingListViewSet, basename='nurse-queue')
router.register(r'vitals', DoctorWaitingListViewSet, basename='vitals')
router.register(r'encounters', PatientEncounterViewSet, basename='encounter')
router.register(r'consultation-drafts', ConsultationDraftViewSet, basename='consultation-draft')
router.register(r'diagnoses', PatientDiagnosisViewSet, basename='diagnosis')
router.register(r'complaints', PresentingComplaintViewSet, basename='complaint')
router.register(r'visit-purposes', VisitPurposeViewSet, basename='visit-purpose')
router.register(r'appointments', PatientAppointmentViewSet, basename='appointment')

# Billings
router.register(r'invoices', InvoiceViewSet, basename='invoice')
router.register(r'receipts', ReceiptViewSet, basename='receipt')
router.register(r'deposits', DepositViewSet, basename='deposit')
router.register(r'refunds', RefundViewSet, basename='refund')

# IPD
router.register(r'admissions', AdmissionViewSet, basename='admission')
router.register(r'wards', WardViewSet, basename='ward')
router.register(r'bed-allocations', BedAllocationViewSet, basename='bed-allocation')

# ANC
router.register(r'anc', ANCRegistrationViewSet, basename='anc-registration')

# Pharmacy & Prescriptions
router.register(r'pharmacy/drugs', PharmacyDrugViewSet, basename='pharmacy-drug')
router.register(r'prescriptions', WrittenPrescriptionViewSet, basename='prescription')

# Radio & Lab
router.register(r'radio-lab', RadioLabViewSet, basename='radio-lab')

# Inventory
router.register(r'inventory/products', InventoryProductViewSet, basename='inventory-product')
router.register(r'inventory/transfers', InventoryTransactionViewSet, basename='inventory-transfer')
router.register(r'inventory/requests', InventoryProductRequestViewSet, basename='inventory-request')

urlpatterns = [
    # Auth endpoints
    path('auth/login/', LoginView.as_view(), name='api-login'),
    path('auth/me/', CurrentUserView.as_view(), name='api-me'),
    path('auth/logout/', LogoutView.as_view(), name='api-logout'),

    # Profile & Settings endpoints
    path('profile/', UserProfileView.as_view(), name='api-profile'),
    path('profile/avatar/', UserAvatarUploadView.as_view(), name='api-profile-avatar'),
    path('profile/change-password/', ChangePasswordView.as_view(), name='api-change-password'),
    path('profile/update-pin/', UpdatePinView.as_view(), name='api-update-pin'),

    # Task Manager endpoints
    path('task-manager/staff/', tm_views.StaffManagerView.as_view(), name='api-tm-staff'),
    path('task-manager/staff-action/', tm_views.StaffActionView.as_view(), name='api-tm-staff-action'),
    path('task-manager/online-users/', tm_views.OnlineUsersView.as_view(), name='api-tm-online-users'),
    path('task-manager/force-logout/', tm_views.ForceLogoutView.as_view(), name='api-tm-force-logout'),
    path('task-manager/activity-logs/', tm_views.ActivityLogsView.as_view(), name='api-tm-activity-logs'),
    path('task-manager/activity-dashboard/', tm_views.ActivityDashboardView.as_view(), name='api-tm-activity-dashboard'),
    path('task-manager/verify-staff/', tm_views.VerifyStaffView.as_view(), name='api-tm-verify-staff'),
    path('task-manager/queue-monitor/', tm_views.QueueMonitorView.as_view(), name='api-tm-queue-monitor'),
    path('task-manager/statistical-insights/', tm_views.StatisticalInsightsView.as_view(), name='api-tm-statistical-insights'),

    # Manage Tariff Plans endpoints
    path('tariffs/registration-fees/', tariff_views.RegistrationFeeView.as_view(), name='api-tariff-reg-fees'),
    path('tariffs/registration-fees/<int:pk>/', tariff_views.RegistrationFeeView.as_view(), name='api-tariff-reg-fees-detail'),
    path('tariffs/lab-charges/', tariff_views.LabChargesView.as_view(), name='api-tariff-lab-charges'),
    path('tariffs/lab-charges/load-general-prices/', tariff_views.LoadGeneralLabPricesView.as_view(), name='api-tariff-lab-load-general'),
    path('tariffs/lab-charges/bulk-upload/', tariff_views.BulkUploadLabTariffView.as_view(), name='api-tariff-lab-bulk-upload'),
    path('tariffs/lab-charges/download-template/', tariff_views.DownloadLabTariffTemplateView.as_view(), name='api-tariff-lab-download-template'),
    path('tariffs/lab-charges/<int:pk>/', tariff_views.LabChargesView.as_view(), name='api-tariff-lab-charges-detail'),
    path('tariffs/radiology-charges/', tariff_views.RadiologyChargesView.as_view(), name='api-tariff-radio-charges'),
    path('tariffs/radiology-charges/load-general-prices/', tariff_views.LoadGeneralRadiologyPricesView.as_view(), name='api-tariff-radiology-load-general'),
    path('tariffs/radiology-charges/bulk-upload/', tariff_views.BulkUploadRadiologyTariffView.as_view(), name='api-tariff-radiology-bulk-upload'),
    path('tariffs/radiology-charges/download-template/', tariff_views.DownloadRadiologyTariffTemplateView.as_view(), name='api-tariff-radiology-download-template'),
    path('tariffs/radiology-charges/<int:pk>/', tariff_views.RadiologyChargesView.as_view(), name='api-tariff-radio-charges-detail'),
    path('tariffs/admission-fees/', tariff_views.AdmissionFeesView.as_view(), name='api-tariff-admission-fees'),
    path('tariffs/admission-fees/<int:pk>/', tariff_views.AdmissionFeesView.as_view(), name='api-tariff-admission-fees-detail'),
    path('tariffs/other-services/', tariff_views.OtherServicesView.as_view(), name='api-tariff-other-services'),
    path('tariffs/other-services/<int:pk>/', tariff_views.OtherServicesView.as_view(), name='api-tariff-other-services-detail'),
    path('tariffs/medication-fees/', tariff_views.MedicationFeesView.as_view(), name='api-tariff-medication-fees'),
    path('tariffs/medication-fees/load-general-prices/', tariff_views.LoadGeneralMedicationPricesView.as_view(), name='api-tariff-medication-load-general'),
    path('tariffs/medication-fees/bulk-upload/', tariff_views.BulkUploadMedicationTariffView.as_view(), name='api-tariff-medication-bulk-upload'),
    path('tariffs/medication-fees/download-template/', tariff_views.DownloadMedicationTariffTemplateView.as_view(), name='api-tariff-medication-download-template'),
    path('tariffs/medication-fees/<int:pk>/', tariff_views.MedicationFeesView.as_view(), name='api-tariff-medication-fees-detail'),
    path('tariffs/packages/', tariff_views.PackagesView.as_view(), name='api-tariff-packages'),
    path('tariffs/packages/<int:pk>/', tariff_views.PackagesView.as_view(), name='api-tariff-packages-detail'),
    path('tariffs/package-data/', tariff_views.PackageDataView.as_view(), name='api-tariff-package-data'),
    path('tariffs/package-data/<int:pk>/', tariff_views.PackageDataView.as_view(), name='api-tariff-package-data-detail'),
    path('tariffs/immunization-fees/', tariff_views.ImmunizationFeesView.as_view(), name='api-tariff-immunization-fees'),

    # Meta & stats
    path('departments/', DepartmentListView.as_view(), name='api-departments'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='api-dashboard-stats'),

    # RBAC: Roles, Modules, Submodules & Permissions
    path('rbac/roles/', rbac_views.RoleListView.as_view(), name='api-rbac-roles'),
    path('rbac/roles/<int:pk>/', rbac_views.RoleDetailView.as_view(), name='api-rbac-role-detail'),
    path('rbac/modules/', rbac_views.SystemModuleListView.as_view(), name='api-rbac-modules'),
    path('rbac/modules/<int:pk>/', rbac_views.SystemModuleDetailView.as_view(), name='api-rbac-module-detail'),
    path('rbac/submodules/', rbac_views.SubModuleView.as_view(), name='api-rbac-submodules'),
    path('rbac/submodules/<int:pk>/', rbac_views.SubModuleView.as_view(), name='api-rbac-submodule-detail'),
    path('rbac/permissions/', rbac_views.RolePermissionView.as_view(), name='api-rbac-permissions'),
    path('rbac/assign-user-role/', rbac_views.UserRoleAssignmentView.as_view(), name='api-rbac-assign-user-role'),
    path('rbac/user-permissions/', rbac_views.UserPermissionsView.as_view(), name='api-rbac-user-permissions'),
    path('rbac/seed/', rbac_views.SeedRbacView.as_view(), name='api-rbac-seed'),

    # Routers
    path('', include(router.urls)),
]
