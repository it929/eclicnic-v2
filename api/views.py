from django.contrib.auth import authenticate, login as auth_login
from django.utils import timezone
from django.db.models import Q, Count, Sum
from datetime import date
from rest_framework import status, viewsets, permissions, filters
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.response import Response
from rest_framework.authtoken.models import Token
from rest_framework.views import APIView
from rest_framework.pagination import PageNumberPagination

from users.models import User, Category
from patients.models import (
    PatientProfile, PatientCategory, PatientPlan, PatientAppointment, Sponsor,
    FamilyFolder, FamilyMember, format_family_number
)
from queue_operations.models import (
    NurseWaitingList, VisitPurpose, DoctorWaitingList, PatientEncounter,
    PatientDiagnosis, PresentingComplaint, WrittenPrescriptions, ConsultationDraft
)
from Billings.models import Invoice, Receipt, Deposit, Refund
from IPD.models import AdmissionTable, Ward, Bed, BedAllocation
from ANC.models import ANCRegistration
from OPD_pharm.models import OpdDrugs
from radio_lab.models import RadiologyLab

from .serializers import (
    UserSerializer,
    CategorySerializer,
    PatientProfileSerializer,
    PatientCategorySerializer,
    PatientPlanSerializer,
    SponsorSerializer,
    FamilyFolderSerializer,
    FamilyMemberSerializer,
    NurseWaitingListSerializer,
    DoctorWaitingListSerializer,
    PatientEncounterSerializer,
    VisitPurposeSerializer,
    InvoiceSerializer,
    ReceiptSerializer,
    DepositSerializer,
    RefundSerializer,
    AdmissionTableSerializer,
    WardSerializer,
    BedSerializer,
    BedAllocationSerializer,
    ANCRegistrationSerializer,
    OpdDrugsSerializer,
    RadiologyLabSerializer,
    PatientAppointmentSerializer,
    PatientDiagnosisSerializer,
    PresentingComplaintSerializer,
    WrittenPrescriptionSerializer,
    ConsultationDraftSerializer,
)


class StandardResultsSetPagination(PageNumberPagination):
    page_size = 15
    page_size_query_param = 'page_size'
    max_page_size = 100


