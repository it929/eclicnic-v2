from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import task_manager_views as tm_views
from . import tariff_views
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
    VisitPurposeViewSet,
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
    UserProfileView,
    ChangePasswordView,
    UpdatePinView,
)

router = DefaultRouter()
# Patients & Queues
router.register(r'patients', PatientViewSet, basename='patient')
router.register(r'patient-categories', PatientCategoryViewSet, basename='patient-category')
router.register(r'sponsors', SponsorViewSet, basename='sponsor')
router.register(r'patient-plans', PatientPlanViewSet, basename='patient-plan')
router.register(r'queues', NurseWaitingListViewSet, basename='nurse-queue')
router.register(r'visit-purposes', VisitPurposeViewSet, basename='visit-purpose')

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

# Pharmacy
router.register(r'pharmacy/drugs', PharmacyDrugViewSet, basename='pharmacy-drug')

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
    path('tariffs/lab-charges/<int:pk>/', tariff_views.LabChargesView.as_view(), name='api-tariff-lab-charges-detail'),
    path('tariffs/radiology-charges/', tariff_views.RadiologyChargesView.as_view(), name='api-tariff-radio-charges'),
    path('tariffs/radiology-charges/<int:pk>/', tariff_views.RadiologyChargesView.as_view(), name='api-tariff-radio-charges-detail'),
    path('tariffs/admission-fees/', tariff_views.AdmissionFeesView.as_view(), name='api-tariff-admission-fees'),
    path('tariffs/admission-fees/<int:pk>/', tariff_views.AdmissionFeesView.as_view(), name='api-tariff-admission-fees-detail'),
    path('tariffs/other-services/', tariff_views.OtherServicesView.as_view(), name='api-tariff-other-services'),
    path('tariffs/other-services/<int:pk>/', tariff_views.OtherServicesView.as_view(), name='api-tariff-other-services-detail'),
    path('tariffs/medication-fees/', tariff_views.MedicationFeesView.as_view(), name='api-tariff-medication-fees'),
    path('tariffs/medication-fees/<int:pk>/', tariff_views.MedicationFeesView.as_view(), name='api-tariff-medication-fees-detail'),
    path('tariffs/packages/', tariff_views.PackagesView.as_view(), name='api-tariff-packages'),
    path('tariffs/packages/<int:pk>/', tariff_views.PackagesView.as_view(), name='api-tariff-packages-detail'),
    path('tariffs/package-data/', tariff_views.PackageDataView.as_view(), name='api-tariff-package-data'),
    path('tariffs/package-data/<int:pk>/', tariff_views.PackageDataView.as_view(), name='api-tariff-package-data-detail'),
    path('tariffs/immunization-fees/', tariff_views.ImmunizationFeesView.as_view(), name='api-tariff-immunization-fees'),

    # Meta & stats
    path('departments/', DepartmentListView.as_view(), name='api-departments'),
    path('dashboard/stats/', DashboardStatsView.as_view(), name='api-dashboard-stats'),

    # Routers
    path('', include(router.urls)),
]