class LoginView(APIView):
    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        username = request.data.get('username', '').strip()
        password = request.data.get('password', '').strip()

        if not username or not password:
            return Response(
                {'detail': 'Username and password are required.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        user = authenticate(username=username, password=password)
        if not user:
            try:
                user_obj = User.objects.filter(Q(username__iexact=username) | Q(email__iexact=username)).first()
                if user_obj and user_obj.check_password(password):
                    user = user_obj
            except Exception:
                pass

        if not user:
            return Response(
                {'detail': 'Invalid username or password.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        auth_login(request, user)
        token, _ = Token.objects.get_or_create(user=user)
        user_data = UserSerializer(user).data

        role_name = user_data.get('role_name') or (user.department.department if user.department else 'Admin')
        modules = user_data.get('role_modules') or (user.department.modules if (user.department and user.department.modules) else [])
        submodules = user_data.get('role_submodules') or {}

        return Response({
            'token': token.key,
            'user': user_data,
            'department': role_name,
            'role': role_name,
            'modules': modules,
            'submodules': submodules,
        })


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        user_data = serializer.data
        role_name = user_data.get('role_name') or (request.user.department.department if request.user.department else 'Admin')
        modules = user_data.get('role_modules') or (request.user.department.modules if (request.user.department and request.user.department.modules) else [])
        submodules = user_data.get('role_submodules') or {}

        return Response({
            'user': user_data,
            'department': role_name,
            'role': role_name,
            'modules': modules,
            'submodules': submodules,
        })


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        try:
            request.user.auth_token.delete()
        except Exception:
            pass
        return Response({'detail': 'Logged out successfully.'})


class UserProfileView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)
        return Response({
            'user': UserSerializer(user, context={'request': request}).data,
            'has_pin': bool(user.has_pin),
            'department': user.department.department if user.department else 'Admin'
        })

    def put(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        pin_code = request.data.get('pin_code')
        if user.has_pin:
            if not pin_code or not user.check_pin(pin_code):
                return Response({'detail': 'Incorrect Security PIN.'}, status=status.HTTP_400_BAD_REQUEST)

        # Update profile fields
        user.fullname = request.data.get('fullname', user.fullname)
        user.email = request.data.get('email', user.email)
        user.phone_number = request.data.get('phone_number', user.phone_number)
        user.address = request.data.get('address', user.address)
        user.gender = request.data.get('gender', user.gender)
        dob = request.data.get('dob')
        if dob:
            user.dob = dob
        if 'avatar' in request.FILES:
            user.avatar = request.FILES['avatar']
        user.save()

        return Response({
            'detail': 'Profile updated successfully!',
            'user': UserSerializer(user, context={'request': request}).data
        })


class UserAvatarUploadView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        avatar_file = request.FILES.get('avatar')
        if not avatar_file:
            return Response({'detail': 'No avatar image file provided.'}, status=status.HTTP_400_BAD_REQUEST)

        user.avatar = avatar_file
        user.save()
        return Response({
            'detail': 'Profile image updated successfully!',
            'user': UserSerializer(user, context={'request': request}).data,
            'avatar_url': user.avatar.url if user.avatar else None,
        })


class ChangePasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        data = request.data if isinstance(request.data, dict) else {}
        old_password = data.get('old_password') or data.get('current_password') or ''
        new_password = data.get('new_password', '')

        if not new_password:
            return Response({'detail': 'New password is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if len(new_password) < 6:
            return Response({'detail': 'New password must be at least 6 characters long.'}, status=status.HTTP_400_BAD_REQUEST)

        if user.has_usable_password() and request.user.is_authenticated:
            if not user.check_password(old_password):
                return Response({'detail': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()

        if request.user.is_authenticated:
            try:
                from django.contrib.auth import update_session_auth_hash
                update_session_auth_hash(request, user)
            except Exception:
                pass

        return Response({'detail': 'Password changed successfully!'})


class UpdatePinView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        new_pin = request.data.get('new_pin')
        if not new_pin or not str(new_pin).isdigit() or len(str(new_pin)) != 4:
            return Response({'detail': 'PIN must be a 4-digit number.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_pin(new_pin)
        user.save()
        return Response({'detail': 'Security PIN updated successfully!'})


class DepartmentListView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        departments = Category.objects.all().order_by('department')
        dept_list = []
        for d in departments:
            staff_count = User.objects.filter(department=d).count()
            dept_list.append({
                'id': d.id,
                'department': d.department,
                'staff_count': staff_count,
                'modules': d.modules if d.modules is not None else [],
            })
        return Response(dept_list)

    def post(self, request):
        name = request.data.get('department', '').strip()
        modules = request.data.get('modules', [])
        if not name:
            return Response({'detail': 'User category / Department name is required.'}, status=status.HTTP_400_BAD_REQUEST)
        if Category.objects.filter(department__iexact=name).exists():
            return Response({'detail': f'Department "{name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)
        dept = Category.objects.create(department=name, modules=modules if isinstance(modules, list) else [])
        return Response({
            'detail': f'User category (Department) "{name}" created successfully!',
            'id': dept.id,
            'department': dept.department,
            'modules': dept.modules,
            'staff_count': 0,
        }, status=status.HTTP_201_CREATED)

    def put(self, request):
        pk = request.data.get('id') or request.query_params.get('id')
        if not pk:
            return Response({'detail': 'Department ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            dept = Category.objects.get(id=pk)
            modules = request.data.get('modules')
            if modules is not None:
                if not isinstance(modules, list):
                    return Response({'detail': 'Modules must be a list of module keys.'}, status=status.HTTP_400_BAD_REQUEST)
                dept.modules = modules
            name = request.data.get('department')
            if name and str(name).strip():
                dept.department = str(name).strip()
            dept.save()
            return Response({
                'detail': f'Module permissions for department "{dept.department}" saved successfully!',
                'id': dept.id,
                'department': dept.department,
                'modules': dept.modules,
            })
        except Category.DoesNotExist:
            return Response({'detail': 'Department not found.'}, status=status.HTTP_404_NOT_FOUND)

    def delete(self, request):
        pk = request.query_params.get('id')
        if not pk:
            return Response({'detail': 'Department ID is required.'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            dept = Category.objects.get(id=pk)
            staff_count = User.objects.filter(department=dept).count()
            if staff_count > 0:
                return Response({
                    'detail': f'Cannot delete department "{dept.department}" because {staff_count} staff member(s) are assigned to it.'
                }, status=status.HTTP_400_BAD_REQUEST)
            name = dept.department
            dept.delete()
            return Response({'detail': f'User category (Department) "{name}" deleted successfully.'})
        except Category.DoesNotExist:
            return Response({'detail': 'Department not found.'}, status=status.HTTP_404_NOT_FOUND)


class DashboardStatsView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        today = date.today()
        total_patients = PatientProfile.objects.count()
        active_patients = PatientProfile.objects.filter(active=1).count()
        inactive_patients = PatientProfile.objects.filter(active=0).count()
        today_patients = PatientProfile.objects.filter(created_date__date=today).count()
        queued_patients = NurseWaitingList.objects.count()

        # Category specific
        private_patients = PatientProfile.objects.filter(category__category__iexact='Private').count()
        anc_patients = PatientProfile.objects.filter(category__category__iexact='ANC').count()
        hmo_patients = PatientProfile.objects.filter(category__category__iexact='HMO').count()
        retainership_patients = PatientProfile.objects.filter(category__category__iexact='Retainership').count()

        # Inpatients & Admissions
        inpatients = AdmissionTable.objects.filter(doctor_discharge_status=0).count()

        # Pharmacy & Inventory
        low_stock_drugs = OpdDrugs.objects.filter(stock__lte=10).count()
        total_drugs = OpdDrugs.objects.count()

        # Billings
        today_invoices = Invoice.objects.filter(created_date__date=today).count()
        today_receipts = Receipt.objects.filter(created_date__date=today).aggregate(total=Sum('total_price'))['total'] or 0

        # Appointments
        today_appointments = PatientAppointment.objects.filter(arrival_date=today).count()

        # Categories breakdown
        categories = PatientCategory.objects.annotate(
            patient_count=Count('patientprofile')
        ).values('id', 'category', 'patient_count')

        return Response({
            'stats': {
                'total_patients': total_patients,
                'active_patients': active_patients,
                'inactive_patients': inactive_patients,
                'registered_today': today_patients,
                'private_patients': private_patients,
                'anc_patients': anc_patients,
                'hmo_patients': hmo_patients,
                'retainership_patients': retainership_patients,
                'inpatients': inpatients,
                'today_appointments': today_appointments,
                'nurse_queue_count': queued_patients,
                'total_staff': User.objects.count(),
                'low_stock_drugs': low_stock_drugs,
                'total_drugs': total_drugs,
                'today_invoices': today_invoices,
                'today_revenue': today_receipts,
            },
            'categories': list(categories),
            'timestamp': timezone.now().isoformat()
        })


class PatientViewSet(viewsets.ModelViewSet):
    queryset = PatientProfile.objects.all().select_related('category', 'plan', 'created_by')
    serializer_class = PatientProfileSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['surname', 'first_name', 'other_name', 'hospital_number', 'phone_number', 'email_address']
    ordering_fields = ['created_date', 'surname', 'first_name', 'hospital_number']
    ordering = ['-created_date']

    def get_queryset(self):
        qs = super().get_queryset().select_related('sponsor', 'family_folder')
        query = self.request.query_params.get('search', None)
        if query:
            q = query.strip()
            qs = qs.filter(
                Q(surname__icontains=q) |
                Q(first_name__icontains=q) |
                Q(other_name__icontains=q) |
                Q(hospital_number__icontains=q) |
                Q(phone_number__icontains=q) |
                Q(email_address__icontains=q) |
                Q(next_of_kin_name__icontains=q) |
                Q(next_of_kin_phone__icontains=q) |
                Q(insurance_policy_number__icontains=q) |
                Q(family_folder__family_number__icontains=q) |
                Q(family_folder__family_name__icontains=q)
            )

        category_id = self.request.query_params.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)

        sponsor_id = self.request.query_params.get('sponsor', None)
        if sponsor_id:
            qs = qs.filter(sponsor_id=sponsor_id)

        gender = self.request.query_params.get('gender', None)
        if gender:
            qs = qs.filter(gender__iexact=gender)

        active = self.request.query_params.get('active', None)
        if active is not None and active != '':
            qs = qs.filter(active=active)

        today_only = self.request.query_params.get('today', None)
        if today_only in ['1', 'true', 'True']:
            from django.utils import timezone
            qs = qs.filter(created_date__date=timezone.localdate())

        has_family = self.request.query_params.get('has_family_folder', None)
        if has_family in ['1', 'true', 'True']:
            qs = qs.filter(family_folder__isnull=False)
        elif has_family in ['0', 'false', 'False']:
            qs = qs.filter(family_folder__isnull=True)

        date_from = self.request.query_params.get('date_from', None)
        if date_from:
            qs = qs.filter(created_date__date__gte=date_from)

        date_to = self.request.query_params.get('date_to', None)
        if date_to:
            qs = qs.filter(created_date__date__lte=date_to)

        return qs

    @action(detail=False, methods=['get'], url_path='directory-stats')
    def directory_stats(self, request):
        from django.utils import timezone
        today = timezone.localdate()
        total = PatientProfile.objects.count()
        active = PatientProfile.objects.filter(active=1).count()
        inactive = PatientProfile.objects.filter(active=0).count()
        registered_today = PatientProfile.objects.filter(created_date__date=today).count()
        private_count = PatientProfile.objects.filter(category__category__iexact='Private').count()
        hmo_count = PatientProfile.objects.filter(category__category__iexact='HMO').count()
        anc_count = PatientProfile.objects.filter(category__category__iexact='ANC').count()
        retainership_count = PatientProfile.objects.filter(category__category__iexact='Retainership').count()
        in_family_count = PatientProfile.objects.filter(family_folder__isnull=False).count()

        return Response({
            'total': total,
            'active': active,
            'inactive': inactive,
            'registered_today': registered_today,
            'private': private_count,
            'hmo': hmo_count,
            'anc': anc_count,
            'retainership': retainership_count,
            'in_family': in_family_count,
        })

    @action(detail=True, methods=['post'], url_path='toggle-active')
    def toggle_active(self, request, pk=None):
        patient = self.get_object()
        from django.utils import timezone

        user_display = 'Administrator'
        if request.user and request.user.is_authenticated:
            user_display = getattr(request.user, 'fullname', '') or request.user.username or 'Staff'

        if patient.active == 1:
            patient.active = 0
            patient.deactivated_date = timezone.now()
            patient.deactivated_by = user_display
            patient.save(update_fields=['active', 'deactivated_date', 'deactivated_by'])
            action_label = 'deactivated'
        else:
            patient.active = 1
            patient.deactivated_date = None
            patient.deactivated_by = None
            patient.save(update_fields=['active', 'deactivated_date', 'deactivated_by'])
            action_label = 'activated'

        return Response({
            'success': True,
            'message': f"Patient {patient.get_full_name()} ({patient.hospital_number}) has been {action_label} successfully.",
            'active': patient.active,
            'deactivated_date': patient.deactivated_date,
            'deactivated_by': patient.deactivated_by,
            'patient': self.get_serializer(patient).data
        })

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.save(created_by=user)
        try:
            TransactionUpdate.objects.get_or_create(
                patient=patient,
                completed=0,
                defaults={'invoice_raised': 0, 'receipt_given': 0}
            )
        except Exception:
            pass


class PatientCategoryViewSet(viewsets.ModelViewSet):
    queryset = PatientCategory.objects.all().order_by('category')
    serializer_class = PatientCategorySerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None


class SponsorViewSet(viewsets.ModelViewSet):
    queryset = Sponsor.objects.all().select_related('category').prefetch_related('plans').order_by('name')
    serializer_class = SponsorSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        category_id = self.request.query_params.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)
        search = self.request.query_params.get('search', None)
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(category__category__icontains=search)
            )
        return qs

    @action(detail=False, methods=['post'], url_path='import-sponsors')
    def import_sponsors(self, request):
        """
        Import sponsors from uploaded Excel file or the default Sponsor.xlsx in project root.
        """
        import os
        import openpyxl
        from django.conf import settings

        uploaded_file = request.FILES.get('file')

        if uploaded_file:
            try:
                wb = openpyxl.load_workbook(uploaded_file, data_only=True)
            except Exception as e:
                return Response(
                    {'detail': f'Could not read uploaded Excel file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            possible_paths = [
                os.path.join(settings.BASE_DIR, '..', 'Sponsor.xlsx'),
                os.path.join(settings.BASE_DIR, 'Sponsor.xlsx'),
                'Sponsor.xlsx',
            ]
            found_path = None
            for p in possible_paths:
                if os.path.exists(p):
                    found_path = p
                    break
            if not found_path:
                return Response(
                    {'detail': 'Sponsor.xlsx not found in project root. Please upload an Excel file.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            try:
                wb = openpyxl.load_workbook(found_path, data_only=True)
            except Exception as e:
                return Response(
                    {'detail': f'Could not load Sponsor.xlsx: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        sheet = wb.active
        hmo_category, _ = PatientCategory.objects.get_or_create(category='HMO')

        created_count = 0
        updated_count = 0

        for row in sheet.iter_rows(values_only=True):
            if not row or not any(row):
                continue

            name = None
            code = None

            if len(row) >= 3 and row[1] and row[2]:
                val1 = str(row[1]).strip()
                val2 = str(row[2]).strip()
                if val1.upper() in ['HMO', 'NAME', 'SPONSOR', 'PLAN NAME', 'CURRENT HMO LIST']:
                    continue
                name = val1
                code = val2
            elif len(row) >= 2 and row[0] and row[1]:
                val0 = str(row[0]).strip()
                val1 = str(row[1]).strip()
                if val0.upper() in ['SN', 'S/N', 'ID', 'CURRENT HMO LIST']:
                    continue
                name = val0
                code = val1

            if not name or name.isdigit():
                continue

            sp, created = Sponsor.objects.update_or_create(
                name=name,
                defaults={'code': code, 'category': hmo_category}
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        return Response({
            'message': f'Successfully synced sponsors: {created_count} created, {updated_count} updated.',
            'created': created_count,
            'updated': updated_count,
            'total': Sponsor.objects.count()
        })


class PatientPlanViewSet(viewsets.ModelViewSet):
    queryset = PatientPlan.objects.all().select_related('category', 'sponsor').order_by('plan')
    serializer_class = PatientPlanSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        sponsor_id = self.request.query_params.get('sponsor', None)
        if sponsor_id:
            qs = qs.filter(sponsor_id=sponsor_id)
        category_id = self.request.query_params.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)
        search = self.request.query_params.get('search', None)
        if search:
            qs = qs.filter(
                Q(plan__icontains=search) |
                Q(code__icontains=search) |
                Q(sponsor__name__icontains=search) |
                Q(category__category__icontains=search)
            )
        return qs


class FamilyFolderViewSet(viewsets.ModelViewSet):
    queryset = FamilyFolder.objects.all().select_related(
        'category', 'sponsor', 'principal_patient', 'created_by'
    ).prefetch_related(
        'members__patient__category', 'members__patient__sponsor', 'members__patient__plan'
    ).order_by('-created_date')
    serializer_class = FamilyFolderSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = StandardResultsSetPagination

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search', None)
        if search:
            search = search.strip()
            qs = qs.filter(
                Q(family_name__icontains=search) |
                Q(family_number__icontains=search) |
                Q(physical_folder_number__icontains=search) |
                Q(principal_patient__surname__icontains=search) |
                Q(principal_patient__first_name__icontains=search) |
                Q(principal_patient__hospital_number__icontains=search) |
                Q(members__patient__surname__icontains=search) |
                Q(members__patient__first_name__icontains=search) |
                Q(members__assigned_hospital_number__icontains=search) |
                Q(phone_number__icontains=search)
            ).distinct()

        folder_type = self.request.query_params.get('folder_type', None)
        if folder_type:
            qs = qs.filter(folder_type=folder_type)

        category_id = self.request.query_params.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)

        sponsor_id = self.request.query_params.get('sponsor', None)
        if sponsor_id:
            qs = qs.filter(sponsor_id=sponsor_id)

        is_active = self.request.query_params.get('is_active', None)
        if is_active is not None:
            active_bool = str(is_active).lower() in ['1', 'true', 'yes']
            qs = qs.filter(is_active=active_bool)

        return qs

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        user = request.user if request.user.is_authenticated else None

        family_name = data.get('family_name', '').strip()
        if not family_name:
            return Response({'detail': 'Family name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        category_id = data.get('category')
        sponsor_id = data.get('sponsor')
        principal_patient_id = data.get('principal_patient_id') or data.get('principal_patient')

        category = None
        if category_id:
            category = PatientCategory.objects.filter(id=category_id).first()

        sponsor = None
        if sponsor_id:
            sponsor = Sponsor.objects.filter(id=sponsor_id).first()

        principal_patient = None
        if principal_patient_id:
            principal_patient = PatientProfile.objects.filter(id=principal_patient_id).first()

        # Determine folder_type (default to private_folder if Private category, hmo_group if HMO)
        folder_type = data.get('folder_type')
        if not folder_type:
            if category and 'hmo' in category.category.lower():
                folder_type = 'hmo_group'
            else:
                folder_type = 'private_folder'

        # Auto-detect category & sponsor from principal patient if not provided
        if principal_patient:
            if not category and principal_patient.category:
                category = principal_patient.category
            if not sponsor and principal_patient.sponsor:
                sponsor = principal_patient.sponsor
            if not folder_type:
                if category and 'hmo' in category.category.lower():
                    folder_type = 'hmo_group'
                else:
                    folder_type = 'private_folder'

        # Generate Family Number
        family_number = data.get('family_number', '').strip()
        if not family_number:
            if principal_patient and principal_patient.hospital_number:
                family_number = format_family_number(principal_patient.hospital_number)
            elif sponsor and sponsor.code:
                import random
                rand_num = random.randint(1000, 9999)
                family_number = f"F/{sponsor.code.strip().upper()}/ISL-{rand_num}"
            else:
                import random
                rand_num = random.randint(1000, 9999)
                family_number = f"F/ISL-{rand_num}"

        # Clean family number: ensure it starts with F/
        if not family_number.upper().startswith('F/'):
            family_number = f"F/{family_number}"

        # Check uniqueness of family_number
        if FamilyFolder.objects.filter(family_number__iexact=family_number).exists():
            import random
            rand_suffix = random.randint(10, 99)
            family_number = f"{family_number}-{rand_suffix}"

        # Physical folder number for private families
        physical_folder_number = data.get('physical_folder_number', '').strip()
        if not physical_folder_number and folder_type == 'private_folder':
            physical_folder_number = family_number

        storage_location = data.get('storage_location', '').strip()
        phone_number = data.get('phone_number') or (principal_patient.phone_number if principal_patient else '')
        address = data.get('address') or (principal_patient.address if principal_patient else '')
        notes = data.get('notes', '')

        folder = FamilyFolder.objects.create(
            family_name=family_name,
            family_number=family_number,
            category=category,
            sponsor=sponsor,
            folder_type=folder_type,
            physical_folder_number=physical_folder_number if folder_type == 'private_folder' else None,
            storage_location=storage_location if folder_type == 'private_folder' else None,
            principal_patient=principal_patient,
            phone_number=phone_number,
            address=address,
            notes=notes,
            created_by=user
        )

        # If a principal patient was specified, add them as the first member (Suffix 'A')
        if principal_patient:
            assigned_number = f"{family_number}-A"
            orig_hosp_num = principal_patient.hospital_number

            # Update patient profile
            principal_patient.hospital_number = assigned_number
            principal_patient.family_folder = folder
            principal_patient.family_member_suffix = 'A'
            principal_patient.save()

            FamilyMember.objects.create(
                family=folder,
                patient=principal_patient,
                letter_suffix='A',
                assigned_hospital_number=assigned_number,
                original_hospital_number=orig_hosp_num,
                relationship='Principal',
                is_principal=True,
                added_by=user
            )

        serializer = self.get_serializer(folder)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='add-member')
    def add_member(self, request, pk=None):
        folder = self.get_object()
        data = request.data
        user = request.user if request.user.is_authenticated else None

        patient_id = data.get('patient_id')
        new_patient_data = data.get('new_patient_data')
        relationship = data.get('relationship', 'Dependent')
        is_principal = bool(data.get('is_principal', False))

        if not patient_id and not new_patient_data:
            return Response({'detail': 'Either patient_id or new_patient_data must be provided.'}, status=status.HTTP_400_BAD_REQUEST)

        letter_suffix = folder.get_next_letter_suffix()
        assigned_number = f"{folder.family_number}-{letter_suffix}"

        if patient_id:
            patient = PatientProfile.objects.filter(id=patient_id).first()
            if not patient:
                return Response({'detail': 'Patient not found.'}, status=status.HTTP_404_NOT_FOUND)

            # Check if patient already belongs to a family
            if hasattr(patient, 'family_membership') and patient.family_membership:
                if patient.family_membership.family_id == folder.id:
                    return Response({'detail': f'Patient is already a member of this family (Suffix {patient.family_membership.letter_suffix}).'}, status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response({
                        'detail': f'Patient already belongs to another family: {patient.family_membership.family.family_name} ({patient.family_membership.family.family_number}). Please remove them first.'
                    }, status=status.HTTP_400_BAD_REQUEST)

            orig_hosp_num = patient.hospital_number
            patient.hospital_number = assigned_number
            patient.family_folder = folder
            patient.family_member_suffix = letter_suffix

            # Determine principal member of folder
            principal = folder.principal_patient
            if not principal and folder.members.exists():
                head_m = folder.members.filter(is_principal=True).first() or folder.members.filter(letter_suffix='A').first()
                if head_m:
                    principal = head_m.patient
                    folder.principal_patient = principal
                    folder.save(update_fields=['principal_patient'])

            # If this patient is designated principal or folder has none, set them as principal
            if is_principal or not folder.principal_patient:
                folder.principal_patient = patient
                folder.save(update_fields=['principal_patient'])
                patient.save()
                # Propagate this principal's sponsor and plan to any existing members
                folder.sync_members_to_principal()
            else:
                # Family members MUST maintain the same category, sponsor, and plan of the Principal Member
                if principal:
                    if principal.category:
                        patient.category = principal.category
                    if principal.sponsor:
                        patient.sponsor = principal.sponsor
                    if principal.plan:
                        patient.plan = principal.plan
                    if getattr(principal, 'insurance_policy_number', None) and not patient.insurance_policy_number:
                        patient.insurance_policy_number = principal.insurance_policy_number
                else:
                    if folder.category:
                        patient.category = folder.category
                    if folder.sponsor:
                        patient.sponsor = folder.sponsor

                patient.save()

            FamilyMember.objects.create(
                family=folder,
                patient=patient,
                letter_suffix=letter_suffix,
                assigned_hospital_number=assigned_number,
                original_hospital_number=orig_hosp_num,
                relationship=relationship,
                is_principal=is_principal or (folder.principal_patient_id == patient.id),
                added_by=user
            )

        elif new_patient_data:
            # Create a brand new patient profile directly in this family
            surname = new_patient_data.get('surname', '').strip()
            first_name = new_patient_data.get('first_name', '').strip()
            if not surname or not first_name:
                return Response({'detail': 'Surname and first name are required for new patient.'}, status=status.HTTP_400_BAD_REQUEST)

            dob = new_patient_data.get('dob') or date.today().isoformat()
            gender = new_patient_data.get('gender', 'Female')
            phone = new_patient_data.get('phone_number') or folder.phone_number or ''
            address = new_patient_data.get('address') or folder.address or ''

            # Optional email address with uniqueness validation
            email = new_patient_data.get('email_address', '').strip() or None
            if email and PatientProfile.objects.filter(email_address__iexact=email).exists():
                return Response({'detail': f'A patient with email "{email}" is already registered.'}, status=status.HTTP_400_BAD_REQUEST)

            # Optional Next of Kin fields
            next_of_kin_name = new_patient_data.get('next_of_kin_name', '').strip() or None
            next_of_kin_relationship = new_patient_data.get('next_of_kin_relationship', '').strip() or None
            next_of_kin_phone = new_patient_data.get('next_of_kin_phone', '').strip() or None

            # Determine principal member to inherit sponsor and plan
            principal = folder.principal_patient
            if not principal and folder.members.exists():
                head_m = folder.members.filter(is_principal=True).first() or folder.members.filter(letter_suffix='A').first()
                if head_m:
                    principal = head_m.patient
                    folder.principal_patient = principal
                    folder.save(update_fields=['principal_patient'])

            # Inherit sponsor, plan, and category from Principal Member
            member_category = principal.category if principal and principal.category else folder.category
            member_sponsor = principal.sponsor if principal and principal.sponsor else folder.sponsor
            member_plan = principal.plan if principal and principal.plan else None
            member_policy = (principal.insurance_policy_number if principal and getattr(principal, 'insurance_policy_number', None) else new_patient_data.get('insurance_policy_number'))

            patient = PatientProfile.objects.create(
                surname=surname,
                first_name=first_name,
                other_name=new_patient_data.get('other_name', ''),
                dob=dob,
                gender=gender,
                phone_number=phone,
                email_address=email,
                address=address,
                category=member_category,
                sponsor=member_sponsor,
                plan=member_plan,
                insurance_policy_number=member_policy,
                hospital_number=assigned_number,
                family_folder=folder,
                family_member_suffix=letter_suffix,
                allergies=new_patient_data.get('allergies', ''),
                patient_type=new_patient_data.get('patient_type', 'Single'),
                relationship_to_patient=relationship,
                full_name=next_of_kin_name,
                phone_numbers=next_of_kin_phone,
                next_of_kin_name=next_of_kin_name,
                next_of_kin_relationship=next_of_kin_relationship,
                next_of_kin_phone=next_of_kin_phone,
                created_by=user
            )

            if is_principal or not folder.principal_patient:
                folder.principal_patient = patient
                folder.save(update_fields=['principal_patient'])
                folder.sync_members_to_principal()

            FamilyMember.objects.create(
                family=folder,
                patient=patient,
                letter_suffix=letter_suffix,
                assigned_hospital_number=assigned_number,
                original_hospital_number=None,
                relationship=relationship,
                is_principal=is_principal or (folder.principal_patient_id == patient.id),
                added_by=user
            )

        # Refresh folder
        folder.refresh_from_db()
        return Response(self.get_serializer(folder).data)

    @action(detail=True, methods=['post'], url_path='sync-plan')
    def sync_plan(self, request, pk=None):
        folder = self.get_object()
        folder.sync_members_to_principal()
        folder.refresh_from_db()
        return Response(self.get_serializer(folder).data)

    @action(detail=True, methods=['post'], url_path='remove-member')
    def remove_member(self, request, pk=None):
        folder = self.get_object()
        data = request.data
        member_id = data.get('member_id')
        patient_id = data.get('patient_id')
        restore_hospital_number = bool(data.get('restore_hospital_number', True))

        member = None
        if member_id:
            member = FamilyMember.objects.filter(id=member_id, family=folder).first()
        elif patient_id:
            member = FamilyMember.objects.filter(patient_id=patient_id, family=folder).first()

        if not member:
            return Response({'detail': 'Family member record not found.'}, status=status.HTTP_404_NOT_FOUND)

        patient = member.patient
        if restore_hospital_number and member.original_hospital_number:
            patient.hospital_number = member.original_hospital_number
        patient.family_folder = None
        patient.family_member_suffix = None
        patient.save()

        # Update principal patient if the removed member was principal
        if folder.principal_patient_id == patient.id:
            next_principal = folder.members.exclude(id=member.id).first()
            folder.principal_patient = next_principal.patient if next_principal else None
            folder.save()

        member.delete()
        folder.refresh_from_db()
        return Response(self.get_serializer(folder).data)

    @action(detail=True, methods=['post'], url_path='set-principal')
    def set_principal(self, request, pk=None):
        folder = self.get_object()
        patient_id = request.data.get('patient_id')
        if not patient_id:
            return Response({'detail': 'patient_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        member = FamilyMember.objects.filter(family=folder, patient_id=patient_id).first()
        if not member:
            return Response({'detail': 'Patient is not a member of this family.'}, status=status.HTTP_404_NOT_FOUND)

        folder.principal_patient = member.patient
        folder.save()

        folder.members.all().update(is_principal=False)
        member.is_principal = True
        member.relationship = 'Principal'
        member.save()

        folder.refresh_from_db()
        return Response(self.get_serializer(folder).data)

    @action(detail=False, methods=['get'], url_path='preview-number')
    def preview_number(self, request):
        patient_id = request.query_params.get('patient_id')
        sponsor_id = request.query_params.get('sponsor_id')
        sponsor_code = request.query_params.get('sponsor_code')

        if patient_id:
            patient = PatientProfile.objects.filter(id=patient_id).first()
            if patient and patient.hospital_number:
                fam_num = format_family_number(patient.hospital_number)
                return Response({
                    'family_number': fam_num,
                    'first_member_number': f"{fam_num}-A",
                    'principal_patient_name': patient.get_full_name(),
                    'principal_hospital_number': patient.hospital_number,
                    'category_id': patient.category_id,
                    'category_name': patient.category.category if patient.category else 'Private',
                    'sponsor_id': patient.sponsor_id,
                    'sponsor_name': patient.get_sponsor_name(),
                })

        code = ''
        if sponsor_id:
            sp = Sponsor.objects.filter(id=sponsor_id).first()
            if sp and sp.code:
                code = sp.code.strip().upper()
        elif sponsor_code:
            code = sponsor_code.strip().upper()

        import random
        rand_num = random.randint(1000, 9999)
        fam_num = f"F/{code}/ISL-{rand_num}" if code else f"F/ISL-{rand_num}"
        return Response({
            'family_number': fam_num,
            'first_member_number': f"{fam_num}-A"
        })

    @action(detail=False, methods=['get'], url_path='stats')
    def stats(self, request):
        total_families = FamilyFolder.objects.count()
        private_folders = FamilyFolder.objects.filter(folder_type='private_folder').count()
        hmo_groups = FamilyFolder.objects.filter(folder_type='hmo_group').count()
        total_members = FamilyMember.objects.count()

        return Response({
            'total_families': total_families,
            'private_folders': private_folders,
            'hmo_groups': hmo_groups,
            'total_members': total_members,
        })


class NurseWaitingListViewSet(viewsets.ModelViewSet):
    queryset = NurseWaitingList.objects.all().select_related('attendant', 'patient')
    serializer_class = NurseWaitingListSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        completed = self.request.query_params.get('completed', None)
        if completed is not None:
            qs = qs.filter(completed=completed)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        plan = serializer.validated_data.get('plan') or (patient.plan if patient else None)
        serializer.save(attendant=user, category=category, plan=plan)


class DoctorWaitingListViewSet(viewsets.ModelViewSet):
    queryset = DoctorWaitingList.objects.all().select_related('patient', 'staff', 'category', 'plan').order_by('-created_date')
    serializer_class = DoctorWaitingListSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient', None)
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        completed = self.request.query_params.get('completed', None)
        if completed is not None:
            qs = qs.filter(completed=completed)
        return qs

    def create(self, request, *args, **kwargs):
        pin_code = request.data.get('pin_code')
        if pin_code is None or str(pin_code).strip() == '':
            return Response(
                {'detail': 'Security PIN is required to authorize recording vitals.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        pin_str = str(pin_code).strip()
        if not pin_str.isdigit():
            return Response(
                {'detail': 'Invalid security PIN format. PIN must be numeric.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        pin_int = int(pin_str)
        if pin_int == 0:
            return Response(
                {'detail': 'PIN 0000 is invalid. Please enter your valid security PIN.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Identify the attending staff member attempting this clinical authorization
        authorizing_staff = None
        if request.user and request.user.is_authenticated:
            authorizing_staff = request.user
        elif request.data.get('staff_id'):
            try:
                authorizing_staff = User.objects.filter(id=request.data.get('staff_id'), is_active=True).first()
            except Exception:
                pass
        elif request.data.get('staff_username'):
            authorizing_staff = User.objects.filter(
                username__iexact=str(request.data.get('staff_username')).strip(),
                is_active=True
            ).first()

        if not authorizing_staff:
            return Response(
                {'detail': 'Authentication required. Please log in as an attending staff member to authorize vitals.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check if the attending staff member has a security PIN configured
        if not authorizing_staff.has_pin:
            staff_name = getattr(authorizing_staff, 'fullname', '') or authorizing_staff.username
            return Response(
                {'detail': f'Staff member "{staff_name}" has no security PIN configured. Please set your 4-digit PIN in Profile Settings before authorizing vitals.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Strictly verify that the entered PIN matches the attending staff member's own PIN
        if not authorizing_staff.check_pin(pin_str):
            return Response(
                {'detail': 'Incorrect Security PIN. Authorization denied.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        plan = serializer.validated_data.get('plan') or (patient.plan if patient else None)

        queue_id = request.data.get('queue_id')
        current_queue = None
        if queue_id:
            current_queue = NurseWaitingList.objects.filter(id=queue_id).first()

        critical_req = (current_queue.critical_request if current_queue else 0) or serializer.validated_data.get('critical_request', 0)
        anc_weeks = (current_queue.anc_weeks if current_queue else None) or serializer.validated_data.get('anc_weeks', None)

        vitals = serializer.save(
            staff=authorizing_staff,
            category=category,
            plan=plan,
            critical_request=critical_req,
            anc_weeks=anc_weeks
        )

        staff_display_name = getattr(authorizing_staff, 'fullname', None) or authorizing_staff.get_full_name() or authorizing_staff.username

        # Mark corresponding NurseWaitingList item as completed
        if queue_id:
            NurseWaitingList.objects.filter(id=queue_id).update(
                completed=1,
                completed_by=staff_display_name
            )
        elif patient:
            NurseWaitingList.objects.filter(patient=patient, completed=0).update(
                completed=1,
                completed_by=staff_display_name
            )

        headers = self.get_success_headers(serializer.data)
        response_data = serializer.data
        response_data['staff_name'] = staff_display_name
        response_data['authorized_by'] = staff_display_name
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        plan = serializer.validated_data.get('plan') or (patient.plan if patient else None)
        serializer.save(staff=user, category=category, plan=plan)


class PatientEncounterViewSet(viewsets.ModelViewSet):
    """
    Doctor Consultation & Clinical Encounter ViewSet.
    Handles documentation of doctor clinical encounters, chief complaints,
    HPI, diagnosis, and treatment plans.
    """
    queryset = PatientEncounter.objects.all().select_related('patient', 'provider').order_by('-created_at')
    serializer_class = PatientEncounterSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient', None)
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        encounter = serializer.save(provider=user)

        # Update DoctorWaitingList if patient is in active doctor queue
        patient = encounter.patient
        if patient:
            try:
                DoctorWaitingList.objects.filter(patient=patient, completed=0).update(
                    waiting_status=1,
                    completed_by=getattr(user, 'fullname', 'Doctor') if user else 'Doctor'
                )
            except Exception:
                pass
            # Automatically clear any in-progress draft for this patient upon completing encounter
            try:
                ConsultationDraft.objects.filter(patient=patient).delete()
            except Exception:
                pass


class ConsultationDraftViewSet(viewsets.ModelViewSet):
    """
    Doctor Consultation Draft ViewSet.
    Persists work-in-progress consultations so doctors can pause, save draft,
    and return later to resume documenting their notes, diagnosis, and orders.
    """
    queryset = ConsultationDraft.objects.all().select_related('patient', 'doctor', 'appointment').order_by('-updated_at')
    serializer_class = ConsultationDraftSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient') or self.request.query_params.get('patient_id')
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        appointment_id = self.request.query_params.get('appointment') or self.request.query_params.get('appointment_id')
        if appointment_id:
            qs = qs.filter(appointment_id=appointment_id)
        return qs

    def create(self, request, *args, **kwargs):
        patient_id = request.data.get('patient') or request.data.get('patient_id')
        if not patient_id:
            return Response({'detail': 'Patient ID is required to save a draft.'}, status=status.HTTP_400_BAD_REQUEST)

        appointment_id = request.data.get('appointment') or request.data.get('appointment_id')
        draft_data = request.data.get('draft_data')
        if draft_data is None:
            draft_data = {k: v for k, v in request.data.items() if k not in ['patient', 'patient_id', 'appointment', 'appointment_id']}

        user = request.user if request.user.is_authenticated else None

        draft = ConsultationDraft.objects.filter(patient_id=patient_id).first()
        if draft:
            draft.draft_data = draft_data
            if appointment_id:
                draft.appointment_id = appointment_id
            if user:
                draft.doctor = user
            draft.save()
            created = False
        else:
            draft = ConsultationDraft.objects.create(
                patient_id=patient_id,
                appointment_id=appointment_id,
                doctor=user,
                draft_data=draft_data
            )
            created = True

        serializer = self.get_serializer(draft)
        return Response({
            'success': True,
            'message': 'Consultation draft saved successfully.',
            'draft': serializer.data
        }, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)

    @action(detail=False, methods=['get', 'post', 'delete'], url_path='active')
    def active_draft(self, request):
        patient_id = request.query_params.get('patient') or request.query_params.get('patient_id') or request.data.get('patient') or request.data.get('patient_id')
        if not patient_id:
            return Response({'detail': 'Patient ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if request.method == 'GET':
            draft = ConsultationDraft.objects.filter(patient_id=patient_id).order_by('-updated_at').first()
            if not draft:
                return Response({'has_draft': False, 'draft': None})
            return Response({
                'has_draft': True,
                'draft': self.get_serializer(draft).data
            })

        elif request.method == 'POST':
            return self.create(request)

        elif request.method == 'DELETE':
            deleted_count, _ = ConsultationDraft.objects.filter(patient_id=patient_id).delete()
            return Response({
                'success': True,
                'message': 'Consultation draft cleared.',
                'deleted_count': deleted_count
            })




class PatientDiagnosisViewSet(viewsets.ModelViewSet):
    queryset = PatientDiagnosis.objects.all().order_by('category', 'description')
    serializer_class = PatientDiagnosisSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        include_inactive = self.request.query_params.get('all', 'false').lower() == 'true'
        if not include_inactive:
            qs = qs.filter(is_active=True)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(description__icontains=search) |
                Q(icd10_code__icontains=search) |
                Q(icd11_code__icontains=search) |
                Q(category__icontains=search)
            )
        category = self.request.query_params.get('category', '').strip()
        if category and category != 'all':
            qs = qs.filter(category__iexact=category)
        return qs

    def create(self, request, *args, **kwargs):
        description = request.data.get('description') or request.data.get('name')
        if not description or not str(description).strip():
            return Response({'detail': 'Diagnosis description is required.'}, status=status.HTTP_400_BAD_REQUEST)
        
        description = str(description).strip()
        category = request.data.get('category', 'General') or 'General'
        icd10_code = request.data.get('icd10_code', '').strip()
        icd11_code = request.data.get('icd11_code', '').strip()

        # Check if diagnosis already exists (case-insensitive)
        existing = PatientDiagnosis.objects.filter(description__iexact=description).first()
        if existing:
            if not existing.is_active:
                existing.is_active = True
            if icd11_code and not existing.icd11_code:
                existing.icd11_code = icd11_code
            if icd10_code and not existing.icd10_code:
                existing.icd10_code = icd10_code
            existing.save()
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)

        diagnosis = PatientDiagnosis.objects.create(
            description=description,
            category=category,
            icd10_code=icd10_code,
            icd11_code=icd11_code,
            is_active=True
        )
        serializer = self.get_serializer(diagnosis)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='who-icd11')
    def who_icd11(self, request):
        """
        Query official WHO ICD-11 classifications via NIH Clinical Table Search Service.
        Supports query by ICD-11 code (e.g. '1F40', 'BA00', 'CA40', '5A11') or disease keywords.
        Returns array of [{code, title, category, is_local, source}]
        """
        query = (
            request.query_params.get('search') or 
            request.query_params.get('terms') or 
            request.query_params.get('code') or ''
        ).strip()
        if not query or len(query) < 2:
            return Response([])

        import urllib.request
        import urllib.parse
        import json

        results = []
        seen_codes = set()

        # 1. First check matching entries in local PatientDiagnosis
        try:
            local_matches = PatientDiagnosis.objects.filter(
                Q(icd11_code__icontains=query) |
                Q(description__icontains=query) |
                Q(icd10_code__icontains=query)
            ).filter(is_active=True)[:10]

            for m in local_matches:
                code_val = m.icd11_code or m.icd10_code or 'LOCAL'
                results.append({
                    'code': code_val,
                    'title': m.description,
                    'category': m.category or 'Clinical',
                    'source': 'Hospital Database',
                    'is_local': True,
                    'id': m.id,
                })
                if code_val:
                    seen_codes.add(code_val.upper())
        except Exception:
            pass

        # 2. Query external WHO / NIH ICD-11 Clinical Tables API
        try:
            encoded_query = urllib.parse.quote(query)
            url = f"https://clinicaltables.nlm.nih.gov/api/icd11_codes/v3/search?terms={encoded_query}&maxList=25"
            req = urllib.request.Request(
                url,
                headers={'User-Agent': 'Clinic365-ICD11-Lookup/1.0'}
            )
            with urllib.request.urlopen(req, timeout=4) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                # NIH format: [total_count, [codes], None, [[code, title, type], ...]]
                if isinstance(data, list) and len(data) >= 4 and isinstance(data[3], list):
                    for item in data[3]:
                        if isinstance(item, list) and len(item) >= 2:
                            c = str(item[0]).strip()
                            t = str(item[1]).strip()
                            if c.upper() not in seen_codes:
                                seen_codes.add(c.upper())
                                results.append({
                                    'code': c,
                                    'title': t,
                                    'category': 'WHO ICD-11',
                                    'source': 'WHO ICD-11 (Official)',
                                    'is_local': False,
                                })
        except Exception:
            # If network request fails or times out, return local matches
            pass

        return Response(results)

    @action(detail=False, methods=['post'], url_path='import-icd11')
    def import_icd11(self, request):
        """
        Directly import/link an ICD-11 entry selected by the doctor into the local database
        """
        code = str(request.data.get('code', '')).strip()
        title = str(request.data.get('title') or request.data.get('description', '')).strip()
        category = str(request.data.get('category', 'WHO ICD-11')).strip() or 'WHO ICD-11'

        if not title:
            return Response({'detail': 'Diagnosis title is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Check existing by title or icd11_code
        existing = PatientDiagnosis.objects.filter(description__iexact=title).first()
        if not existing and code:
            existing = PatientDiagnosis.objects.filter(icd11_code__iexact=code).first()

        if existing:
            if code and not existing.icd11_code:
                existing.icd11_code = code
            if not existing.is_active:
                existing.is_active = True
            existing.save()
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)

        created = PatientDiagnosis.objects.create(
            description=title,
            category=category,
            icd11_code=code,
            is_active=True
        )
        serializer = self.get_serializer(created)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request):
        """
        Bulk import clinical diagnoses via uploaded file (.xlsx, .xls, .csv)
        or via raw JSON payload: {"items": [{"description": "...", "category": "...", "icd10_code": "..."}]}
        """
        records_to_process = []
        uploaded_file = request.FILES.get('file')

        if uploaded_file:
            filename = uploaded_file.name.lower()
            try:
                if filename.endswith('.csv'):
                    import io, csv
                    decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                    reader = csv.DictReader(io.StringIO(decoded_file))
                    for row in reader:
                        clean_row = {str(k).strip().lower(): v for k, v in row.items() if k}
                        description = (
                            clean_row.get('description')
                            or clean_row.get('name')
                            or clean_row.get('diagnosis')
                            or clean_row.get('disease')
                        )
                        if description and str(description).strip():
                            category = clean_row.get('category') or clean_row.get('type') or 'General'
                            icd10_code = clean_row.get('icd10_code') or clean_row.get('icd_code') or clean_row.get('code') or ''
                            records_to_process.append({
                                'description': str(description).strip(),
                                'category': str(category).strip() or 'General',
                                'icd10_code': str(icd10_code).strip(),
                            })
                elif filename.endswith(('.xlsx', '.xls')):
                    import pandas as pd
                    import io
                    df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                    df.columns = [str(c).strip().lower() for c in df.columns]
                    for _, row in df.iterrows():
                        description = (
                            row.get('description')
                            or row.get('name')
                            or row.get('diagnosis')
                            or row.get('disease')
                        )
                        if pd.notna(description) and str(description).strip():
                            category = row.get('category') if pd.notna(row.get('category')) else 'General'
                            icd10_code = row.get('icd10_code') if pd.notna(row.get('icd10_code')) else (row.get('code') if pd.notna(row.get('code')) else '')
                            icd11_code = row.get('icd11_code') if pd.notna(row.get('icd11_code')) else (row.get('icd11') if pd.notna(row.get('icd11')) else '')
                            records_to_process.append({
                                'description': str(description).strip(),
                                'category': str(category).strip() or 'General',
                                'icd10_code': str(icd10_code).strip(),
                                'icd11_code': str(icd11_code).strip(),
                            })
                else:
                    return Response(
                        {'detail': 'Unsupported file format. Please upload an Excel (.xlsx, .xls) or CSV file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response(
                    {'detail': f'Error parsing file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif 'items' in request.data:
            items = request.data.get('items', [])
            for it in items:
                if isinstance(it, dict) and (it.get('description') or it.get('name')):
                    records_to_process.append({
                        'description': str(it.get('description') or it.get('name')).strip(),
                        'category': str(it.get('category') or 'General').strip(),
                        'icd10_code': str(it.get('icd10_code') or '').strip(),
                        'icd11_code': str(it.get('icd11_code') or '').strip(),
                    })

        if not records_to_process:
            return Response(
                {'detail': 'No valid diagnosis records found. Ensure column "description" or "diagnosis" exists in the file.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        created_count = 0
        updated_count = 0
        for item in records_to_process:
            desc_text = item['description']
            cat_text = item['category']
            code_text = item['icd10_code']
            code11_text = item.get('icd11_code', '')

            existing = PatientDiagnosis.objects.filter(description__iexact=desc_text).first()
            if existing:
                existing.category = cat_text or existing.category
                if code_text:
                    existing.icd10_code = code_text
                if code11_text:
                    existing.icd11_code = code11_text
                existing.is_active = True
                existing.save()
                updated_count += 1
            else:
                PatientDiagnosis.objects.create(
                    description=desc_text,
                    category=cat_text or 'General',
                    icd10_code=code_text,
                    icd11_code=code11_text,
                    is_active=True
                )
                created_count += 1

        total = created_count + updated_count
        return Response({
            'success': True,
            'message': f'Successfully processed {total} diagnoses: {created_count} added, {updated_count} updated.',
            'created_count': created_count,
            'updated_count': updated_count,
            'total_count': total,
        })

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        from django.http import HttpResponse
        csv_content = (
            "description,category,icd10_code,icd11_code\r\n"
            "Malaria (Uncomplicated),General,B54,1F40.Z\r\n"
            "Essential Hypertension,Cardiovascular,I10,BA00\r\n"
            "Acute Gastroenteritis,Gastrointestinal,A09,1A40\r\n"
            "Type 2 Diabetes Mellitus,Endocrine,E11,5A11\r\n"
            "Enteric Fever (Typhoid),Infectious,A01.0,1A07.0\r\n"
            "Bronchial Asthma,Respiratory,J45,CA23\r\n"
        )
        response = HttpResponse(csv_content, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="diagnoses_bulk_import_template.csv"'
        return response


class PresentingComplaintViewSet(viewsets.ModelViewSet):
    queryset = PresentingComplaint.objects.all().order_by('category', 'name')
    serializer_class = PresentingComplaintSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        include_inactive = self.request.query_params.get('all', 'false').lower() == 'true'
        if not include_inactive:
            qs = qs.filter(is_active=True)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(category__icontains=search)
            )
        category = self.request.query_params.get('category', '').strip()
        if category and category != 'all':
            qs = qs.filter(category__iexact=category)
        return qs

    def create(self, request, *args, **kwargs):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Complaint name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        category = request.data.get('category', 'general').strip() or 'general'

        # Check existing (case-insensitive)
        existing = PresentingComplaint.objects.filter(name__iexact=name).first()
        if existing:
            if not existing.is_active:
                existing.is_active = True
                existing.save()
            serializer = self.get_serializer(existing)
            return Response(serializer.data, status=status.HTTP_200_OK)

        complaint = PresentingComplaint.objects.create(
            name=name,
            category=category,
            is_active=True
        )
        serializer = self.get_serializer(complaint)
        return Response(serializer.data, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='categories')
    def categories(self, request):
        return Response([
            {'value': k, 'label': v}
            for k, v in PresentingComplaint.CATEGORY_CHOICES
        ])

    @action(detail=False, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request):
        """
        Bulk import presenting complaints via uploaded file (.xlsx, .xls, .csv)
        or via raw JSON payload: {"items": [{"name": "...", "category": "..."}]}
        """
        records_to_process = []
        uploaded_file = request.FILES.get('file')

        if uploaded_file:
            filename = uploaded_file.name.lower()
            try:
                if filename.endswith('.csv'):
                    import io, csv
                    decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                    reader = csv.DictReader(io.StringIO(decoded_file))
                    for row in reader:
                        clean_row = {str(k).strip().lower(): v for k, v in row.items() if k}
                        name = clean_row.get('name') or clean_row.get('complaint') or clean_row.get('description')
                        if name and str(name).strip():
                            cat = clean_row.get('category') or 'general'
                            records_to_process.append({
                                'name': str(name).strip(),
                                'category': str(cat).strip().lower() or 'general',
                            })
                elif filename.endswith(('.xlsx', '.xls')):
                    import pandas as pd
                    import io
                    df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                    df.columns = [str(c).strip().lower() for c in df.columns]
                    for _, row in df.iterrows():
                        name = row.get('name') or row.get('complaint') or row.get('description')
                        if pd.notna(name) and str(name).strip():
                            cat = row.get('category') if pd.notna(row.get('category')) else 'general'
                            records_to_process.append({
                                'name': str(name).strip(),
                                'category': str(cat).strip().lower() or 'general',
                            })
            except Exception as e:
                return Response(
                    {'success': False, 'detail': f'Error reading uploaded file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        else:
            items = request.data.get('items', [])
            if isinstance(items, list):
                for it in items:
                    name = it.get('name') or it.get('complaint') or it.get('description')
                    if name and str(name).strip():
                        cat = it.get('category') or 'general'
                        records_to_process.append({
                            'name': str(name).strip(),
                            'category': str(cat).strip().lower() or 'general',
                        })

        if not records_to_process:
            return Response(
                {'success': False, 'detail': 'No valid complaint records found in upload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        valid_categories = dict(PresentingComplaint.CATEGORY_CHOICES)
        created_count = 0
        updated_count = 0

        for rec in records_to_process:
            name = rec['name']
            cat = rec['category']
            if cat not in valid_categories:
                found_key = None
                for k, v in valid_categories.items():
                    if cat in v.lower() or cat == k.lower():
                        found_key = k
                        break
                cat = found_key or 'general'

            existing = PresentingComplaint.objects.filter(name__iexact=name).first()
            if existing:
                updated = False
                if not existing.is_active:
                    existing.is_active = True
                    updated = True
                if updated:
                    existing.save()
                    updated_count += 1
            else:
                PresentingComplaint.objects.create(
                    name=name,
                    category=cat,
                    is_active=True
                )
                created_count += 1

        total = created_count + updated_count
        return Response({
            'success': True,
            'message': f'Successfully processed {total} complaints: {created_count} added, {updated_count} updated.',
            'created_count': created_count,
            'updated_count': updated_count,
            'total_count': total,
        })

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        from django.http import HttpResponse
        csv_content = (
            "name,category\r\n"
            "Fever / Chills,general\r\n"
            "Severe Throbbing Headache,neurological\r\n"
            "Chest Pain / Tightness,cardiovascular\r\n"
            "Persistent Dry Cough,cardiovascular\r\n"
            "Acute Abdominal Pain,gastrointestinal\r\n"
            "Joint Pain & Stiffness,musculoskeletal\r\n"
            "Dysuria / Painful Urination,genitourinary\r\n"
            "Sore Throat,ent\r\n"
            "Skin Rash / Pruritus,dermatological\r\n"
            "Blurred Vision,eye\r\n"
        )
        response = HttpResponse(csv_content, content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="presenting_complaints_template.csv"'
        return response



class VisitPurposeViewSet(viewsets.ModelViewSet):
    queryset = VisitPurpose.objects.all().order_by('purpose')
    serializer_class = VisitPurposeSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['purpose']
    ordering_fields = ['purpose', 'price', 'specialist_id']

    @action(detail=False, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request):
        """
        Bulk import visit purposes via uploaded file (.xlsx, .xls, .csv)
        or via raw JSON payload: {"items": [{"purpose": "...", "price": 1000, "specialist_id": 0}]}
        """
        records_to_process = []
        uploaded_file = request.FILES.get('file')

        if uploaded_file:
            filename = uploaded_file.name.lower()
            try:
                if filename.endswith('.csv'):
                    import io, csv
                    decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                    reader = csv.DictReader(io.StringIO(decoded_file))
                    for row in reader:
                        clean_row = {str(k).strip().lower(): v for k, v in row.items() if k}
                        purpose = (
                            clean_row.get('purpose')
                            or clean_row.get('name')
                            or clean_row.get('purpose of visit')
                            or clean_row.get('visit purpose')
                        )
                        if purpose and str(purpose).strip():
                            price = clean_row.get('price') or clean_row.get('cost') or clean_row.get('fee') or 0
                            specialist_id = clean_row.get('specialist_id') or clean_row.get('specialist') or 0
                            records_to_process.append({
                                'purpose': str(purpose).strip(),
                                'price': price,
                                'specialist_id': specialist_id,
                            })
                elif filename.endswith(('.xlsx', '.xls')):
                    import pandas as pd
                    import io
                    df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                    df.columns = [str(c).strip().lower() for c in df.columns]
                    for _, row in df.iterrows():
                        purpose = (
                            row.get('purpose')
                            or row.get('name')
                            or row.get('purpose of visit')
                            or row.get('visit purpose')
                        )
                        if pd.notna(purpose) and str(purpose).strip():
                            price = row.get('price') if pd.notna(row.get('price')) else (row.get('fee') if pd.notna(row.get('fee')) else 0)
                            specialist_id = row.get('specialist_id') if pd.notna(row.get('specialist_id')) else 0
                            records_to_process.append({
                                'purpose': str(purpose).strip(),
                                'price': price,
                                'specialist_id': specialist_id,
                            })
                else:
                    return Response(
                        {'detail': 'Unsupported file format. Please upload an Excel (.xlsx, .xls) or CSV file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response(
                    {'detail': f'Error parsing file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif 'items' in request.data:
            items = request.data.get('items', [])
            for it in items:
                if isinstance(it, dict) and it.get('purpose'):
                    records_to_process.append({
                        'purpose': str(it.get('purpose')).strip(),
                        'price': it.get('price', 0),
                        'specialist_id': it.get('specialist_id', 0),
                    })

        if not records_to_process:
            return Response(
                {'detail': 'No valid purpose records found in the uploaded file or payload. Please ensure the column "purpose" is provided.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        created_count = 0
        updated_count = 0
        for item in records_to_process:
            purpose_text = item['purpose']
            try:
                price_val = int(float(str(item.get('price') or 0).replace(',', '').strip()))
            except (ValueError, TypeError):
                price_val = 0
            try:
                specialist_val = int(float(str(item.get('specialist_id') or 0).strip()))
            except (ValueError, TypeError):
                specialist_val = 0

            obj, created = VisitPurpose.objects.update_or_create(
                purpose=purpose_text,
                defaults={
                    'price': price_val,
                    'specialist_id': specialist_val,
                }
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        return Response({
            'success': True,
            'message': f'Successfully processed {len(records_to_process)} records ({created_count} created, {updated_count} updated).',
            'created_count': created_count,
            'updated_count': updated_count,
            'total_processed': len(records_to_process),
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        """
        Download CSV template for bulk importing visit purposes.
        """
        from django.http import HttpResponse
        import csv

        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="visit_purposes_template.csv"'

        writer = csv.writer(response)
        writer.writerow(['purpose', 'price'])
        writer.writerow(['General Consultation', '2000'])
        writer.writerow(['Specialist Consultation', '5000'])
        writer.writerow(['Antenatal Clinic (ANC)', '3000'])
        writer.writerow(['Pediatric Review', '2500'])
        writer.writerow(['Dental Examination', '4000'])
        writer.writerow(['Eye Clinic / Ophthalmology', '4000'])
        writer.writerow(['Routine Health Checkup', '3500'])

        return response


class PatientAppointmentViewSet(viewsets.ModelViewSet):
    queryset = PatientAppointment.objects.all().select_related('patient', 'provider').order_by('-arrival_date', '-arrival_time', '-created_date')
    serializer_class = PatientAppointmentSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = StandardResultsSetPagination
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = [
        'patient__surname', 'patient__first_name', 'patient__other_name',
        'patient__hospital_number', 'patient__phone_number',
        'clinician', 'purpose', 'provider__fullname', 'provider__username'
    ]
    ordering_fields = ['arrival_date', 'arrival_time', 'created_date', 'completed']

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient', None)
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        provider_id = self.request.query_params.get('provider', None)
        if provider_id:
            qs = qs.filter(provider_id=provider_id)

        status_filter = self.request.query_params.get('status', None)
        today = timezone.localdate()
        now_time = timezone.localtime().time()

        if status_filter == 'today':
            qs = qs.filter(arrival_date=today).order_by('completed', '-arrival_time', '-created_date', '-id')
        elif status_filter == 'upcoming':
            qs = qs.filter(arrival_date__gt=today, completed=0).order_by('-arrival_date', '-arrival_time', '-created_date', '-id')
        elif status_filter == 'completed':
            qs = qs.filter(completed=1).order_by('-arrival_date', '-arrival_time', '-created_date', '-id')
        elif status_filter == 'cancelled':
            qs = qs.filter(completed=2).order_by('-arrival_date', '-arrival_time', '-created_date', '-id')
        elif status_filter == 'expired':
            qs = qs.filter(arrival_date__lt=today, completed=0).order_by('-arrival_date', '-arrival_time', '-created_date', '-id')
        else:
            qs = qs.order_by('-arrival_date', '-arrival_time', '-created_date', '-id')

        date_param = self.request.query_params.get('date', None)
        if date_param:
            qs = qs.filter(arrival_date=date_param).order_by('completed', '-arrival_time', '-created_date', '-id')

        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        provider = serializer.validated_data.get('provider') or user
        clinician = serializer.validated_data.get('clinician')
        if not clinician and provider:
            clinician = provider.fullname or provider.username
        serializer.save(provider=provider, clinician=clinician)

    @action(detail=True, methods=['post'], url_path='cancel')
    def cancel_appointment(self, request, pk=None):
        appointment = self.get_object()
        if appointment.has_actions_taken():
            return Response(
                {
                    'detail': 'Cannot cancel this appointment: Clinical actions (such as vitals taken, consultation held, or requests placed) have already been initiated for this patient.'
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        appointment.completed = 2
        appointment.save(update_fields=['completed'])
        return Response({'detail': 'Appointment cancelled successfully.', 'status': 'cancelled'})

    @action(detail=True, methods=['post'], url_path='complete')
    def complete_appointment(self, request, pk=None):
        appointment = self.get_object()
        appointment.completed = 1
        appointment.save(update_fields=['completed'])
        return Response({'detail': 'Appointment marked as completed.', 'status': 'completed'})

    @action(detail=False, methods=['get'], url_path='summary')
    def summary(self, request):
        today = timezone.localdate()
        all_count = PatientAppointment.objects.count()
        today_count = PatientAppointment.objects.filter(arrival_date=today).count()
        upcoming_count = PatientAppointment.objects.filter(arrival_date__gt=today, completed=0).count()
        completed_count = PatientAppointment.objects.filter(completed=1).count()
        cancelled_count = PatientAppointment.objects.filter(completed=2).count()
        expired_count = PatientAppointment.objects.filter(arrival_date__lt=today, completed=0).count()

        return Response({
            'total': all_count,
            'today': today_count,
            'upcoming': upcoming_count,
            'completed': completed_count,
            'cancelled': cancelled_count,
            'expired': expired_count,
        })


# Billings ViewSets
class InvoiceViewSet(viewsets.ModelViewSet):
    queryset = Invoice.objects.all().select_related('patient', 'patient__sponsor', 'patient__plan', 'patient__category', 'category', 'staff').order_by('-created_date')
    serializer_class = InvoiceSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['invoice_number', 'product', 'patient__surname', 'patient__first_name', 'patient__hospital_number']

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient', None)
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        completed = self.request.query_params.get('completed', None)
        if completed is not None:
            qs = qs.filter(completed=completed)
        return qs

    def perform_create(self, serializer):
        import uuid
        from django.utils import timezone
        user = self.request.user if self.request.user.is_authenticated else None
        if not user and self.request.data.get('staff'):
            try:
                from users.models import User
                user = User.objects.filter(id=self.request.data.get('staff')).first()
            except Exception:
                pass
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        invoice_number = serializer.validated_data.get('invoice_number')
        if not invoice_number:
            invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"
        invoice = serializer.save(staff=user, category=category, invoice_number=invoice_number)
        if patient:
            try:
                tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
                tu.invoice_ids = invoice_number
                tu.invoice_raised = (tu.invoice_raised or 0) + (invoice.price or 0)
                tu.total_invoiced_items = (tu.total_invoiced_items or 0) + 1
                tu.save()
            except Exception:
                pass

    @action(detail=False, methods=['post'], url_path='create-consultation-bills')
    def create_consultation_bills(self, request):
        import uuid
        from django.utils import timezone
        from django.db import transaction
        from Billings.models import TransactionUpdate
        from queue_operations.models import OtherService

        patient_id = request.data.get('patient_id') or request.data.get('patient')
        if not patient_id:
            return Response({'error': 'patient_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            patient = PatientProfile.objects.select_related('sponsor', 'plan', 'category').get(id=patient_id)
        except PatientProfile.DoesNotExist:
            return Response({'error': 'Patient not found'}, status=status.HTTP_404_NOT_FOUND)

        prescriptions = request.data.get('prescriptions', [])
        lab_orders = request.data.get('lab_orders', [])
        radiology_orders = request.data.get('radiology_orders', [])
        other_service_orders = request.data.get('other_service_orders', [])

        user = request.user if request.user.is_authenticated else None
        category = patient.category

        # Payment option determination
        payment_option = request.data.get('payment_option')
        if not payment_option:
            if patient.plan and patient.plan.plan:
                payment_option = patient.plan.plan
            elif patient.sponsor and patient.sponsor.name:
                payment_option = patient.sponsor.name
            else:
                payment_option = 'Cash'

        # Each bill generation must have its own unique invoice number
        invoice_number = f"INV-{uuid.uuid4().hex[:8].upper()}"

        invoices_to_create = []
        total_amount = 0

        with transaction.atomic():
            # 1. Prescriptions
            for p in prescriptions:
                drug_name = (p.get('drug') or p.get('item') or '').strip()
                if not drug_name:
                    continue
                qty = int(p.get('dispense_quantity') or p.get('qty') or 1)
                rate = p.get('tariff_rate')
                if rate is None or rate == '':
                    try:
                        from inventory.models import PharmacyTariff
                        t = PharmacyTariff.objects.filter(product_name__icontains=drug_name).first()
                        rate = t.rate if t else 0
                    except Exception:
                        rate = 0
                try:
                    unit_price = int(round(float(rate)))
                except (ValueError, TypeError):
                    unit_price = 0

                disp_detail = p.get('dispense_detail') or ''
                product_label = f"{drug_name} ({disp_detail})" if disp_detail else drug_name

                invoices_to_create.append(Invoice(
                    patient=patient,
                    invoice_number=invoice_number,
                    product=product_label[:60],
                    qty=qty,
                    price=int(round(unit_price * qty)),
                    discount=0,
                    payment_option=payment_option,
                    category=category,
                    staff=user,
                    completed=0,
                    original_source_model='prescriptions',
                    original_source_id=p.get('id') if isinstance(p.get('id'), int) and p.get('id') < 2147483647 else None,
                ))
                total_amount += (unit_price * qty)

            # 2. Laboratory Orders
            for l in lab_orders:
                test_name = (l.get('test') or l.get('item') or '').strip()
                if not test_name:
                    continue
                qty = 1
                rate = l.get('tariff_rate')
                if rate is None or rate == '':
                    try:
                        from radio_lab.models import RadioLabInventory
                        t = RadioLabInventory.objects.filter(item__icontains=test_name, type='L').first()
                        rate = t.rate if t else 0
                    except Exception:
                        rate = 0
                try:
                    unit_price = int(round(float(rate)))
                except (ValueError, TypeError):
                    unit_price = 0

                product_label = f"Lab: {test_name}"
                invoices_to_create.append(Invoice(
                    patient=patient,
                    invoice_number=invoice_number,
                    product=product_label[:60],
                    qty=qty,
                    price=unit_price,
                    discount=0,
                    payment_option=payment_option,
                    category=category,
                    staff=user,
                    completed=0,
                    original_source_model='lab',
                ))
                total_amount += unit_price

                # Also insert RadiologyLab for the Laboratory queue
                try:
                    RadiologyLab.objects.create(
                        item=test_name,
                        item_type='L',
                        rate=unit_price,
                        patient=patient,
                        category=category,
                        plan=patient.plan,
                        staff=user,
                        billing_waiting_status=1,
                        completed=0,
                    )
                except Exception as ex:
                    print("Error creating RadiologyLab test record:", ex)

            # 3. Radiology & Scans Orders
            for r in radiology_orders:
                scan_name = (r.get('scan') or r.get('item') or '').strip()
                if not scan_name:
                    continue
                qty = 1
                rate = r.get('tariff_rate')
                if rate is None or rate == '':
                    try:
                        from radio_lab.models import RadioLabInventory
                        t = RadioLabInventory.objects.filter(item__icontains=scan_name, type='R').first()
                        rate = t.rate if t else 0
                    except Exception:
                        rate = 0
                try:
                    unit_price = int(round(float(rate)))
                except (ValueError, TypeError):
                    unit_price = 0

                is_purse = bool(r.get('is_pay_from_purse') or r.get('payment_mode') == 'pay_from_purse')
                scan_payment_option = 'Cash' if is_purse else payment_option
                purse_suffix = ' [Pay from your purse]' if is_purse else ''
                product_label = f"Scan: {scan_name}{purse_suffix}"

                invoices_to_create.append(Invoice(
                    patient=patient,
                    invoice_number=invoice_number,
                    product=product_label[:60],
                    qty=qty,
                    price=unit_price,
                    discount=0,
                    payment_option=scan_payment_option,
                    category=category,
                    staff=user,
                    completed=0,
                    original_source_model='radiology',
                ))
                total_amount += unit_price

                # Also insert RadiologyLab for the Radiology queue
                try:
                    rad_comment = (r.get('comment') or r.get('notes') or '').strip()
                    if is_purse and '[Pay from your purse]' not in rad_comment:
                        rad_comment = f"[Pay from your purse] {rad_comment}".strip()

                    RadiologyLab.objects.create(
                        item=scan_name,
                        item_type='R',
                        rate=unit_price,
                        comment=rad_comment,
                        patient=patient,
                        category=category,
                        plan=patient.plan,
                        staff=user,
                        billing_waiting_status=1,
                        completed=0,
                    )
                except Exception as ex:
                    print("Error creating RadiologyLab scan record:", ex)

            # 4. Other Clinical Services Orders
            for s in other_service_orders:
                service_name = (s.get('service') or s.get('item') or '').strip()
                if not service_name:
                    continue
                qty = 1
                rate = s.get('tariff_rate')
                if rate is None or rate == '':
                    try:
                        from myAdmins.models import OtherService2
                        t = OtherService2.objects.filter(service__icontains=service_name).first()
                        rate = t.rate if t else 0
                    except Exception:
                        rate = 0
                try:
                    unit_price = int(round(float(rate)))
                except (ValueError, TypeError):
                    unit_price = 0

                product_label = f"Service: {service_name}"
                invoices_to_create.append(Invoice(
                    patient=patient,
                    invoice_number=invoice_number,
                    product=product_label[:60],
                    qty=qty,
                    price=unit_price,
                    discount=0,
                    payment_option=payment_option,
                    category=category,
                    staff=user,
                    completed=0,
                    original_source_model='other_services',
                ))
                total_amount += unit_price

                # Also insert OtherService for ward / clinical procedures tracking
                try:
                    OtherService.objects.create(
                        patient=patient,
                        provider=user,
                        category=category,
                        plan=patient.plan,
                        purpose=service_name,
                        price=unit_price,
                        completed=0,
                    )
                except Exception as ex:
                    print("Error creating OtherService record:", ex)

            # Bulk create all invoices
            if invoices_to_create:
                Invoice.objects.bulk_create(invoices_to_create)

                # Update or create TransactionUpdate for billing overview
                try:
                    tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
                    tu.invoice_ids = invoice_number
                    tu.invoice_raised = (tu.invoice_raised or 0) + total_amount
                    tu.total_invoiced_items = (tu.total_invoiced_items or 0) + len(invoices_to_create)
                    if user:
                        tu.staff = user
                    tu.save()
                except Exception as ex:
                    print("Error updating TransactionUpdate:", ex)

        return Response({
            'status': 'success',
            'invoice_number': invoice_number,
            'items_count': len(invoices_to_create),
            'total_amount': total_amount,
            'message': f'Successfully routed {len(invoices_to_create)} item(s) to billing for payment (Invoice #{invoice_number})'
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='save-consultation-orders')
    def save_consultation_orders(self, request):
        """
        Doctor consultation: persists prescribed medications, lab investigations,
        radiology scans, and other clinical services into their respective queue models
        without pre-generating invoices. Creates/updates TransactionUpdate so patient
        immediately appears in the Encounters Billing Queue.
        """
        import uuid
        from django.db import transaction
        from Billings.models import TransactionUpdate
        from queue_operations.models import OtherService, WrittenPrescriptions, DoctorWaitingList
        from radio_lab.models import RadiologyLab
        from inventory.models import PharmacyTariff
        from radio_lab.models import RadioLabInventory
        from myAdmins.models import OtherService2

        patient_id = request.data.get('patient_id') or request.data.get('patient')
        if not patient_id:
            return Response({'error': 'patient_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            patient = PatientProfile.objects.select_related('sponsor', 'plan', 'category').get(id=patient_id)
        except PatientProfile.DoesNotExist:
            return Response({'error': 'Patient not found'}, status=status.HTTP_404_NOT_FOUND)

        prescriptions = request.data.get('prescriptions', [])
        lab_orders = request.data.get('lab_orders', [])
        radiology_orders = request.data.get('radiology_orders', [])
        other_service_orders = request.data.get('other_service_orders', [])

        user = request.user if request.user.is_authenticated else None
        if not user:
            user = User.objects.filter(is_staff=True).first() or User.objects.first()
        category = patient.category

        saved_counts = {'prescriptions': 0, 'lab': 0, 'radiology': 0, 'services': 0}

        with transaction.atomic():
            # 1. Prescriptions
            for p in prescriptions:
                drug_name = (p.get('drug') or p.get('item') or '').strip()
                if not drug_name:
                    continue
                disp_qty = int(p.get('dispense_quantity') or p.get('qty') or 1)
                dosage_form = p.get('dosage_form') or 'Tablet'
                strength = p.get('strength') or ''
                dose_qty = str(p.get('dose_qty') or '1')
                dose_unit = p.get('dose_unit') or ('tab' if dosage_form == 'Tablet' else 'ml')
                frequency = p.get('frequency') or 'Twice daily (bd)'
                duration = str(p.get('duration') or '5')
                duration_unit = p.get('duration_unit') or 'Day(s)'
                dispense_unit = p.get('dispense_unit') or ('Bottles' if dosage_form in ['Syrup', 'Suspension'] else 'Pieces')
                dispense_detail = p.get('dispense_detail') or ''
                comment = p.get('comment') or p.get('notes') or ''
                start_date = p.get('start_date') or timezone.now().date()
                instruction = p.get('instruction') or f"{dose_qty} {dose_unit} {frequency} for {duration} {duration_unit}"

                if p.get('is_pay_from_purse') or p.get('payment_mode') == 'pay_from_purse':
                    if not comment:
                        comment = '[Pay from your purse]'
                    elif '[Pay from your purse]' not in comment:
                        comment = f"[Pay from your purse] {comment}".strip()

                # Avoid duplicate insertion if exact prescription already pending today
                existing_rx = WrittenPrescriptions.objects.filter(
                    patient=patient, item=drug_name[:200], status='pending',
                    created_date__date=timezone.now().date()
                ).first()
                if not existing_rx:
                    WrittenPrescriptions.objects.create(
                        patient=patient,
                        provider=user,
                        item=drug_name[:200],
                        instruction=instruction,
                        quantity=disp_qty,
                        dosage_form=dosage_form,
                        strength=strength,
                        dose_qty=dose_qty,
                        dose_unit=dose_unit,
                        frequency=frequency,
                        duration=duration,
                        duration_unit=duration_unit,
                        dispense_unit=dispense_unit,
                        dispense_quantity=disp_qty,
                        dispense_detail=dispense_detail,
                        comment=comment,
                        start_date=start_date,
                        status='pending'
                    )
                saved_counts['prescriptions'] += 1

            # 2. Laboratory Orders
            for l in lab_orders:
                test_name = (l.get('test') or l.get('item') or '').strip()
                if not test_name:
                    continue
                rate = l.get('tariff_rate')
                if rate is None or rate == '':
                    t = RadioLabInventory.objects.filter(item__icontains=test_name, type='L').first()
                    rate = t.rate if t else 0
                try:
                    unit_price = float(rate)
                except (ValueError, TypeError):
                    unit_price = 0

                comment = (l.get('comment') or l.get('notes') or '').strip()
                if l.get('is_pay_from_purse') or l.get('payment_mode') == 'pay_from_purse':
                    if not comment:
                        comment = '[Pay from your purse]'
                    elif '[Pay from your purse]' not in comment:
                        comment = f"[Pay from your purse] {comment}".strip()

                existing_lab = RadiologyLab.objects.filter(
                    patient=patient, item=test_name, item_type='L', completed=0,
                    created_date__date=timezone.now().date()
                ).first()
                if not existing_lab:
                    RadiologyLab.objects.create(
                        item=test_name,
                        item_type='L',
                        rate=unit_price,
                        comment=comment,
                        patient=patient,
                        category=category,
                        plan=patient.plan,
                        staff=user,
                        billing_waiting_status=1,
                        completed=0,
                    )
                saved_counts['lab'] += 1

            # 3. Radiology Scans
            for r in radiology_orders:
                scan_name = (r.get('scan') or r.get('item') or '').strip()
                if not scan_name:
                    continue
                rate = r.get('tariff_rate')
                if rate is None or rate == '':
                    t = RadioLabInventory.objects.filter(item__icontains=scan_name, type='R').first()
                    rate = t.rate if t else 0
                try:
                    unit_price = float(rate)
                except (ValueError, TypeError):
                    unit_price = 0

                comment = (r.get('comment') or r.get('notes') or '').strip()
                if r.get('is_pay_from_purse') or r.get('payment_mode') == 'pay_from_purse':
                    if not comment:
                        comment = '[Pay from your purse]'
                    elif '[Pay from your purse]' not in comment:
                        comment = f"[Pay from your purse] {comment}".strip()

                existing_rad = RadiologyLab.objects.filter(
                    patient=patient, item=scan_name, item_type='R', completed=0,
                    created_date__date=timezone.now().date()
                ).first()
                if not existing_rad:
                    RadiologyLab.objects.create(
                        item=scan_name,
                        item_type='R',
                        rate=unit_price,
                        comment=comment,
                        patient=patient,
                        category=category,
                        plan=patient.plan,
                        staff=user,
                        billing_waiting_status=1,
                        completed=0,
                    )
                saved_counts['radiology'] += 1

            # 4. Other Clinical Services
            for s in other_service_orders:
                service_name = (s.get('service') or s.get('item') or '').strip()
                if not service_name:
                    continue
                rate = s.get('tariff_rate')
                if rate is None or rate == '':
                    t = OtherService2.objects.filter(service__icontains=service_name).first()
                    rate = t.rate if t else 0
                try:
                    unit_price = float(rate)
                except (ValueError, TypeError):
                    unit_price = 0

                existing_srv = OtherService.objects.filter(
                    patient=patient, purpose=service_name, completed=0,
                    created_date__date=timezone.now().date()
                ).first()
                if not existing_srv:
                    OtherService.objects.create(
                        patient=patient,
                        provider=user,
                        category=category,
                        plan=patient.plan,
                        purpose=service_name,
                        price=int(unit_price),
                        completed=0,
                    )
                saved_counts['services'] += 1

            # Update TransactionUpdate record
            tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
            tu.updated_date = timezone.now()
            tu.save()

            # Mark active doctor waiting list as consultation done
            DoctorWaitingList.objects.filter(patient=patient, completed=0).update(
                waiting_status=1,
                encounter_status=1,
                completed_by=getattr(user, 'fullname', 'Doctor') if user else 'Doctor'
            )

        total_saved = sum(saved_counts.values())
        return Response({
            'status': 'success',
            'saved_counts': saved_counts,
            'total_items': total_saved,
            'message': f'Consultation orders ({total_saved} items) routed to Encounters Billing Queue for cashier generation.'
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['get'], url_path='encounter-billing-queue')
    def encounter_billing_queue(self, request):
        """
        Returns list of patients for the Encounters Billing Queue:
        1. Defaults to patients scheduled for TODAY, with support for filtering by date ('YYYY-MM-DD' or 'all').
        2. Includes patients with active appointments, unbilled doctor prescriptions, lab tests, radiology scans,
           and clinical procedures.
        3. Pre-populates Registration Fee (if new/unpaid) and Consultation Fee (so patient pays before doctor consults),
           along with all doctor prescribed drugs, lab investigations, radiology scans, and services.
        4. Supports filtering by patient name, card number (hospital_number), phone number, and policy number.
        """
        from datetime import datetime
        from django.utils import timezone
        from Billings.models import TransactionUpdate, Invoice
        from queue_operations.models import OtherService, WrittenPrescriptions, DoctorWaitingList, NurseWaitingList, PatientEncounter, VisitPurpose, RegFee, GetRegistrationFee
        from radio_lab.models import RadiologyLab
        from inventory.models import PharmacyTariff
        from radio_lab.models import RadioLabInventory
        from myAdmins.models import OtherService2
        from patients.models import PatientAppointment

        # Filter parameters
        filter_date_param = request.query_params.get('date', '').strip()
        search_query = request.query_params.get('search', '').strip().lower()
        card_query = request.query_params.get('card_no', '').strip().lower()
        phone_query = request.query_params.get('phone', '').strip().lower()
        name_query = request.query_params.get('patient_name', '').strip().lower()

        # Date handling: default is today
        today = timezone.localdate()
        target_date = today

        if filter_date_param.lower() == 'all':
            target_date = None
        elif filter_date_param and filter_date_param.lower() != 'today':
            try:
                target_date = datetime.strptime(filter_date_param, '%Y-%m-%d').date()
            except (ValueError, TypeError):
                target_date = today

        # Gather target patient IDs
        unbilled_patient_ids = set()

        if target_date:
            # 1. Appointments scheduled for target date
            appt_pids = PatientAppointment.objects.filter(
                arrival_date=target_date, completed__in=[0, 1]
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(appt_pids)

            # 2. Patients registered on target date or with pending registration fee on target date
            reg_pids = PatientProfile.objects.filter(
                created_date__date=target_date
            ).values_list('id', flat=True).distinct()
            unbilled_patient_ids.update(reg_pids)

            reg_fee_pids = GetRegistrationFee.objects.filter(
                created_date__date=target_date, completed=0
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(reg_fee_pids)

            # 3. Active unbilled clinical orders created on target date
            rx_pids = WrittenPrescriptions.objects.filter(
                status='pending', created_date__date=target_date
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(rx_pids)

            lab_pids = RadiologyLab.objects.filter(
                completed=0, created_date__date=target_date
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(lab_pids)

            srv_pids = OtherService.objects.filter(
                completed=0, created_date__date=target_date
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(srv_pids)

            nw_pids = NurseWaitingList.objects.filter(
                completed=0, created_date__date=target_date
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(nw_pids)

            dw_pids = DoctorWaitingList.objects.filter(
                completed=0, created_date__date=target_date
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(dw_pids)

            tu_pids = TransactionUpdate.objects.filter(
                completed=0, created_date__date=target_date
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(tu_pids)
        else:
            # When target_date is None ("All Dates")
            appt_pids = PatientAppointment.objects.filter(
                completed__in=[0, 1]
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(appt_pids)

            reg_fee_pids = GetRegistrationFee.objects.filter(
                completed=0
            ).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(reg_fee_pids)

            rx_pids = WrittenPrescriptions.objects.filter(status='pending').values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(rx_pids)

            lab_pids = RadiologyLab.objects.filter(completed=0).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(lab_pids)

            srv_pids = OtherService.objects.filter(completed=0).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(srv_pids)

            nw_pids = NurseWaitingList.objects.filter(completed=0).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(nw_pids)

            dw_pids = DoctorWaitingList.objects.filter(completed=0).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(dw_pids)

            tu_pids = TransactionUpdate.objects.filter(completed=0).values_list('patient_id', flat=True).distinct()
            unbilled_patient_ids.update(tu_pids)

        unbilled_patient_ids.discard(None)

        results = []
        patients = PatientProfile.objects.filter(id__in=unbilled_patient_ids).select_related(
            'sponsor', 'sponsor__category', 'plan', 'category'
        )

        for pat in patients:
            pat_name = f"{pat.surname} {pat.first_name} {pat.other_name or ''}".strip()
            hosp_num = pat.hospital_number or ''
            phone_num = pat.phone_number or ''
            sponsor_name = pat.sponsor.name if pat.sponsor else 'Self-Pay / Cash'
            plan_name = pat.plan.plan if pat.plan else 'Private / Standard'
            policy_num = getattr(pat.plan, 'policy_number', None) or getattr(pat, 'insurance_policy_number', None) or 'N/A'
            tag_num = f"{pat.id + 380}"

            # Determine HMO vs Private:
            # 1. Check sponsor category first (e.g., ISALU HOSPITALS PRIVATE -> Category: Private)
            if pat.sponsor and pat.sponsor.category:
                is_hmo = ('hmo' in pat.sponsor.category.category.lower())
            # 2. Check patient profile category
            elif pat.category:
                is_hmo = ('hmo' in pat.category.category.lower())
            # 3. Fallback heuristics on sponsor / plan name
            elif pat.sponsor:
                s_name = (pat.sponsor.name or '').lower()
                if any(w in s_name for w in ['private', 'self-pay', 'self pay', 'cash']):
                    is_hmo = False
                elif any(w in s_name for w in ['hmo', 'nhis', 'insurance', 'managed care']):
                    is_hmo = True
                else:
                    is_hmo = False
            else:
                is_hmo = False

            category_name = 'HMO' if is_hmo else (pat.category.category if pat.category else 'Private')

            # Filter checks
            if card_query and card_query not in hosp_num.lower():
                continue
            if phone_query and phone_query not in phone_num.lower():
                continue
            if name_query and name_query not in pat_name.lower():
                continue
            if search_query:
                combined_text = f"{pat_name} {hosp_num} {phone_num} {sponsor_name} {plan_name} {policy_num} TAG #: {tag_num}".lower()
                if search_query not in combined_text:
                    continue

            # Find appointments for target_date or latest appointments
            if target_date:
                appts = list(PatientAppointment.objects.filter(patient=pat, arrival_date=target_date, completed__in=[0, 1]).order_by('arrival_time', 'id'))
                if not appts:
                    appts = list(PatientAppointment.objects.filter(patient=pat, arrival_date=target_date).order_by('arrival_time', 'id'))
                latest_dw = DoctorWaitingList.objects.filter(patient=pat, created_date__date=target_date).order_by('-created_date').first()
                latest_nw = NurseWaitingList.objects.filter(patient=pat, created_date__date=target_date).order_by('-created_date').first()
                latest_enc = PatientEncounter.objects.filter(patient=pat, created_at__date=target_date).order_by('-created_at').first()
            else:
                appts = list(PatientAppointment.objects.filter(patient=pat, completed__in=[0, 1]).order_by('-arrival_date', 'arrival_time', 'id')[:5])
                latest_dw = DoctorWaitingList.objects.filter(patient=pat).order_by('-created_date').first()
                latest_nw = NurseWaitingList.objects.filter(patient=pat).order_by('-created_date').first()
                latest_enc = PatientEncounter.objects.filter(patient=pat).order_by('-created_at').first()

            appt = appts[0] if appts else None

            # Collect all distinct consultation purposes for this patient on this encounter/date
            purposes_list = []
            seen_purposes_lower = set()

            def add_purpose_tokens(raw_string, appt_id=None, visit_type='New-case', clinician=''):
                if not raw_string:
                    return
                # Split any compound strings (e.g., "Pediatric Review, Dental Examination, Routine Health Checkup")
                parts = [p.strip() for p in str(raw_string).split(',') if p.strip()]
                for p_text in parts:
                    clean_lower = p_text.lower()
                    if clean_lower not in seen_purposes_lower:
                        seen_purposes_lower.add(clean_lower)
                        purposes_list.append({
                            'purpose': p_text,
                            'appointment_id': appt_id,
                            'visit_type': visit_type,
                            'clinician': clinician,
                        })

            for a in appts:
                add_purpose_tokens(a.purpose, appt_id=a.id, visit_type=a.visit_type or 'New-case', clinician=a.clinician or '')

            if latest_dw and latest_dw.purpose:
                clin = getattr(latest_dw.staff, 'fullname', None) or latest_dw.staff.get_full_name() if latest_dw.staff else ''
                add_purpose_tokens(latest_dw.purpose, appt_id=None, visit_type='Follow-up', clinician=clin)

            if latest_nw and latest_nw.purpose:
                add_purpose_tokens(latest_nw.purpose, appt_id=None, visit_type='Follow-up', clinician='')

            if not purposes_list:
                default_p = (pat.category.category if pat.category else '') or 'General Consultation'
                add_purpose_tokens(default_p, appt_id=None, visit_type='New-case' if getattr(pat, 'is_new', False) else 'Follow-up', clinician='')

            all_purposes_str = ", ".join([p['purpose'] for p in purposes_list])
            all_purposes_arr = [p['purpose'] for p in purposes_list]
            purpose = all_purposes_str

            seen_by = 'Dr. Attending Physician'
            clinicians = [p['clinician'] for p in purposes_list if p.get('clinician')]
            if clinicians:
                seen_by = clinicians[0]
            elif appt and appt.clinician:
                seen_by = appt.clinician
            elif latest_dw and latest_dw.staff:
                seen_by = getattr(latest_dw.staff, 'fullname', None) or latest_dw.staff.get_full_name() or f"Dr. {latest_dw.staff.username}"
            elif latest_nw and latest_nw.attendant:
                seen_by = getattr(latest_nw.attendant, 'fullname', None) or latest_nw.attendant.get_full_name() or f"Nurse {latest_nw.attendant.username}"
            elif latest_enc and latest_enc.provider:
                seen_by = getattr(latest_enc.provider, 'fullname', None) or latest_enc.provider.get_full_name() or f"Dr. {latest_enc.provider.username}"

            visit_date_raw = target_date or (appt.arrival_date if appt and appt.arrival_date else None) or (latest_dw.created_date.date() if latest_dw and latest_dw.created_date else None) or (latest_nw.created_date.date() if latest_nw and latest_nw.created_date else None) or (pat.created_date.date() if pat.created_date else today)
            visit_date_str = visit_date_raw.strftime('%d/%m/%Y')
            visit_time_str = appt.arrival_time.strftime('%I:%M%p') if (appt and appt.arrival_time) else (latest_dw.created_date.strftime('%I:%M%p') if (latest_dw and latest_dw.created_date) else '09:00AM')
            visit_datetime_str = f"{visit_time_str} {visit_date_raw.strftime('%d %b %Y')}"
            visit_type = (appt.visit_type if appt and appt.visit_type else '') or purposes_list[0]['visit_type'] or 'Follow-up'

            default_payment_option = 'Claim' if is_hmo else 'Cash'

            # Gather all billable items for this patient
            items = []

            # -------------------------------------------------------------
            # A. Patient Registration & Card Fee (if new or unpaid)
            # -------------------------------------------------------------
            already_registered = Invoice.objects.filter(patient=pat, product__icontains='Registration').exists() or GetRegistrationFee.objects.filter(patient=pat, completed=1).exists()
            is_new_case = (visit_type == 'New-case')
            has_unbilled_reg = GetRegistrationFee.objects.filter(patient=pat, completed=0).exists()

            reg_date_match = True
            if target_date and pat.created_date:
                reg_date_match = (pat.created_date.date() == target_date)

            if not already_registered and (reg_date_match or is_new_case or has_unbilled_reg):
                reg_obj = GetRegistrationFee.objects.filter(patient=pat, completed=0).first()
                if reg_obj and reg_obj.price:
                    reg_price = float(reg_obj.price)
                else:
                    rf = RegFee.objects.first()
                    reg_price = float(rf.price) if rf else 2500.0

                items.append({
                    'id': f"reg_{pat.id}",
                    'service_item': 'Patient Registration & Card Fee',
                    'uom': 'Each',
                    'quantity': 1,
                    'rate': reg_price,
                    'discount': 0,
                    'total': reg_price,
                    'payment_option': default_payment_option,
                    'compulsory_pa_code': False,
                    'bill': True,
                    'pa_code': '',
                    'category': 'registration',
                    'original_model': 'GetRegistrationFee',
                    'original_id': pat.id,
                })

            # -------------------------------------------------------------
            # B. Consultation Fee(s) for All Scheduled Purposes
            # -------------------------------------------------------------
            consult_date_check = target_date or today
            has_clinical_visit = bool(appts or latest_dw or latest_nw or latest_enc)

            if has_clinical_visit:
                existing_consult_invoices = Invoice.objects.filter(
                    patient=pat,
                    product__icontains='Consultation',
                    created_date__date=consult_date_check
                )
                invoiced_count = existing_consult_invoices.count()
                matched_invoices_count = 0
                seen_consult_fees_lower = set()

                for p_entry in purposes_list:
                    p_name = p_entry['purpose']
                    p_name_clean = p_name.strip()
                    if not p_name_clean:
                        continue
                    if p_name_clean.lower() in seen_consult_fees_lower:
                        continue
                    seen_consult_fees_lower.add(p_name_clean.lower())

                    # Specific check: if an invoice already specifically exists for this purpose
                    if existing_consult_invoices.filter(product__icontains=p_name_clean).exists():
                        matched_invoices_count += 1
                        continue

                    # If total invoices on this date already cover all purposes
                    if invoiced_count >= len(purposes_list):
                        continue

                    # If generic invoices exist that haven't been matched
                    if invoiced_count > matched_invoices_count:
                        matched_invoices_count += 1
                        continue

                    # Determine consultation rate for this specific purpose
                    vp = VisitPurpose.objects.filter(purpose__iexact=p_name).first()
                    if not vp:
                        vp = VisitPurpose.objects.filter(purpose__icontains=p_name.split()[0]).first()

                    if vp and vp.price:
                        consult_price = float(vp.price)
                    else:
                        p_lower = p_name.lower()
                        if any(s in p_lower for s in ['specialist', 'cardiology', 'dental', 'eye', 'pediatric', 'antenatal', 'anc']):
                            consult_price = 5000.0
                        else:
                            consult_price = 2000.0

                    items.append({
                        'id': f"consult_{pat.id}_{p_entry['appointment_id'] or p_name.replace(' ', '_')}",
                        'service_item': f"Consultation Fee: {p_name}",
                        'uom': 'Each',
                        'quantity': 1,
                        'rate': consult_price,
                        'discount': 0,
                        'total': consult_price,
                        'payment_option': default_payment_option,
                        'compulsory_pa_code': False,
                        'bill': True,
                        'pa_code': '',
                        'category': 'consultation',
                        'original_model': 'PatientAppointment' if p_entry['appointment_id'] else 'DoctorWaitingList',
                        'original_id': p_entry['appointment_id'] or pat.id,
                    })

            # -------------------------------------------------------------
            # C. Prescriptions (Prescribed drugs from doctor)
            # -------------------------------------------------------------
            if target_date:
                rx_items = WrittenPrescriptions.objects.filter(patient=pat, status='pending', created_date__date=target_date).order_by('created_date')
            else:
                rx_items = WrittenPrescriptions.objects.filter(patient=pat, status='pending').order_by('created_date')

            for rx in rx_items:
                t = PharmacyTariff.objects.filter(product_name__icontains=rx.item).first()
                rate = float(t.rate) if (t and t.rate) else 0.0
                qty = rx.dispense_quantity or rx.quantity or 1
                uom = rx.dispense_unit or ('Bottles' if rx.dosage_form in ['Syrup', 'Suspension'] else 'Each')
                disp_desc = f" ({rx.dispense_detail})" if rx.dispense_detail else ''

                is_purse = ('[Pay from your purse]' in (rx.comment or '') or '[Pay from purse]' in (rx.instruction or ''))
                rx_payment_option = 'Cash' if is_purse else default_payment_option
                purse_tag = ' [Pay from your purse]' if is_purse else ''

                items.append({
                    'id': f"rx_{rx.id}",
                    'service_item': f"{rx.item}{disp_desc}{purse_tag}",
                    'uom': uom,
                    'quantity': qty,
                    'rate': rate,
                    'discount': 0,
                    'total': round(qty * rate, 2),
                    'payment_option': rx_payment_option,
                    'compulsory_pa_code': False,
                    'bill': True,
                    'pa_code': '',
                    'category': 'prescription',
                    'original_model': 'WrittenPrescriptions',
                    'original_id': rx.id,
                })

            # -------------------------------------------------------------
            # D. Investigations (Laboratory Tests & Radiology Scans)
            # -------------------------------------------------------------
            if target_date:
                rad_lab_items = RadiologyLab.objects.filter(patient=pat, completed=0, created_date__date=target_date).order_by('created_date')
            else:
                rad_lab_items = RadiologyLab.objects.filter(patient=pat, completed=0).order_by('created_date')

            for rl in rad_lab_items:
                rate = float(rl.rate or 0)
                is_lab = (rl.item_type == 'L')
                label_prefix = "Lab: " if is_lab else "Scan: "
                uom = "Tests" if is_lab else "Scans"

                is_purse = ('[Pay from your purse]' in (rl.comment or ''))
                rl_payment_option = 'Cash' if is_purse else default_payment_option
                purse_tag = ' [Pay from your purse]' if is_purse else ''

                items.append({
                    'id': f"rl_{rl.id}",
                    'service_item': f"{label_prefix}{rl.item}{purse_tag}",
                    'uom': uom,
                    'quantity': 1,
                    'rate': rate,
                    'discount': 0,
                    'total': rate,
                    'payment_option': rl_payment_option,
                    'compulsory_pa_code': False,
                    'bill': True,
                    'pa_code': '',
                    'category': 'investigation',
                    'original_model': 'RadiologyLab',
                    'original_id': rl.id,
                })

            # -------------------------------------------------------------
            # E. Other Clinical Services & Procedures
            # -------------------------------------------------------------
            if target_date:
                other_services = OtherService.objects.filter(patient=pat, completed=0, created_date__date=target_date).order_by('created_date')
            else:
                other_services = OtherService.objects.filter(patient=pat, completed=0).order_by('created_date')

            for os in other_services:
                rate = float(os.price or 0)
                items.append({
                    'id': f"os_{os.id}",
                    'service_item': f"Service: {os.purpose}",
                    'uom': 'Each',
                    'quantity': 1,
                    'rate': rate,
                    'discount': 0,
                    'total': rate,
                    'payment_option': default_payment_option,
                    'compulsory_pa_code': False,
                    'bill': True,
                    'pa_code': '',
                    'category': 'service',
                    'original_model': 'OtherService',
                    'original_id': os.id,
                })

            rx_count = len([it for it in items if it['category'] == 'prescription'])
            inv_count = len([it for it in items if it['category'] == 'investigation'])
            srv_count = len([it for it in items if it['category'] == 'service'])

            # Query invoices generated for this patient on target date to track settlements
            if target_date:
                settled_invoices_qs = Invoice.objects.filter(
                    patient=pat,
                    created_date__date=target_date
                ).order_by('created_date')
            else:
                settled_invoices_qs = Invoice.objects.filter(
                    patient=pat,
                    created_date__date=today
                ).order_by('created_date')

            settled_invoices_today = []
            for inv in settled_invoices_qs:
                unit_p = float(inv.price or 0)
                inv_qty = int(inv.qty or 1)
                disc = float(inv.discount or 0)
                inv_tot = float(unit_p * inv_qty * (1 - (disc / 100.0)))
                settled_invoices_today.append({
                    'id': inv.id,
                    'invoice_number': inv.invoice_number or f"INV-{inv.id}",
                    'service_item': inv.product or 'Hospital Service',
                    'quantity': inv_qty,
                    'rate': unit_p,
                    'discount': disc,
                    'total': inv_tot,
                    'payment_option': inv.payment_option or 'Cash',
                    'completed': bool(inv.completed),
                    'created_time': inv.created_date.strftime('%I:%M %p') if inv.created_date else '',
                })

            consult_inv = next((it for it in settled_invoices_today if 'consultation' in (it['service_item'] or '').lower()), None)
            consultation_settled = consult_inv is not None
            consultation_settled_amount = float(consult_inv['total']) if consult_inv else 0.0

            reg_inv = next((it for it in settled_invoices_today if 'registration' in (it['service_item'] or '').lower()), None)
            registration_settled = reg_inv is not None
            registration_settled_amount = float(reg_inv['total']) if reg_inv else 0.0

            total_invoiced_today = sum(it['total'] for it in settled_invoices_today)
            total_paid_today = sum(it['total'] for it in settled_invoices_today if it['completed'])
            has_pending_items = len(items) > 0

            # If filtering by target_date, skip patient if they have no billable items and no settled invoices
            if target_date and not items and not settled_invoices_today:
                continue

            results.append({
                'patient_id': pat.id,
                'patient_name': pat_name,
                'hospital_number': hosp_num,
                'phone_number': phone_num,
                'category': category_name,
                'is_hmo': is_hmo,
                'sponsor': sponsor_name,
                'plan': plan_name,
                'policy_number': policy_num,
                'tag_number': tag_num,
                'gender': getattr(pat, 'gender', '') or 'N/A',
                'age': pat.get_age if hasattr(pat, 'get_age') and pat.get_age is not None else '',
                'address': pat.address or 'N/A',
                'session_number': getattr(appt, 'id', None) or f"{pat.id}{today.strftime('%d%m')}",
                'visit_date': visit_date_str,
                'visit_time': visit_time_str,
                'visit_datetime': visit_datetime_str,
                'purpose': purpose,
                'purposes': all_purposes_arr,
                'purposes_count': len(all_purposes_arr),
                'purposes_list': purposes_list,
                'visit_type': visit_type,
                'seen_by': seen_by,
                'prescriptions_count': rx_count,
                'investigations_count': inv_count,
                'services_count': srv_count,
                'has_consultation_fee': any(it['category'] == 'consultation' for it in items),
                'consultation_fees_count': len([it for it in items if it['category'] == 'consultation']),
                'has_registration_fee': any(it['category'] == 'registration' for it in items),
                'total_items_count': len(items),
                'billable_items': items,
                'settled_invoices_today': settled_invoices_today,
                'consultation_settled': consultation_settled,
                'consultation_settled_amount': consultation_settled_amount,
                'registration_settled': registration_settled,
                'registration_settled_amount': registration_settled_amount,
                'total_invoiced_today': total_invoiced_today,
                'total_paid_today': total_paid_today,
                'has_pending_items': has_pending_items,
            })

        return Response(results, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='generate-encounter-bill')
    def generate_encounter_bill(self, request):
        """
        Called when cashier reviews the Combined Encounter Bill modal and clicks
        'Generate Invoice' or 'Pay & Clear Bill'. Creates Invoice records, marks source records as billed,
        optionally records Receipt settlement, and creates/updates TransactionUpdate for the patient.
        """
        import uuid
        import random
        from django.db import transaction
        from Billings.models import TransactionUpdate, Receipt
        from queue_operations.models import OtherService, WrittenPrescriptions, NurseWaitingList, GetRegistrationFee
        from radio_lab.models import RadiologyLab
        from patients.models import PatientAppointment

        patient_id = request.data.get('patient_id')
        if not patient_id:
            return Response({'error': 'patient_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            patient = PatientProfile.objects.select_related('sponsor', 'plan', 'category').get(id=patient_id)
        except PatientProfile.DoesNotExist:
            return Response({'error': 'Patient not found'}, status=status.HTTP_404_NOT_FOUND)

        selected_items = request.data.get('items', [])
        if not selected_items:
            return Response({'error': 'No billable items selected to generate invoice.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        staff_id = request.data.get('staff_id')
        if not user and staff_id:
            try:
                from users.models import User
                user = User.objects.filter(id=staff_id).first()
            except Exception:
                pass
        category = patient.category
        mark_as_paid = bool(request.data.get('mark_as_paid', False))

        # Check if patient is HMO or Private category / sponsor:
        # 1. Sponsor category (e.g., ISALU HOSPITALS PRIVATE -> Private)
        if patient.sponsor and patient.sponsor.category:
            is_hmo = ('hmo' in patient.sponsor.category.category.lower())
        # 2. Patient profile category
        elif category:
            is_hmo = ('hmo' in category.category.lower())
        # 3. Fallback heuristics on sponsor / plan name
        elif patient.sponsor:
            s_name = (patient.sponsor.name or '').lower()
            if any(w in s_name for w in ['private', 'self-pay', 'self pay', 'cash']):
                is_hmo = False
            elif any(w in s_name for w in ['hmo', 'nhis', 'insurance', 'managed care']):
                is_hmo = True
            else:
                is_hmo = False
        else:
            is_hmo = False

        bill_type_req = request.data.get('bill_type')
        if bill_type_req == 'claim':
            is_hmo = True
        elif bill_type_req == 'invoice':
            is_hmo = False

        from django.utils import timezone
        today = timezone.localdate() if hasattr(timezone, 'localdate') else timezone.now().date()
        prefix = 'CLM-' if is_hmo else 'INV-'

        # Unify all bills created for the patient today into ONE invoice / claim for the day
        existing_today = Invoice.objects.filter(
            patient=patient,
            created_date__date=today
        ).exclude(invoice_number__isnull=True).exclude(invoice_number='').order_by('created_date').first()

        if existing_today and existing_today.invoice_number:
            invoice_number = existing_today.invoice_number
            if not user and existing_today.staff:
                user = existing_today.staff
        else:
            invoice_number = f"{prefix}{uuid.uuid4().hex[:8].upper()}"

        receipt_number = f"REC-{random.randint(10000, 99999)}" if mark_as_paid else None
        invoices_to_create = []
        total_amount = 0.0

        with transaction.atomic():
            for item in selected_items:
                product_name = str(item.get('service_item') or item.get('product') or '').strip()
                if not product_name:
                    continue

                qty = int(item.get('quantity') or item.get('qty') or 1)
                rate = float(item.get('rate') or 0)
                discount = int(item.get('discount') or 0)
                pay_option = item.get('payment_option') or ('Claim' if is_hmo else 'Cash')
                pa_code = item.get('pa_code') or item.get('auth_code') or ''

                item_total = float(item.get('total') or (qty * rate * (1 - discount / 100.0)))
                orig_model = item.get('original_model') or ''
                orig_id = item.get('original_id')
                label = product_name[:60]

                # Prevent recording duplicate invoice items if user clicks create bill multiple times
                is_duplicate = False
                if orig_model and orig_id:
                    is_duplicate = Invoice.objects.filter(
                        patient=patient,
                        invoice_number=invoice_number,
                        original_source_model=orig_model[:50],
                        original_source_id=int(orig_id)
                    ).exists()
                else:
                    is_duplicate = Invoice.objects.filter(
                        patient=patient,
                        invoice_number=invoice_number,
                        product=label
                    ).exists()

                if is_duplicate:
                    continue

                total_amount += item_total

                invoices_to_create.append(Invoice(
                    patient=patient,
                    invoice_number=invoice_number,
                    product=label,
                    qty=qty,
                    price=int(round(item_total)),
                    discount=discount,
                    payment_option=pay_option,
                    category=category,
                    staff=user,
                    completed=1 if mark_as_paid else 0,
                    original_source_model=orig_model[:50] if orig_model else None,
                    original_source_id=int(orig_id) if isinstance(orig_id, int) and orig_id < 2147483647 else None,
                ))

                # Mark source records as billed!
                if orig_model == 'WrittenPrescriptions' and orig_id:
                    WrittenPrescriptions.objects.filter(id=orig_id).update(status='billed')
                elif orig_model == 'RadiologyLab' and orig_id:
                    RadiologyLab.objects.filter(id=orig_id).update(billing_waiting_status=0, completed=1)
                elif orig_model == 'OtherService' and orig_id:
                    OtherService.objects.filter(id=orig_id).update(completed=1)
                elif orig_model == 'NurseWaitingList' and orig_id:
                    NurseWaitingList.objects.filter(id=orig_id).update(completed=1)
                elif orig_model == 'GetRegistrationFee':
                    GetRegistrationFee.objects.filter(patient=patient).update(completed=1)
                elif orig_model in ['PatientAppointment', 'Appointment'] and orig_id:
                    # Paying consultation fee in billing settles the bill/invoice, but does NOT complete the clinical appointment.
                    # The patient is still waiting to see the doctor for their consultation encounter.
                    pass

            if invoices_to_create:
                Invoice.objects.bulk_create(invoices_to_create)

                if mark_as_paid:
                    primary_pay_opt = selected_items[0].get('payment_option') or ('Claim' if is_hmo else 'Cash')
                    Receipt.objects.create(
                        patient=patient,
                        invoice_number=invoice_number,
                        receipt_number=receipt_number,
                        remarks=f"Payment cleared for {len(invoices_to_create)} encounter item(s)",
                        total_price=int(round(total_amount)),
                        category=category,
                        payment_type=primary_pay_opt,
                        staff=user,
                    )

                # Update or create TransactionUpdate safely without MultipleObjectsReturned risk
                try:
                    tu = TransactionUpdate.objects.filter(patient=patient, completed=0).order_by('-id').first()
                    if not tu:
                        tu = TransactionUpdate(patient=patient, completed=0)
                    tu.invoice_ids = invoice_number
                    tu.invoice_raised = (tu.invoice_raised or 0) + int(round(total_amount))
                    tu.total_invoiced_items = (tu.total_invoiced_items or 0) + len(invoices_to_create)
                    if mark_as_paid:
                        tu.receipt_given = (tu.receipt_given or 0) + 1
                    if user:
                        tu.staff = user
                    tu.updated_date = timezone.now()
                    tu.save()
                except Exception as ex:
                    print("Error updating TransactionUpdate:", ex)

        staff_name = ''
        if user:
            staff_name = (getattr(user, 'fullname', None) or '').strip() or user.get_full_name() or user.username
        if not staff_name:
            staff_name = (request.data.get('staff_name') or '').strip()
        if not staff_name and existing_today and existing_today.staff:
            staff_name = (getattr(existing_today.staff, 'fullname', None) or '').strip() or existing_today.staff.get_full_name() or existing_today.staff.username
        if not staff_name:
            staff_name = 'Cashier / Billing Desk'

        bill_num_clean = invoice_number.replace('INV-', '').replace('CLM-', '')
        if not bill_num_clean.isdigit():
            # If hexadecimal uuid, map to a readable numeric bill number
            bill_num_clean = f"{abs(hash(invoice_number)) % 9000000 + 1000000}"

        now_dt = timezone.localtime()
        formatted_dt = now_dt.strftime('%d %B %Y %I:%M%p').lower()
        msg = f"{'HMO Claim' if is_hmo else 'Invoice'} #{invoice_number} successfully generated for {patient.get_full_name()}."

        # Gather previous patient balances
        prev_balance = 0.0
        try:
            prev_tu = TransactionUpdate.objects.filter(patient=patient).exclude(invoice_ids=invoice_number).order_by('-id').first()
            if prev_tu and prev_tu.invoice_raised:
                prev_balance = float(prev_tu.invoice_raised)
        except Exception:
            pass

        return Response({
            'status': 'success',
            'bill_type': 'claim' if is_hmo else 'invoice',
            'invoice_number': invoice_number,
            'bill_number': bill_num_clean,
            'receipt_number': receipt_number,
            'is_paid': mark_as_paid,
            'items_count': len(invoices_to_create),
            'total_amount': total_amount,
            'created_datetime': formatted_dt,
            'staff_name': staff_name,
            'previous_balance': prev_balance,
            'latest_balance': prev_balance + total_amount,
            'patient_data': {
                'id': patient.id,
                'name': patient.get_full_name(),
                'hospital_number': patient.hospital_number or 'N/A',
                'sponsor': patient.sponsor.name if patient.sponsor else 'Self-Pay / Cash',
                'plan': patient.plan.plan if patient.plan else 'Standard Plan',
                'policy_number': patient.insurance_policy_number or getattr(patient.plan, 'code', None) or 'NIL',
                'enrollee_number': getattr(patient, 'enrollee_number', None) or patient.insurance_policy_number or 'NIL',
                'address': patient.address or 'OGBA',
                'phone': patient.phone_number or 'N/A',
                'gender': getattr(patient, 'gender', '') or 'N/A',
                'age': patient.get_age if hasattr(patient, 'get_age') and patient.get_age is not None else '',
                'session_number': f"{patient.id}{random.randint(100000, 999999)}",
            },
            'items': selected_items,
            'message': msg
        }, status=status.HTTP_201_CREATED)

    @action(detail=False, methods=['post'], url_path='issue-receipt')
    def issue_receipt(self, request):
        """
        Settles a private patient invoice (or batch of invoices under invoice_number),
        marks them as completed=1, records official Receipt with receipt_number,
        and updates patient TransactionUpdate.
        """
        import random
        from django.db import transaction
        from Billings.models import TransactionUpdate, Receipt, Invoice

        invoice_numbers = request.data.get('invoice_numbers')
        invoice_number = request.data.get('invoice_number')
        invoice_id = request.data.get('invoice_id')
        payment_type = request.data.get('payment_type') or 'Cash'
        remarks = request.data.get('remarks') or ''
        amount_paid = request.data.get('amount_paid')

        if not invoice_numbers and invoice_number:
            invoice_numbers = [invoice_number]

        if not invoice_numbers and not invoice_id:
            return Response({'error': 'invoice_number, invoice_numbers or invoice_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if invoice_numbers:
                invoices = list(Invoice.objects.select_related('patient', 'category').filter(invoice_number__in=invoice_numbers))
            else:
                invoices = list(Invoice.objects.select_related('patient', 'category').filter(id=invoice_id))

            if not invoices:
                return Response({'error': 'Invoice not found'}, status=status.HTTP_404_NOT_FOUND)

            patient = invoices[0].patient
            inv_num = invoices[0].invoice_number or f"INV-{invoices[0].id}"
            category = invoices[0].category or (patient.category if patient else None)
            user = request.user if request.user.is_authenticated else None
            staff_id = request.data.get('staff_id')
            if not user and staff_id:
                try:
                    from users.models import User
                    user = User.objects.filter(id=staff_id).first()
                except Exception:
                    pass
            if not user and invoices[0].staff:
                user = invoices[0].staff

            # Calculate total
            total_calc = sum(float(it.price or 0) * int(it.qty or 1) * (1 - (float(it.discount or 0) / 100.0)) for it in invoices)
            final_amount = float(amount_paid) if amount_paid is not None else total_calc

            # Mark invoices as completed
            if invoice_numbers:
                Invoice.objects.filter(invoice_number__in=invoice_numbers).update(completed=1, payment_option=payment_type)
            else:
                Invoice.objects.filter(id=invoice_id).update(completed=1, payment_option=payment_type)

            receipt_number = f"REC-{random.randint(10000, 99999)}"
            receipt = Receipt.objects.create(
                patient=patient,
                invoice_number=inv_num,
                receipt_number=receipt_number,
                remarks=remarks or f"Payment settled for {len(invoices)} item(s) on {inv_num}",
                total_price=int(round(final_amount)),
                category=category,
                payment_type=payment_type,
                staff=user,
            )

            if patient:
                try:
                    tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
                    tu.receipt_given = (tu.receipt_given or 0) + 1
                    tu.save()
                except Exception:
                    pass

        return Response({
            'status': 'success',
            'receipt_number': receipt_number,
            'invoice_number': inv_num,
            'patient_name': f"{patient.surname} {patient.first_name}" if patient else 'Patient',
            'hospital_number': patient.hospital_number if patient else '',
            'sponsor': patient.sponsor.name if (patient and patient.sponsor) else 'Self-Pay / Cash',
            'total_amount': final_amount,
            'payment_type': payment_type,
            'message': f"Official Receipt #{receipt_number} successfully issued for Invoice #{inv_num} (₦{final_amount:,.2f})!"
        }, status=status.HTTP_201_CREATED)


class ReceiptViewSet(viewsets.ModelViewSet):
    queryset = Receipt.objects.all().select_related('patient', 'category', 'staff').order_by('-created_date')
    serializer_class = ReceiptSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['receipt_number', 'invoice_number', 'patient__surname', 'patient__first_name']

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient', None)
        if patient_id:
            qs = qs.filter(patient_id=patient_id)
        return qs

    def perform_create(self, serializer):
        import random
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        receipt_number = serializer.validated_data.get('receipt_number') or f"REC-{random.randint(10000, 99999)}"
        receipt = serializer.save(staff=user, category=category, receipt_number=receipt_number)
        if patient:
            try:
                tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
                tu.receipt_given = (tu.receipt_given or 0) + 1
                tu.save()
            except Exception:
                pass


class DepositViewSet(viewsets.ModelViewSet):
    queryset = Deposit.objects.all().select_related('patient', 'staff').order_by('-created_date')
    serializer_class = DepositSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]


class RefundViewSet(viewsets.ModelViewSet):
    queryset = Refund.objects.all().select_related('patient', 'staff').order_by('-created_date')
    serializer_class = RefundSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]


# IPD ViewSets
class AdmissionViewSet(viewsets.ModelViewSet):
    queryset = AdmissionTable.objects.all().select_related('patient', 'doctor_admitted').order_by('-doctor_admit_date')
    serializer_class = AdmissionTableSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        active = self.request.query_params.get('active', None)
        if active == '1':
            qs = qs.filter(doctor_discharge_status=0)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(doctor_admitted=user)

    def perform_update(self, serializer):
        status = serializer.validated_data.get('doctor_discharge_status')
        if status == 1 or status == '1':
            user = self.request.user if self.request.user.is_authenticated else None
            user_name = user.fullname if (user and hasattr(user, 'fullname') and user.fullname) else 'Doctor'
            serializer.save(
                doctor_discharge_status=1,
                doctor_discharge_date=timezone.now(),
                doctor_discharged=user_name
            )
        else:
            serializer.save()


class WardViewSet(viewsets.ModelViewSet):
    queryset = Ward.objects.all().prefetch_related('beds').order_by('ward_name')
    serializer_class = WardSerializer
    permission_classes = [permissions.AllowAny]


class BedAllocationViewSet(viewsets.ModelViewSet):
    queryset = BedAllocation.objects.all().select_related('patient', 'ward', 'bed', 'staff').order_by('-created_date')
    serializer_class = BedAllocationSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        is_active = self.request.query_params.get('active', None)
        if is_active is not None:
            qs = qs.filter(is_active=(is_active == '1'))
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        alloc = serializer.save(staff=user)
        if alloc.bed:
            alloc.bed.is_occupied = True
            alloc.bed.save()


# ANC ViewSets
class ANCRegistrationViewSet(viewsets.ModelViewSet):
    queryset = ANCRegistration.objects.all().select_related('patient', 'created_by').order_by('-visit_date')
    serializer_class = ANCRegistrationSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['patient__surname', 'patient__first_name', 'patient__hospital_number']

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save(created_by=user)


# Pharmacy ViewSets
class PharmacyDrugViewSet(viewsets.ModelViewSet):
    queryset = OpdDrugs.objects.all().select_related('staff').order_by('product_name')
    serializer_class = OpdDrugsSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['product_name', 'product_id', 'description']

    def get_queryset(self):
        qs = super().get_queryset()
        low_stock = self.request.query_params.get('low_stock', None)
        if low_stock == '1':
            qs = qs.filter(stock__lte=10)
        return qs

    def perform_create(self, serializer):
        import random
        user = self.request.user if self.request.user.is_authenticated else None
        product_id = serializer.validated_data.get('product_id') or f"DRG{random.randint(1000, 9999)}"
        serializer.save(staff=user, product_id=product_id)


# Radiology & Laboratory ViewSets
class RadioLabViewSet(viewsets.ModelViewSet):
    queryset = RadiologyLab.objects.all().select_related('patient', 'category', 'plan', 'staff').order_by('-created_date')
    serializer_class = RadiologyLabSerializer
    pagination_class = StandardResultsSetPagination
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['item', 'patient__surname', 'patient__first_name', 'patient__hospital_number']

    def get_queryset(self):
        qs = super().get_queryset()
        completed = self.request.query_params.get('completed', None)
        if completed is not None:
            qs = qs.filter(completed=completed)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        plan = serializer.validated_data.get('plan') or (patient.plan if patient else None)
        serializer.save(staff=user, category=category, plan=plan)


# Inventory ViewSets
from inventory.models import Product as InventoryProduct, Transaction as InventoryTransaction, ProductRequests as InventoryProductRequests
from .serializers import InventoryProductSerializer, InventoryTransactionSerializer, InventoryProductRequestSerializer

class InventoryProductViewSet(viewsets.ModelViewSet):
    queryset = InventoryProduct.objects.all().order_by('-created_date')
    serializer_class = InventoryProductSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['product_name', 'product_id', 'description']

    def perform_create(self, serializer):
        staff = self.request.user if self.request.user.is_authenticated else None
        serializer.save(staff=staff)


class InventoryTransactionViewSet(viewsets.ModelViewSet):
    queryset = InventoryTransaction.objects.all().order_by('-created_date')
    serializer_class = InventoryTransactionSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        staff = self.request.user if self.request.user.is_authenticated else None
        serializer.save(staff=staff)


class InventoryProductRequestViewSet(viewsets.ModelViewSet):
    queryset = InventoryProductRequests.objects.all().order_by('-created_date')
    serializer_class = InventoryProductRequestSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        staff = self.request.user if self.request.user.is_authenticated else None
        serializer.save(staff=staff)


class WrittenPrescriptionViewSet(viewsets.ModelViewSet):
    """
    Prescription and Pharmacy Dispensing ViewSet.
    Handles doctor clinical prescriptions, calculated pieces/bottles,
    and pharmacy dispensing queue.
    """
    queryset = WrittenPrescriptions.objects.all().select_related('patient', 'provider', 'dispensed_by').order_by('-created_date')
    serializer_class = WrittenPrescriptionSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        patient_id = self.request.query_params.get('patient', None)
        if patient_id:
            qs = qs.filter(patient_id=patient_id)

        status_param = self.request.query_params.get('status', None)
        if status_param:
            qs = qs.filter(status__iexact=status_param)

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(item__icontains=search) |
                Q(patient__surname__icontains=search) |
                Q(patient__first_name__icontains=search) |
                Q(patient__hospital_number__icontains=search)
            )
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        if not user or not user.is_authenticated:
            # Fallback to first available staff/superuser
            user = User.objects.filter(is_staff=True).first() or User.objects.first()
        serializer.save(provider=user)

    @action(detail=False, methods=['post'], url_path='bulk-save')
    def bulk_save(self, request):
        """
        Save multiple prescriptions at once from doctor consultation modal.
        """
        patient_id = request.data.get('patient') or request.data.get('patient_id')
        if not patient_id:
            return Response({'error': 'Patient ID is required'}, status=status.HTTP_400_BAD_REQUEST)

        patient = PatientProfile.objects.filter(id=patient_id).first()
        if not patient:
            return Response({'error': 'Patient not found'}, status=status.HTTP_404_NOT_FOUND)

        prescriptions_list = request.data.get('prescriptions', [])
        if not prescriptions_list:
            return Response({'error': 'No prescriptions provided'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        if not user or not user.is_authenticated:
            user = User.objects.filter(is_staff=True).first() or User.objects.first()

        created_items = []
        for p in prescriptions_list:
            item_name = str(p.get('item') or p.get('drug') or '').strip()
            if not item_name:
                continue

            dosage_form = p.get('dosage_form') or 'Tablet'
            route = p.get('route') or 'Oral'
            strength = p.get('strength') or ''
            dose_qty = str(p.get('dose_qty') or p.get('qty_dose') or '1')
            dose_unit = p.get('dose_unit') or p.get('unit') or 'tab'
            frequency = p.get('frequency') or 'Twice daily (bd)'
            duration = str(p.get('duration') or '5')
            duration_unit = p.get('duration_unit') or 'Day(s)'
            dispense_unit = p.get('dispense_unit') or ('Bottles' if dosage_form in ['Syrup', 'Suspension'] else 'Pieces')
            dispense_quantity = int(p.get('dispense_quantity') or p.get('quantity') or 0)
            dispense_detail = p.get('dispense_detail') or ''
            comment = p.get('comment') or p.get('notes') or ''
            start_date = p.get('start_date') or timezone.now().date()
            instruction = p.get('instruction') or f"{dose_qty} {dose_unit} ({dosage_form}) via {route}, {frequency} for {duration} {duration_unit}"

            if p.get('is_pay_from_purse') or p.get('payment_mode') == 'pay_from_purse':
                if not comment:
                    comment = '[Pay from your purse]'
                elif '[Pay from your purse]' not in comment:
                    comment = f"[Pay from your purse] {comment}".strip()

            record = WrittenPrescriptions.objects.create(
                patient=patient,
                provider=user,
                item=item_name[:200],
                instruction=instruction,
                quantity=dispense_quantity,
                dosage_form=dosage_form,
                route=route,
                strength=strength,
                dose_qty=dose_qty,
                dose_unit=dose_unit,
                frequency=frequency,
                duration=duration,
                duration_unit=duration_unit,
                dispense_unit=dispense_unit,
                dispense_quantity=dispense_quantity,
                dispense_detail=dispense_detail,
                comment=comment,
                start_date=start_date,
                status='pending'
            )
            created_items.append(record)

        serializer = self.get_serializer(created_items, many=True)
        return Response({
            'success': True,
            'count': len(created_items),
            'prescriptions': serializer.data
        }, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=['post'], url_path='dispense')
    def dispense(self, request, pk=None):
        """
        Dispense a prescription to patient, marking it dispensed and reducing stock.
        """
        prescription = self.get_object()
        if prescription.status == 'dispensed':
            return Response({'detail': 'Medication has already been dispensed.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        prescription.status = 'dispensed'
        prescription.dispensed_at = timezone.now()
        if user and user.is_authenticated:
            prescription.dispensed_by = user
        prescription.save()

        # Safely deduct from OpdDrugs inventory if matching product exists
        stock_deducted = 0
        matching_drug = OpdDrugs.objects.filter(product_name__iexact=prescription.item).first()
        if not matching_drug:
            # Try partial match
            matching_drug = OpdDrugs.objects.filter(product_name__icontains=prescription.item.split()[0]).first()

        if matching_drug and prescription.dispense_quantity > 0:
            qty_to_deduct = prescription.dispense_quantity
            matching_drug.stock = max(0, matching_drug.stock - qty_to_deduct)
            matching_drug.save(update_fields=['stock', 'status'])
            stock_deducted = qty_to_deduct

        serializer = self.get_serializer(prescription)
        return Response({
            'success': True,
            'prescription': serializer.data,
            'stock_deducted': stock_deducted,
            'remaining_stock': matching_drug.stock if matching_drug else None,
            'drug_name': matching_drug.product_name if matching_drug else None,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='queue')
    def queue(self, request):
        """
        Get pending prescriptions awaiting pharmacy dispensing.
        """
        pending = WrittenPrescriptions.objects.filter(status='pending').select_related(
            'patient', 'provider'
        ).order_by('-created_date')
        serializer = self.get_serializer(pending, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

