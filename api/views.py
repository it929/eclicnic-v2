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

from users.models import User, Category, SystemModule
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
from OPD_pharm.models import OpdDrugs, OpdDrugsUpdate
from radio_lab.models import RadiologyLab, LabResult, ScanResult
from inventory.models import (
    Product, PharmacyStore, StoreStock, StoreStockBatch,
    StockRequisition, StockRequisitionItem,
    StockTransfer, StockTransferItem, StockMovement,
    PharmacyVendor, Transaction, AdministerDrugs, PharmacyTariff
)

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
    LabResultSerializer,
    ScanResultSerializer,
    PatientAppointmentSerializer,
    PatientDiagnosisSerializer,
    PresentingComplaintSerializer,
    WrittenPrescriptionSerializer,
    ConsultationDraftSerializer,
    PharmacyStoreSerializer,
    StoreStockSerializer,
    StockTransferSerializer,
    StockTransferItemSerializer,
    StockRequisitionSerializer,
    StockRequisitionItemSerializer,
    StockMovementSerializer,
    PharmacyVendorSerializer,
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
        all_mod_codes = [m.code for m in SystemModule.objects.all()]
        for d in departments:
            staff_count = User.objects.filter(department=d).count()
            mods = d.modules if d.modules is not None else []
            # Admin & CMD departments must have all modules assigned by default
            if d.department and d.department.lower() in ['admin', 'cmd'] and len(mods) < len(all_mod_codes):
                mods = all_mod_codes
                d.modules = mods
                d.save()
            dept_list.append({
                'id': d.id,
                'department': d.department,
                'staff_count': staff_count,
                'modules': mods,
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

    @action(detail=False, methods=['get'], url_path='import-template')
    def import_template(self, request):
        import pandas as pd
        import io
        from django.http import HttpResponse

        sample_data = {
            'surname': ['Doe', 'Smith'],
            'first_name': ['John', 'Jane'],
            'other_name': ['Robert', 'Mary'],
            'dob': ['1990-05-15', '1985-11-20'],
            'gender': ['Male', 'Female'],
            'patient_type': ['Private', 'HMO'],
            'phone_number': ['08012345678', '08087654321'],
            'email_address': ['john.doe@example.com', 'jane.smith@example.com'],
            'address': ['123 Hospital Road, Ikeja', '45 Victoria Island, Lagos'],
            'category': ['Private', 'HMO'],
            'plan': ['Standard', 'Gold Plan'],
            'hospital_number': ['ISL-2026-001', 'ISL-2026-002']
        }
        df = pd.DataFrame(sample_data)
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine='openpyxl') as writer:
            df.to_excel(writer, index=False, sheet_name='Patients')
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="patients_import_template.xlsx"'
        return response

    @action(detail=False, methods=['post'], url_path='import-excel')
    def import_excel(self, request):
        uploaded_file = request.FILES.get('file') or request.FILES.get('excel_file')
        if not uploaded_file:
            return Response({'detail': 'No file uploaded. Please upload a .xlsx or .xls file.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            import pandas as pd
            import io
            df = pd.read_excel(io.BytesIO(uploaded_file.read()))
            df.columns = [str(c).strip().lower().replace(' ', '_') for c in df.columns]

            unique_cats = set(df['category'].dropna().astype(str).str.strip().unique()) if 'category' in df.columns else set()
            unique_plans = set(df['plan'].dropna().astype(str).str.strip().unique()) if 'plan' in df.columns else set()

            cat_map = {}
            for cat_name in unique_cats:
                cat_obj, _ = PatientCategory.objects.get_or_create(category=cat_name)
                cat_map[cat_name] = cat_obj

            plan_map = {}
            for plan_name in unique_plans:
                first_row = df[df['plan'].astype(str).str.strip() == plan_name].iloc[0]
                cat_obj = cat_map.get(str(first_row.get('category', '')).strip()) if 'category' in df.columns else None
                plan_obj, _ = PatientPlan.objects.get_or_create(plan=plan_name, defaults={'category': cat_obj})
                plan_map[plan_name] = plan_obj

            patients_to_create = []
            errors = []

            for index, row in df.iterrows():
                try:
                    surname = str(row.get('surname', '')).strip() if pd.notna(row.get('surname')) else ''
                    first_name = str(row.get('first_name', '')).strip() if pd.notna(row.get('first_name')) else ''
                    if not surname or not first_name:
                        continue

                    dob = row.get('dob')
                    if pd.notna(dob):
                        if isinstance(dob, pd.Timestamp):
                            dob = dob.date()
                        else:
                            from dateutil import parser
                            try:
                                dob = parser.parse(str(dob)).date()
                            except Exception:
                                dob = None
                    else:
                        dob = None

                    email = str(row.get('email_address', '')).strip() if pd.notna(row.get('email_address')) else None
                    if email and PatientProfile.objects.filter(email_address=email).exists():
                        errors.append(f"Row {index+2}: Email {email} already exists")
                        continue

                    patients_to_create.append(PatientProfile(
                        surname=surname,
                        first_name=first_name,
                        other_name=str(row.get('other_name', '')).strip() if pd.notna(row.get('other_name')) else None,
                        dob=dob,
                        gender=str(row.get('gender', '')).strip() if pd.notna(row.get('gender')) else 'Other',
                        patient_type=str(row.get('patient_type', '')).strip() if pd.notna(row.get('patient_type')) else 'General',
                        phone_number=str(row.get('phone_number', '')).strip() if pd.notna(row.get('phone_number')) else '',
                        address=str(row.get('address', '')).strip() if pd.notna(row.get('address')) else None,
                        category=cat_map.get(str(row.get('category', '')).strip()) if pd.notna(row.get('category')) else None,
                        plan=plan_map.get(str(row.get('plan', '')).strip()) if pd.notna(row.get('plan')) else None,
                        email_address=email,
                        hospital_number=str(row.get('hospital_number', '')).strip() if pd.notna(row.get('hospital_number')) else None,
                        created_by=request.user if request.user and request.user.is_authenticated else None,
                        active=1
                    ))
                except Exception as e:
                    errors.append(f"Row {index+2}: {str(e)}")

            if patients_to_create:
                PatientProfile.objects.bulk_create(patients_to_create, batch_size=500, ignore_conflicts=True)

            return Response({
                'message': f"Successfully imported {len(patients_to_create)} patients.",
                'imported_count': len(patients_to_create),
                'errors': errors[:10]
            })
        except Exception as e:
            return Response({'detail': f"File processing error: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

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

    def get_queryset(self):
        qs = super().get_queryset()
        search = self.request.query_params.get('search', None)
        if search:
            qs = qs.filter(category__icontains=search)
        return qs

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        sponsors_count = instance.sponsors.count()
        plans_count = instance.plans.count()
        patients_count = instance.patientprofile_set.count()
        if sponsors_count > 0 or plans_count > 0 or patients_count > 0:
            reasons = []
            if sponsors_count > 0:
                reasons.append(f"{sponsors_count} sponsor(s)")
            if plans_count > 0:
                reasons.append(f"{plans_count} plan(s)")
            if patients_count > 0:
                reasons.append(f"{patients_count} patient(s)")
            return Response(
                {"detail": f"Cannot delete category '{instance.category}' because it is linked to {', '.join(reasons)}. Please reassign them first."},
                status=status.HTTP_400_BAD_REQUEST
            )
        return super().destroy(request, *args, **kwargs)


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

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        """
        Download Excel (.xlsx) template for bulk uploading sponsors.
        """
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Sponsors"

        # Headers
        headers = ["S/N", "Sponsor Name", "Billing Code", "Category"]
        ws.append(headers)

        # Style header row
        header_fill = PatternFill(start_color="1F497D", end_color="1F497D", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        center_align = Alignment(horizontal="center", vertical="center")
        left_align = Alignment(horizontal="left", vertical="center")
        thin_border = Border(
            left=Side(style="thin", color="D9D9D9"),
            right=Side(style="thin", color="D9D9D9"),
            top=Side(style="thin", color="D9D9D9"),
            bottom=Side(style="thin", color="D9D9D9")
        )

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center_align

        # Export existing sponsors from database or fallback to sample rows
        existing_sponsors = Sponsor.objects.all().select_related('category').order_by('name')

        if existing_sponsors.exists():
            rows_data = []
            for idx, sponsor in enumerate(existing_sponsors, start=1):
                cat_name = sponsor.category.category if (sponsor.category and sponsor.category.category) else ""
                rows_data.append((
                    idx,
                    sponsor.name or "",
                    sponsor.code or "",
                    cat_name
                ))
        else:
            # Sample rows to guide the user if database has no sponsors yet
            rows_data = [
                (1, "AIICO MULTISHIELD", "AMH", "HMO"),
                (2, "BASTION HEALTH", "BH", "HMO"),
                (3, "TOTAL ENERGIES RETAINERSHIP", "TER", "Private Retainership"),
                (4, "FIRST BANK CORPORATE", "FBN", "Corporate"),
                (5, "ISALU STAFF SCHEME", "ISS", "Staff"),
            ]

        for r_idx, row_data in enumerate(rows_data, start=2):
            for c_idx, val in enumerate(row_data, start=1):
                cell = ws.cell(row=r_idx, column=c_idx, value=val)
                cell.border = thin_border
                cell.alignment = center_align if c_idx in [1, 3] else left_align

        # Column widths
        ws.column_dimensions["A"].width = 8
        ws.column_dimensions["B"].width = 38
        ws.column_dimensions["C"].width = 18
        ws.column_dimensions["D"].width = 24

        response = HttpResponse(
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response["Content-Disposition"] = 'attachment; filename="sponsors_bulk_upload_template.xlsx"'
        wb.save(response)
        return response

    @action(detail=False, methods=['post'], url_path='import-sponsors')
    def import_sponsors(self, request):
        """
        Import sponsors from uploaded Excel/CSV file or fallback to Sponsor.xlsx in project root.
        Supports columns: [S/N, Sponsor Name, Billing Code, Category] or [Sponsor Name, Billing Code, Category].
        """
        import os
        import csv
        import io
        import openpyxl
        from django.conf import settings

        uploaded_file = request.FILES.get('file')
        default_category_id = request.data.get('category_id') or request.data.get('category')
        
        default_category = None
        if default_category_id:
            try:
                default_category = PatientCategory.objects.get(id=default_category_id)
            except Exception:
                default_category = None

        if not default_category:
            default_category, _ = PatientCategory.objects.get_or_create(category='HMO')

        rows_data = []

        if uploaded_file:
            fname = (uploaded_file.name or '').lower()
            if fname.endswith('.csv'):
                try:
                    content = uploaded_file.read().decode('utf-8-sig')
                    reader = csv.reader(io.StringIO(content))
                    rows_data = list(reader)
                except Exception as e:
                    return Response(
                        {'detail': f'Could not read uploaded CSV file: {str(e)}'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            else:
                try:
                    wb = openpyxl.load_workbook(uploaded_file, data_only=True)
                    sheet = wb.active
                    rows_data = list(sheet.iter_rows(values_only=True))
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
                    {'detail': 'No file uploaded and Sponsor.xlsx not found in project root.'},
                    status=status.HTTP_404_NOT_FOUND
                )
            try:
                wb = openpyxl.load_workbook(found_path, data_only=True)
                sheet = wb.active
                rows_data = list(sheet.iter_rows(values_only=True))
            except Exception as e:
                return Response(
                    {'detail': f'Could not load Sponsor.xlsx: {str(e)}'},
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR
                )

        created_count = 0
        updated_count = 0
        skipped_count = 0

        # Pre-cache existing categories for quick name matching
        cat_map = {c.category.strip().upper(): c for c in PatientCategory.objects.all()}

        for row in rows_data:
            if not row or not any(row):
                continue

            cleaned_row = [str(c).strip() if c is not None else '' for c in row]
            non_empty = [c for c in cleaned_row if c]
            if not non_empty:
                continue

            # Skip header-like rows
            first_upper = non_empty[0].upper()
            if any(first_upper.startswith(hdr) for hdr in ['CURRENT HMO LIST', 'CURRENT SPONSOR', 'SN', 'S/N', 'ID', 'SPONSOR NAME', 'HMO']):
                continue

            name = None
            code = None
            category_str = None

            # Pattern A: [SN, Name, Code, Optional Category, ...]
            # Pattern B: [Name, Code, Optional Category, ...]
            if cleaned_row[0].isdigit() and len(cleaned_row) >= 3:
                name = cleaned_row[1]
                code = cleaned_row[2]
                if len(cleaned_row) >= 4 and cleaned_row[3]:
                    category_str = cleaned_row[3]
            elif len(cleaned_row) >= 2 and not cleaned_row[0].isdigit():
                # Check if col 0 is Name and col 1 is Code
                # or if col 0 is SN like '1' string
                name = cleaned_row[0]
                code = cleaned_row[1]
                if len(cleaned_row) >= 3 and cleaned_row[2]:
                    category_str = cleaned_row[2]
            elif len(cleaned_row) == 1:
                name = cleaned_row[0]
                code = ''

            if not name or name.upper() in ['HMO', 'NAME', 'SPONSOR', 'SPONSOR NAME', 'PLAN NAME']:
                skipped_count += 1
                continue

            # Determine sponsor category
            target_category = default_category
            if category_str:
                up_cat = category_str.strip().upper()
                if up_cat in cat_map:
                    target_category = cat_map[up_cat]
                else:
                    new_cat, _ = PatientCategory.objects.get_or_create(category=category_str.strip())
                    cat_map[up_cat] = new_cat
                    target_category = new_cat

            sp, created = Sponsor.objects.update_or_create(
                name=name,
                defaults={
                    'code': code if code else None,
                    'category': target_category
                }
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        return Response({
            'message': f'Sponsors processed successfully: {created_count} created, {updated_count} updated.',
            'created': created_count,
            'updated': updated_count,
            'skipped': skipped_count,
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

    def create(self, request, *args, **kwargs):
        pin_code = request.data.get('pin_code')
        if pin_code is None or str(pin_code).strip() == '':
            return Response(
                {'detail': 'Security PIN is required to authorize and complete consultation.'},
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

        # Identify attending doctor attempting this clinical authorization
        authorizing_doctor = None
        if request.user and request.user.is_authenticated:
            authorizing_doctor = request.user
        elif request.data.get('doctor_id'):
            try:
                authorizing_doctor = User.objects.filter(id=request.data.get('doctor_id'), is_active=True).first()
            except Exception:
                pass
        elif request.data.get('doctor_username'):
            authorizing_doctor = User.objects.filter(
                username__iexact=str(request.data.get('doctor_username')).strip(),
                is_active=True
            ).first()

        if not authorizing_doctor:
            return Response(
                {'detail': 'Authentication required. Please log in as an attending doctor to authorize consultation.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Check if doctor has a security PIN configured
        if not authorizing_doctor.has_pin:
            doc_name = getattr(authorizing_doctor, 'fullname', '') or authorizing_doctor.username
            return Response(
                {'detail': f'Doctor "{doc_name}" has no security PIN configured. Please set your 4-digit PIN in Profile Settings before completing consultation.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Strictly verify that the entered PIN matches the doctor's security PIN
        if not authorizing_doctor.check_pin(pin_str):
            return Response(
                {'detail': 'Incorrect Security PIN. Authorization denied.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        encounter = serializer.save(provider=authorizing_doctor)

        # Update DoctorWaitingList if patient is in active doctor queue
        patient = encounter.patient
        doc_display_name = getattr(authorizing_doctor, 'fullname', None) or authorizing_doctor.get_full_name() or authorizing_doctor.username or 'Doctor'
        if patient:
            try:
                DoctorWaitingList.objects.filter(patient=patient, completed=0).update(
                    completed=1,
                    waiting_status=1,
                    encounter_status=1,
                    completed_by=doc_display_name
                )
            except Exception:
                pass
            # Automatically clear any in-progress draft for this patient upon completing encounter
            try:
                ConsultationDraft.objects.filter(patient=patient).delete()
            except Exception:
                pass

        headers = self.get_success_headers(serializer.data)
        response_data = serializer.data
        response_data['provider_name'] = doc_display_name
        response_data['authorized_by'] = doc_display_name
        return Response(response_data, status=status.HTTP_201_CREATED, headers=headers)

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        encounter = serializer.save(provider=user)

        # Update DoctorWaitingList if patient is in active doctor queue
        patient = encounter.patient
        if patient:
            try:
                DoctorWaitingList.objects.filter(patient=patient, completed=0).update(
                    completed=1,
                    waiting_status=1,
                    encounter_status=1,
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
        uploaded_file = request.FILES.get('file')
        if not uploaded_file:
            return Response({'detail': 'No file uploaded.'}, status=status.HTTP_400_BAD_REQUEST)
        
        filename = uploaded_file.name.lower()
        records_to_process = []
        try:
            if filename.endswith('.csv'):
                import io, csv
                decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                reader = csv.DictReader(io.StringIO(decoded_file))
                for row in reader:
                    clean_row = {str(k).strip().lower(): v for k, v in row.items() if k}
                    desc = clean_row.get('description') or clean_row.get('name') or clean_row.get('diagnosis')
                    if desc and str(desc).strip():
                        records_to_process.append({
                            'description': str(desc).strip(),
                            'category': str(clean_row.get('category') or 'General').strip(),
                            'icd10_code': str(clean_row.get('icd10_code') or clean_row.get('icd10') or '').strip(),
                            'icd11_code': str(clean_row.get('icd11_code') or clean_row.get('icd11') or '').strip(),
                        })
            elif filename.endswith(('.xlsx', '.xls')):
                import pandas as pd, io
                df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                df.columns = [str(c).strip().lower() for c in df.columns]
                for _, row in df.iterrows():
                    desc = row.get('description') or row.get('name') or row.get('diagnosis')
                    if pd.notna(desc) and str(desc).strip():
                        records_to_process.append({
                            'description': str(desc).strip(),
                            'category': str(row.get('category') or 'General').strip(),
                            'icd10_code': str(row.get('icd10_code') if pd.notna(row.get('icd10_code')) else (row.get('icd10') if pd.notna(row.get('icd10')) else '')).strip(),
                            'icd11_code': str(row.get('icd11_code') if pd.notna(row.get('icd11_code')) else (row.get('icd11') if pd.notna(row.get('icd11')) else '')).strip(),
                        })
            else:
                return Response({'detail': 'Unsupported file format.'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'detail': f'Error reading file: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)

        created_count = 0
        for item in records_to_process:
            _, created = PatientDiagnosis.objects.get_or_create(
                description=item['description'],
                defaults={
                    'category': item['category'],
                    'icd10_code': item['icd10_code'],
                    'icd11_code': item['icd11_code'],
                    'is_active': True,
                }
            )
            if created:
                created_count += 1
        return Response({'success': True, 'message': f'Successfully imported {created_count} diagnoses.', 'created_count': created_count})

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
    queryset = VisitPurpose.objects.all().select_related('sponsor', 'plan', 'sponsor__category').order_by('purpose', 'sponsor__name', 'plan__plan')
    serializer_class = VisitPurposeSerializer
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['purpose', 'sponsor__name', 'sponsor__code', 'plan__plan', 'plan__code']
    ordering_fields = ['purpose', 'price', 'specialist_id', 'created_date']

    def get_queryset(self):
        qs = VisitPurpose.objects.all().select_related('sponsor', 'plan', 'sponsor__category').order_by('purpose', 'sponsor__name', 'plan__plan')

        sponsor_id = self.request.query_params.get('sponsor') or self.request.query_params.get('sponsor_id')
        plan_id = self.request.query_params.get('plan') or self.request.query_params.get('plan_id')
        patient_id = self.request.query_params.get('patient') or self.request.query_params.get('patient_id')
        search = self.request.query_params.get('search', '').strip()
        fee_filter = self.request.query_params.get('fee_filter', '').strip().lower()

        # If patient passed, resolve specific tariffs for that patient's sponsor & plan
        if patient_id:
            try:
                patient = PatientProfile.objects.select_related('sponsor', 'plan').get(id=patient_id)
                pat_sponsor = patient.sponsor
                pat_plan = patient.plan
                if pat_sponsor and pat_plan:
                    qs = qs.filter(
                        (Q(sponsor=pat_sponsor) & Q(plan=pat_plan)) |
                        (Q(sponsor=pat_sponsor) & Q(plan__isnull=True)) |
                        Q(plan=pat_plan) |
                        (Q(sponsor__isnull=True) & Q(plan__isnull=True))
                    )
                elif pat_sponsor:
                    qs = qs.filter(
                        Q(sponsor=pat_sponsor) |
                        (Q(sponsor__isnull=True) & Q(plan__isnull=True))
                    )
                else:
                    qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
            except Exception:
                pass
        else:
            if sponsor_id:
                if str(sponsor_id).lower() in ('general', 'none', 'null', 'self', 'cash'):
                    qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                elif str(sponsor_id).lower() != 'all':
                    qs = qs.filter(sponsor_id=sponsor_id)

            if plan_id:
                if str(plan_id).lower() in ('general', 'none', 'null'):
                    qs = qs.filter(plan__isnull=True)
                elif str(plan_id).lower() != 'all':
                    qs = qs.filter(plan_id=plan_id)

        if fee_filter == 'free':
            qs = qs.filter(price=0)
        elif fee_filter == 'paid':
            qs = qs.filter(price__gt=0)

        if search:
            qs = qs.filter(
                Q(purpose__icontains=search) |
                Q(sponsor__name__icontains=search) |
                Q(sponsor__code__icontains=search) |
                Q(plan__plan__icontains=search) |
                Q(plan__code__icontains=search)
            )

        return qs

    @action(detail=False, methods=['post'], url_path='load-general-prices')
    def load_general_prices(self, request):
        """
        Replicates all general out-of-pocket clinic visit purposes into a target Sponsor and/or Plan.
        Accepts optional adjustment_percent (e.g. -10 for 10% discount, 0 for same base price).
        """
        sponsor_id = request.data.get('sponsor_id')
        plan_id = request.data.get('plan_id')
        overwrite = request.data.get('overwrite', False)
        adjustment_percent = float(request.data.get('adjustment_percent', 0) or 0)

        if not sponsor_id:
            return Response({'detail': 'Please select a Sponsor / HMO Company to load tariffs for.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            sponsor = Sponsor.objects.get(id=sponsor_id)
        except Sponsor.DoesNotExist:
            return Response({'detail': 'Selected Sponsor not found.'}, status=status.HTTP_404_NOT_FOUND)

        plan = None
        if plan_id and str(plan_id).lower() not in ('all', 'null', 'none', ''):
            try:
                plan = PatientPlan.objects.get(id=plan_id)
            except PatientPlan.DoesNotExist:
                return Response({'detail': 'Selected Coverage Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        # Base purposes are those without sponsor & plan
        base_purposes = VisitPurpose.objects.filter(sponsor__isnull=True, plan__isnull=True)
        if not base_purposes.exists():
            # If no general purposes exist without sponsor, take distinct purpose names
            base_purposes = VisitPurpose.objects.all().distinct('purpose')

        multiplier = 1.0 + (adjustment_percent / 100.0)
        created_count = 0
        updated_count = 0

        for bp in base_purposes:
            new_price = max(0, int(round(bp.price * multiplier)))
            existing = VisitPurpose.objects.filter(purpose__iexact=bp.purpose, sponsor=sponsor, plan=plan).first()
            if existing:
                if overwrite:
                    existing.price = new_price
                    existing.save()
                    updated_count += 1
            else:
                VisitPurpose.objects.create(
                    purpose=bp.purpose,
                    price=new_price,
                    specialist_id=bp.specialist_id,
                    sponsor=sponsor,
                    plan=plan
                )
                created_count += 1

        plan_desc = f" ({plan.plan})" if plan else " (All Plans)"
        return Response({
            'success': True,
            'message': f'Successfully synchronized consultation tariffs for {sponsor.name}{plan_desc}: {created_count} created, {updated_count} updated.',
            'created_count': created_count,
            'updated_count': updated_count,
            'total_purposes': base_purposes.count()
        })

    @action(detail=False, methods=['post'], url_path='bulk-import')
    def bulk_import(self, request):
        """
        Bulk import visit purposes & consultation tariffs from Excel (.xlsx, .xls) or CSV.
        Supports columns: purpose, price/fee, sponsor, plan.
        Can also take default sponsor_id and plan_id from form data if rows don't specify them.
        """
        import io, csv, re
        import pandas as pd

        uploaded_file = request.FILES.get('file')

        default_sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        default_plan_id = request.data.get('plan_id') or request.data.get('plan')

        default_sponsor = None
        if default_sponsor_id and str(default_sponsor_id).lower() not in ('all', 'general', 'null', 'none', ''):
            default_sponsor = Sponsor.objects.filter(id=default_sponsor_id).first()

        default_plan = None
        if default_plan_id and str(default_plan_id).lower() not in ('all', 'general', 'null', 'none', ''):
            default_plan = PatientPlan.objects.filter(id=default_plan_id).first()

        records_to_process = []

        def extract_row_data(row_dict):
            norm = {}
            for k, v in row_dict.items():
                if k is not None:
                    clean_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
                    norm[clean_k] = v

            purpose = None
            for key_candidate in ['purposename', 'purpose', 'purposeofvisit', 'visitpurpose', 'clinicservice', 'clinic', 'name']:
                for k in norm:
                    if key_candidate in k:
                        val = norm[k]
                        if val is not None and str(val).strip() and str(val).lower() != 'nan':
                            purpose = str(val).strip()
                            break
                if purpose:
                    break

            price = 0
            for key_candidate in ['price', 'fee', 'consultationfee', 'rate', 'amount', 'tariff', 'cost']:
                for k in norm:
                    if key_candidate in k:
                        val = norm[k]
                        if val is not None and str(val).strip() and str(val).lower() != 'nan':
                            price = val
                            break
                if price:
                    break

            sponsor_val = None
            for key_candidate in ['sponsor', 'hmocompany', 'hmo', 'provider', 'company']:
                for k in norm:
                    if key_candidate in k:
                        val = norm[k]
                        if val is not None and str(val).strip() and str(val).lower() != 'nan':
                            sponsor_val = str(val).strip()
                            break
                if sponsor_val:
                    break

            plan_val = None
            for key_candidate in ['coverageplan', 'planname', 'patientplan', 'plan', 'tier']:
                for k in norm:
                    if key_candidate in k:
                        val = norm[k]
                        if val is not None and str(val).strip() and str(val).lower() != 'nan':
                            plan_val = str(val).strip()
                            break
                if plan_val:
                    break

            return purpose, price, sponsor_val, plan_val

        if uploaded_file:
            filename = uploaded_file.name.lower()
            try:
                if filename.endswith('.csv'):
                    decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                    reader = csv.DictReader(io.StringIO(decoded_file))
                    for row in reader:
                        p_name, p_price, p_spons, p_plan = extract_row_data(row)
                        if p_name:
                            records_to_process.append({
                                'purpose': p_name,
                                'price': p_price,
                                'sponsor': p_spons,
                                'plan': p_plan,
                                'specialist_id': 0,
                            })
                elif filename.endswith(('.xlsx', '.xls')):
                    df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                    for _, row in df.iterrows():
                        row_dict = row.to_dict()
                        p_name, p_price, p_spons, p_plan = extract_row_data(row_dict)
                        if p_name:
                            records_to_process.append({
                                'purpose': p_name,
                                'price': p_price,
                                'sponsor': p_spons,
                                'plan': p_plan,
                                'specialist_id': 0,
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
                        'sponsor': it.get('sponsor') or it.get('sponsor_id'),
                        'plan': it.get('plan') or it.get('plan_id'),
                        'specialist_id': it.get('specialist_id', 0),
                    })

        if not records_to_process:
            return Response(
                {'detail': 'No valid purpose records found in the uploaded file. Please make sure the file contains a "Purpose Name" column.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        sponsors_by_name = {s.name.strip().lower(): s for s in Sponsor.objects.all()}
        sponsors_by_code = {s.code.strip().lower(): s for s in Sponsor.objects.all() if s.code}
        plans_by_name = {p.plan.strip().lower(): p for p in PatientPlan.objects.all() if p.plan}

        created_count = 0
        updated_count = 0

        for item in records_to_process:
            purpose_text = item['purpose']
            try:
                price_val = int(float(str(item.get('price') or 0).replace(',', '').replace('₦', '').strip()))
            except (ValueError, TypeError):
                price_val = 0
            price_val = max(0, price_val)
            specialist_val = 0

            # Resolve sponsor
            target_sponsor = default_sponsor
            raw_sponsor = item.get('sponsor')
            if raw_sponsor:
                s_str = str(raw_sponsor).strip()
                if s_str.isdigit():
                    target_sponsor = Sponsor.objects.filter(id=int(s_str)).first()
                elif s_str.lower() in ('general', 'self', 'cash', 'out-of-pocket', 'none', 'null', ''):
                    target_sponsor = None
                else:
                    target_sponsor = sponsors_by_name.get(s_str.lower()) or sponsors_by_code.get(s_str.lower())
                    if not target_sponsor:
                        target_sponsor = Sponsor.objects.filter(name__icontains=s_str).first()

            # Resolve plan
            target_plan = default_plan
            raw_plan = item.get('plan')
            if raw_plan:
                p_str = str(raw_plan).strip()
                if p_str.isdigit():
                    target_plan = PatientPlan.objects.filter(id=int(p_str)).first()
                elif p_str.lower() in ('general', 'all', 'none', 'null', 'all plans', ''):
                    target_plan = None
                else:
                    if target_sponsor:
                        target_plan = PatientPlan.objects.filter(sponsor=target_sponsor, plan__iexact=p_str).first()
                        if not target_plan:
                            target_plan = PatientPlan.objects.filter(sponsor=target_sponsor, plan__icontains=p_str).first()
                    if not target_plan:
                        target_plan = plans_by_name.get(p_str.lower()) or PatientPlan.objects.filter(plan__icontains=p_str).first()

            obj, created = VisitPurpose.objects.update_or_create(
                purpose=purpose_text,
                sponsor=target_sponsor,
                plan=target_plan,
                defaults={
                    'price': price_val,
                    'specialist_id': specialist_val,
                }
            )
            if created:
                created_count += 1
            else:
                updated_count += 1

        target_label = target_sponsor.name if target_sponsor else "General Out-of-Pocket"
        if target_sponsor and target_plan:
            target_label += f" ({target_plan.plan} Plan)"

        return Response({
            'success': True,
            'message': f'Successfully processed {len(records_to_process)} consultation tariff records for {target_label} ({created_count} created, {updated_count} updated).',
            'created_count': created_count,
            'updated_count': updated_count,
            'total_processed': len(records_to_process),
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        """
        Download Excel (.xlsx) template for bulk importing visit purpose tariffs.
        Pre-populates with ALL existing distinct purposes currently in the database.
        Pre-fills Sponsor and Plan if provided in query params so user only enters prices.
        """
        from django.http import HttpResponse
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        sponsor_id = request.query_params.get('sponsor_id') or request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan_id') or request.query_params.get('plan')

        sp = None
        pl = None
        sponsor_str = ""
        plan_str = ""

        if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'null', 'none', ''):
            sp = Sponsor.objects.filter(id=sponsor_id).first()
            if sp:
                sponsor_str = sp.name

        if plan_id and str(plan_id).lower() not in ('all', 'general', 'null', 'none', ''):
            pl = PatientPlan.objects.filter(id=plan_id).first()
            if pl:
                plan_str = pl.plan

        # Fetch all distinct existing visit purposes in database
        db_purposes = list(
            VisitPurpose.objects.filter(purpose__isnull=False)
            .exclude(purpose='')
            .values_list('purpose', flat=True)
            .distinct()
            .order_by('purpose')
        )

        seen_lower = set()
        distinct_purposes = []
        for p in db_purposes:
            p_clean = str(p).strip()
            if p_clean and p_clean.lower() not in seen_lower:
                seen_lower.add(p_clean.lower())
                distinct_purposes.append(p_clean)

        if not distinct_purposes:
            distinct_purposes = [
                'General Consultation',
                'Specialist Consultation',
                'Antenatal Clinic (ANC)',
                'Pediatric Review',
                'Dental Examination',
                'Eye Clinic / Ophthalmology',
                'Surgical Review',
                'Cardiology First visit',
                'Cardiology follow up visit',
                'Routine Health Checkup',
                'Post-Discharge Follow-up',
                'Immunization / Child Welfare',
                'Dietary & Nutrition Counseling',
            ]

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Visit Purposes Tariffs"
        ws.views.sheetView[0].showGridLines = True

        headers = ["Purpose Name", "Sponsor", "Coverage Plan", "Price (₦)"]
        ws.append(headers)

        header_fill = PatternFill(start_color="1E3A8A", end_color="1E3A8A", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        center_align = Alignment(horizontal="center", vertical="center", wrap_text=True)
        left_align = Alignment(horizontal="left", vertical="center")
        right_align = Alignment(horizontal="right", vertical="center")

        thin_border = Border(
            left=Side(style="thin", color="CBD5E1"),
            right=Side(style="thin", color="CBD5E1"),
            top=Side(style="thin", color="CBD5E1"),
            bottom=Side(style="thin", color="CBD5E1")
        )

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = center_align
            cell.border = thin_border
        ws.row_dimensions[1].height = 28

        for row_idx, p_name in enumerate(distinct_purposes, start=2):
            current_price = ''
            if sp:
                existing = VisitPurpose.objects.filter(purpose__iexact=p_name, sponsor=sp, plan=pl).first()
                if not existing and not pl:
                    existing = VisitPurpose.objects.filter(purpose__iexact=p_name, sponsor=sp, plan__isnull=True).first()
                if existing:
                    current_price = existing.price
            if current_price == '':
                gen = VisitPurpose.objects.filter(purpose__iexact=p_name, sponsor__isnull=True, plan__isnull=True).first()
                current_price = gen.price if gen else 2000

            ws.append([p_name, sponsor_str, plan_str, current_price])

            c1 = ws.cell(row=row_idx, column=1)
            c2 = ws.cell(row=row_idx, column=2)
            c3 = ws.cell(row=row_idx, column=3)
            c4 = ws.cell(row=row_idx, column=4)

            c1.alignment = left_align
            c2.alignment = left_align
            c3.alignment = left_align
            c4.alignment = right_align

            c1.font = Font(name="Calibri", size=11, bold=True, color="1E293B")
            c2.font = Font(name="Calibri", size=11, color="334155")
            c3.font = Font(name="Calibri", size=11, color="334155")
            c4.font = Font(name="Calibri", size=11, bold=True, color="059669")

            c4.number_format = '#,##0'

            for c in (c1, c2, c3, c4):
                c.border = thin_border
            ws.row_dimensions[row_idx].height = 22

        ws.column_dimensions['A'].width = 34
        ws.column_dimensions['B'].width = 30
        ws.column_dimensions['C'].width = 24
        ws.column_dimensions['D'].width = 18

        # Sheet 2: Reference Guide
        ws_guide = wb.create_sheet(title="Sponsors & Plans Guide")
        ws_guide.views.sheetView[0].showGridLines = True
        ws_guide.append(["HOW TO USE THIS BULK TARIFF TEMPLATE"])
        ws_guide.cell(row=1, column=1).font = Font(name="Calibri", size=13, bold=True, color="1E3A8A")
        ws_guide.append([])
        ws_guide.append(["1. 'Purpose Name' contains all current visit purposes from the clinic database."])
        ws_guide.append(["2. 'Sponsor' is pre-filled if selected, or you can enter the HMO name / code (e.g. AIICO MULTISHIELD, AXA MANSARD)."])
        ws_guide.append(["3. 'Coverage Plan' can be left blank for all plans, or enter specific plan (e.g. SILVER, BRONZE, GOLD)."])
        ws_guide.append(["4. 'Price (₦)' enter the consultation rate in numbers only. Then save and upload via 'Bulk Upload Tariffs'."])
        ws_guide.append([])
        ws_guide.append(["List of Hospital Sponsors & Active Plans:"])
        ws_guide.cell(row=7, column=1).font = Font(name="Calibri", size=11, bold=True, color="1E3A8A")

        ws_guide.append(["Sponsor Name", "Billing Code", "Available Coverage Plans"])
        for c_idx in range(1, 4):
            c_hdr = ws_guide.cell(row=8, column=c_idx)
            c_hdr.fill = PatternFill(start_color="F1F5F9", end_color="F1F5F9", fill_type="solid")
            c_hdr.font = Font(name="Calibri", size=10, bold=True, color="1E293B")
            c_hdr.border = thin_border

        for r_num, s_item in enumerate(Sponsor.objects.all().order_by('name')[:50], start=9):
            p_list = list(s_item.plans.values_list('plan', flat=True))
            ws_guide.append([s_item.name, s_item.code or '', ", ".join(p_list) if p_list else "All Plans"])
            for c_idx in range(1, 4):
                ws_guide.cell(row=r_num, column=c_idx).border = thin_border
                ws_guide.cell(row=r_num, column=c_idx).font = Font(name="Calibri", size=10, color="334155")

        ws_guide.column_dimensions['A'].width = 34
        ws_guide.column_dimensions['B'].width = 16
        ws_guide.column_dimensions['C'].width = 40

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        safe_name = (sp.code or sp.name).replace(' ', '_').replace('/', '_') if sp else 'General_Tariffs'
        filename = f"visit_purposes_template_{safe_name}.xlsx"

        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @action(detail=False, methods=['get'], url_path='download-master-template')
    def download_master_template(self, request):
        """
        Download Excel (.xlsx) template for bulk importing master visit purposes into database catalog.
        Columns: Purpose of Appointment / Clinic Service, Consultation Fee (₦)
        Pre-populated with existing database master purposes or standard clinical presets.
        """
        from django.http import HttpResponse
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Master Visit Purposes"
        ws.views.sheetView[0].showGridLines = True

        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1'),
        )

        # Title block
        ws.merge_cells('A1:B1')
        title_cell = ws.cell(row=1, column=1)
        title_cell.value = "HOSPITAL MASTER VISIT PURPOSES CATALOG TEMPLATE"
        title_cell.font = Font(name="Calibri", size=13, bold=True, color="065F46")
        title_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[1].height = 28

        ws.merge_cells('A2:B2')
        sub_cell = ws.cell(row=2, column=1)
        sub_cell.value = "Enter clinic consultation purpose names and default baseline fees (Cash / Private). All rows will be saved directly into the database catalog."
        sub_cell.font = Font(name="Calibri", size=9.5, italic=True, color="047857")
        sub_cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.row_dimensions[2].height = 20

        # Header Row
        headers = ["Purpose of Appointment / Clinic Service", "Consultation Fee (₦)"]
        for col_idx, h_text in enumerate(headers, start=1):
            cell = ws.cell(row=4, column=col_idx)
            cell.value = h_text
            cell.font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
            cell.fill = PatternFill(start_color="059669", end_color="059669", fill_type="solid")
            cell.alignment = Alignment(horizontal="center" if col_idx == 2 else "left", vertical="center")
            cell.border = thin_border
        ws.row_dimensions[4].height = 26

        sample_purposes = [
            ("General Consultation", 2000),
            ("Antenatal Clinic (ANC)", 3000),
            ("Immunization", 1500),
            ("Pediatric Review", 2500),
            ("Cardiology First visit", 6000),
            ("Cardiology follow up visit", 5000),
            ("Dental Examination", 4000),
            ("Eye Clinic / Ophthalmology", 4000),
            ("Specialist Consultation", 5000),
            ("Surgical Review", 5000),
            ("Post-Discharge Follow-up", 2000),
            ("Routine Health Checkup", 3500),
        ]

        existing_db = list(VisitPurpose.objects.filter(sponsor__isnull=True).order_by('purpose').values_list('purpose', 'price'))
        data_to_write = existing_db if existing_db else sample_purposes

        for row_idx, (p_name, p_price) in enumerate(data_to_write, start=5):
            c1 = ws.cell(row=row_idx, column=1, value=p_name)
            c1.font = Font(name="Calibri", size=10.5, color="1E293B")
            c1.border = thin_border

            c2 = ws.cell(row=row_idx, column=2, value=p_price)
            c2.font = Font(name="Calibri", size=10.5, color="1E293B")
            c2.alignment = Alignment(horizontal="right", vertical="center")
            c2.border = thin_border
            c2.number_format = "#,##0"
            ws.row_dimensions[row_idx].height = 20

        ws.column_dimensions['A'].width = 46
        ws.column_dimensions['B'].width = 24

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="master_visit_purposes_template.xlsx"'
        return response

    @action(detail=False, methods=['get'], url_path='master-purposes')
    def master_purposes(self, request):
        """
        Returns all distinct master visit purposes registered in the hospital database,
        along with their default base out-of-pocket price, and summary of configured sponsor tariffs.
        """
        all_vps = VisitPurpose.objects.all().select_related('sponsor', 'plan')
        purposes_map = {}
        for vp in all_vps:
            name = (vp.purpose or '').strip()
            if not name:
                continue
            key = name.lower()
            if key not in purposes_map:
                purposes_map[key] = {
                    'purpose': name,
                    'base_id': None,
                    'base_price': 0,
                    'specialist_id': 0,
                    'tariffs_count': 0,
                    'sponsors': [],
                    'tariffs': [],
                    'created_date': vp.created_date,
                }
            item = purposes_map[key]
            if vp.sponsor is None:
                item['base_id'] = vp.id
                item['base_price'] = vp.price
                item['specialist_id'] = vp.specialist_id
                item['created_date'] = vp.created_date
            else:
                item['tariffs_count'] += 1
                s_name = vp.sponsor.name
                if s_name not in item['sponsors']:
                    item['sponsors'].append(s_name)
                item['tariffs'].append({
                    'id': vp.id,
                    'sponsor_id': vp.sponsor.id,
                    'sponsor_name': vp.sponsor.name,
                    'plan_id': vp.plan.id if vp.plan else None,
                    'plan_name': vp.plan.plan if vp.plan else 'All Plans',
                    'price': vp.price,
                })

        result = sorted(purposes_map.values(), key=lambda x: x['purpose'].lower())
        return Response({
            'count': len(result),
            'results': result
        }, status=status.HTTP_200_OK)

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
        if not user and request.data.get('doctor_id'):
            try:
                user = User.objects.filter(id=request.data.get('doctor_id'), is_active=True).first()
            except Exception:
                pass
        if not user and request.data.get('doctor_username'):
            user = User.objects.filter(username__iexact=str(request.data.get('doctor_username')).strip(), is_active=True).first()
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
                dispense_unit = p.get('dispense_unit')
                if not dispense_unit or dispense_unit in ['Pieces', 'pieces']:
                    if dosage_form in ['Syrup', 'Suspension']:
                        dispense_unit = 'Bottles'
                    elif dosage_form == 'Injection' or 'inj' in drug_name.lower():
                        dispense_unit = 'Ampoules' if ('amp' in dose_unit.lower() or 'amp' in drug_name.lower()) else 'Vials'
                    elif dosage_form == 'Inhaler':
                        dispense_unit = 'Inhalers'
                    elif dosage_form == 'Ointment':
                        dispense_unit = 'Tubes'
                    elif dosage_form == 'Suppository':
                        dispense_unit = 'Suppositories'
                    elif dosage_form == 'Sachet':
                        dispense_unit = 'Sachets'
                    elif dosage_form == 'Capsule':
                        dispense_unit = 'Capsules'
                    elif dosage_form == 'Caplet':
                        dispense_unit = 'Caplets'
                    else:
                        dispense_unit = 'Tablets'

                dispense_detail = p.get('dispense_detail') or ''
                if (dosage_form == 'Injection' or 'inj' in drug_name.lower()) and 'tablets' in dispense_detail.lower():
                    dispense_detail = f"{disp_qty} {dispense_unit}"
                elif dispense_detail:
                    dispense_detail = dispense_detail.replace('(Pieces)', '').replace('(pieces)', '').strip()
                comment = p.get('comment') or p.get('notes') or ''
                start_date = p.get('start_date') or timezone.now().date()
                instruction = p.get('instruction') or f"{dose_qty} {dose_unit} {frequency} for {duration} {duration_unit}"

                if p.get('is_pay_from_purse') or p.get('payment_mode') == 'pay_from_purse':
                    if not comment:
                        comment = '[Pay from your purse]'
                    elif '[Pay from your purse]' not in comment:
                        comment = f"[Pay from your purse] {comment}".strip()

                # Avoid duplicate insertion if exact prescription already exists today
                existing_rx = WrittenPrescriptions.objects.filter(
                    patient=patient, item=drug_name[:200],
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
                    p_sponsor = getattr(patient, 'sponsor', None)
                    p_plan = getattr(patient, 'plan', None)
                    t = None
                    if p_sponsor and p_plan:
                        t = RadioLabInventory.objects.filter(item__iexact=test_name, type='L', sponsor=p_sponsor, plan=p_plan).first()
                    if not t and p_plan:
                        t = RadioLabInventory.objects.filter(item__iexact=test_name, type='L', plan=p_plan).first()
                    if not t and p_sponsor:
                        t = RadioLabInventory.objects.filter(item__iexact=test_name, type='L', sponsor=p_sponsor).first()
                    if not t:
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
                billing_waiting_status=1, created_date__date=target_date
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

            lab_pids = RadiologyLab.objects.filter(billing_waiting_status=1).values_list('patient_id', flat=True).distinct()
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

            # Find appointments for target_date or latest appointments (latest/current schedule first)
            if target_date:
                appts = list(PatientAppointment.objects.filter(patient=pat, arrival_date=target_date, completed__in=[0, 1]).order_by('-arrival_date', '-arrival_time', '-id'))
                if not appts:
                    appts = list(PatientAppointment.objects.filter(patient=pat, arrival_date=target_date).order_by('-arrival_date', '-arrival_time', '-id'))
                latest_dw = DoctorWaitingList.objects.filter(patient=pat, created_date__date=target_date).order_by('-created_date').first()
                latest_nw = NurseWaitingList.objects.filter(patient=pat, created_date__date=target_date).order_by('-created_date').first()
                latest_enc = PatientEncounter.objects.filter(patient=pat, created_at__date=target_date).order_by('-created_at').first()
            else:
                appts = list(PatientAppointment.objects.filter(patient=pat, completed__in=[0, 1]).order_by('-arrival_date', '-arrival_time', '-id')[:5])
                if not appts:
                    appts = list(PatientAppointment.objects.filter(patient=pat).order_by('-arrival_date', '-arrival_time', '-id')[:5])
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
            raw_time_str = appt.arrival_time.strftime('%H:%M:%S') if (appt and appt.arrival_time) else (latest_dw.created_date.strftime('%H:%M:%S') if (latest_dw and latest_dw.created_date) else '09:00:00')
            raw_date_str = visit_date_raw.strftime('%Y-%m-%d')
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

                    # Determine consultation rate for this specific purpose and patient sponsor/plan
                    pat_sponsor = getattr(pat, 'sponsor', None)
                    pat_plan = getattr(pat, 'plan', None)
                    vp = None

                    if pat_sponsor and pat_plan:
                        vp = VisitPurpose.objects.filter(purpose__iexact=p_name, sponsor=pat_sponsor, plan=pat_plan).first()
                    if not vp and pat_sponsor:
                        vp = VisitPurpose.objects.filter(purpose__iexact=p_name, sponsor=pat_sponsor, plan__isnull=True).first()
                    if not vp and pat_plan:
                        vp = VisitPurpose.objects.filter(purpose__iexact=p_name, plan=pat_plan).first()
                    if not vp:
                        vp = VisitPurpose.objects.filter(purpose__iexact=p_name, sponsor__isnull=True, plan__isnull=True).first()

                    if not vp:
                        p_first = p_name.split()[0]
                        if pat_sponsor and pat_plan:
                            vp = VisitPurpose.objects.filter(purpose__icontains=p_first, sponsor=pat_sponsor, plan=pat_plan).first()
                        if not vp and pat_sponsor:
                            vp = VisitPurpose.objects.filter(purpose__icontains=p_first, sponsor=pat_sponsor, plan__isnull=True).first()
                        if not vp:
                            vp = VisitPurpose.objects.filter(purpose__icontains=p_first, sponsor__isnull=True, plan__isnull=True).first()

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

            enc_consultation_text = (latest_enc.comments_on_diagnosis or '') if latest_enc else ''
            enc_consult_lower = enc_consultation_text.lower()

            already_invoiced_rx_ids = set(
                Invoice.objects.filter(
                    patient=pat,
                    original_source_model='WrittenPrescriptions'
                ).exclude(original_source_id__isnull=True).values_list('original_source_id', flat=True)
            )

            for rx in rx_items:
                if rx.id in already_invoiced_rx_ids or rx.status == 'billed':
                    continue
                t = PharmacyTariff.objects.filter(product_name__icontains=rx.item).first()
                rate = float(t.rate) if (t and t.rate) else 0.0
                qty = rx.dispense_quantity or rx.quantity or 1
                uom = rx.dispense_unit
                if not uom or uom in ['Pieces', 'pieces', 'Each']:
                    if rx.dosage_form in ['Syrup', 'Suspension']:
                        uom = 'Bottles'
                    elif rx.dosage_form == 'Injection' or 'inj' in (rx.item or '').lower():
                        uom = 'Ampoules' if ('amp' in (rx.dose_unit or '').lower() or 'amp' in (rx.item or '').lower()) else 'Vials'
                    elif rx.dosage_form == 'Capsule':
                        uom = 'Capsules'
                    elif rx.dosage_form == 'Tablet':
                        uom = 'Tablets'
                    else:
                        uom = rx.dispense_unit or 'Each'

                if rx.dispense_detail:
                    clean_disp = rx.dispense_detail.replace('(Pieces)', '').replace('(pieces)', '').strip()
                    if (rx.dosage_form == 'Injection' or 'inj' in (rx.item or '').lower()) and 'tablets' in clean_disp.lower():
                        clean_disp = f"{qty} {uom}"
                    disp_desc = f" ({clean_disp})" if clean_disp else ''
                else:
                    disp_desc = ''

                rx_cmt = (rx.comment or '').lower()
                rx_inst = (rx.instruction or '').lower()
                rx_name = (rx.item or '').lower()

                is_purse = (
                    'pay from your purse' in rx_cmt or
                    'pay from purse' in rx_cmt or
                    'out-of-pocket' in rx_cmt or
                    'out of pocket' in rx_cmt or
                    'non-tariff' in rx_cmt or
                    'pay from your purse' in rx_inst or
                    'pay from purse' in rx_inst or
                    'out-of-pocket' in rx_inst or
                    'non-tariff' in rx_inst or
                    'pay from your purse' in rx_name or
                    'pay from purse' in rx_name
                )

                if not is_purse and enc_consult_lower and rx.item:
                    rx_keyword = rx.item.split()[0].lower()
                    if rx_keyword in enc_consult_lower:
                        for line in enc_consultation_text.splitlines():
                            if rx_keyword in line.lower():
                                l_low = line.lower()
                                if any(k in l_low for k in ['pay from your purse', 'pay from purse', 'out-of-pocket', 'out of pocket', 'non-tariff', 'non tariff']):
                                    is_purse = True
                                    break

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
                    'is_pay_from_purse': is_purse,
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
            already_invoiced_rl_ids = set(
                Invoice.objects.filter(
                    patient=pat,
                    original_source_model='RadiologyLab'
                ).exclude(original_source_id__isnull=True).values_list('original_source_id', flat=True)
            )

            if target_date:
                rad_lab_items = RadiologyLab.objects.filter(patient=pat, created_date__date=target_date).order_by('created_date')
            else:
                rad_lab_items = RadiologyLab.objects.filter(patient=pat).order_by('created_date')

            for rl in rad_lab_items:
                # Skip if already billed / invoiced or already cleared from cashier
                if rl.id in already_invoiced_rl_ids or rl.billing_waiting_status == 0:
                    continue
                if Invoice.objects.filter(patient=pat, created_date__date=rl.created_date.date(), product__icontains=rl.item[:30]).exists():
                    continue

                rate = float(rl.rate or 0)
                is_lab = (rl.item_type == 'L')
                label_prefix = "Lab: " if is_lab else "Scan: "
                uom = "Tests" if is_lab else "Scans"

                rl_cmt = (rl.comment or '').lower()
                rl_name = (rl.item or '').lower()

                is_purse = (
                    'pay from your purse' in rl_cmt or
                    'pay from purse' in rl_cmt or
                    'out-of-pocket' in rl_cmt or
                    'out of pocket' in rl_cmt or
                    'non-tariff' in rl_cmt or
                    'pay from your purse' in rl_name or
                    'pay from purse' in rl_name
                )

                if not is_purse and enc_consult_lower and rl.item:
                    rl_keyword = rl.item.split()[0].lower()
                    if rl_keyword in enc_consult_lower:
                        for line in enc_consultation_text.splitlines():
                            if rl_keyword in line.lower():
                                l_low = line.lower()
                                if any(k in l_low for k in ['pay from your purse', 'pay from purse', 'out-of-pocket', 'out of pocket', 'non-tariff', 'non tariff']):
                                    is_purse = True
                                    break

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
                    'is_pay_from_purse': is_purse,
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

            already_invoiced_os_ids = set(
                Invoice.objects.filter(
                    patient=pat,
                    original_source_model='OtherService'
                ).exclude(original_source_id__isnull=True).values_list('original_source_id', flat=True)
            )

            for os in other_services:
                if os.id in already_invoiced_os_ids or os.completed == 1:
                    continue
                rate = float(os.price or 0)
                os_cmt = (os.comment or '').lower()
                os_purpose = (os.purpose or '').lower()

                is_purse = (
                    'pay from your purse' in os_cmt or
                    'pay from purse' in os_cmt or
                    'out-of-pocket' in os_cmt or
                    'out of pocket' in os_cmt or
                    'non-tariff' in os_cmt or
                    'pay from your purse' in os_purpose or
                    'pay from purse' in os_purpose
                )

                if not is_purse and enc_consult_lower and os.purpose:
                    os_keyword = os.purpose.split()[0].lower()
                    if os_keyword in enc_consult_lower:
                        for line in enc_consultation_text.splitlines():
                            if os_keyword in line.lower():
                                l_low = line.lower()
                                if any(k in l_low for k in ['pay from your purse', 'pay from purse', 'out-of-pocket', 'out of pocket', 'non-tariff', 'non tariff']):
                                    is_purse = True
                                    break

                os_payment_option = 'Cash' if is_purse else default_payment_option
                purse_tag = ' [Pay from your purse]' if is_purse else ''

                items.append({
                    'id': f"os_{os.id}",
                    'service_item': f"Service: {os.purpose}{purse_tag}",
                    'uom': 'Each',
                    'quantity': 1,
                    'rate': rate,
                    'discount': 0,
                    'total': rate,
                    'payment_option': os_payment_option,
                    'is_pay_from_purse': is_purse,
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
                'appointment_id': getattr(appt, 'id', None),
                'session_number': getattr(appt, 'id', None) or f"{pat.id}{today.strftime('%d%m')}",
                'visit_date': visit_date_str,
                'visit_time': visit_time_str,
                'raw_date': raw_date_str,
                'raw_time': raw_time_str,
                'arrival_date': raw_date_str,
                'arrival_time': raw_time_str,
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

        # Ensure current schedule is always at the top (latest arrival_date, latest arrival_time, newest appointment/patient ID)
        def get_schedule_sort_key(item):
            d = str(item.get('raw_date') or item.get('arrival_date') or '')
            t = str(item.get('raw_time') or item.get('arrival_time') or '')
            appt_id = int(item.get('appointment_id') or 0)
            pat_id = int(item.get('patient_id') or 0)
            return (d, t, appt_id, pat_id)

        results.sort(key=get_schedule_sort_key, reverse=True)

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

        # Generate / retrieve persistent document numbers for today:
        # 1. Claim Number (for HMO Claim items)
        existing_claim_today = Invoice.objects.filter(
            patient=patient,
            created_date__date=today,
            invoice_number__startswith='CLM-'
        ).exclude(invoice_number__isnull=True).exclude(invoice_number='').order_by('created_date').first()
        claim_number = existing_claim_today.invoice_number if existing_claim_today else f"CLM-{uuid.uuid4().hex[:8].upper()}"

        # 2. Invoice Number (for Patient Out-of-pocket / Cash items)
        existing_inv_today = Invoice.objects.filter(
            patient=patient,
            created_date__date=today,
            invoice_number__startswith='INV-'
        ).exclude(invoice_number__isnull=True).exclude(invoice_number='').order_by('created_date').first()
        invoice_number = existing_inv_today.invoice_number if existing_inv_today else f"INV-{uuid.uuid4().hex[:8].upper()}"

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

                # Determine target document number:
                # - For HMO patients: items marked 'Claim' go to HMO Claim (CLM-...)
                #   items marked 'Cash', 'Pay from purse', 'Transfer', 'POS', etc. go to Patient Invoice (INV-...)
                # - For Private patients: all items go to Patient Invoice (INV-...)
                if is_hmo and str(pay_option).strip().lower() == 'claim':
                    target_doc_number = claim_number
                else:
                    target_doc_number = invoice_number

                # Prevent recording duplicate invoice items if user clicks create bill multiple times
                is_duplicate = False
                if orig_model and orig_id:
                    is_duplicate = Invoice.objects.filter(
                        patient=patient,
                        invoice_number=target_doc_number,
                        original_source_model=orig_model[:50],
                        original_source_id=int(orig_id)
                    ).exists()
                else:
                    is_duplicate = Invoice.objects.filter(
                        patient=patient,
                        invoice_number=target_doc_number,
                        product=label
                    ).exists()

                if is_duplicate:
                    continue

                total_amount += item_total

                invoices_to_create.append(Invoice(
                    patient=patient,
                    invoice_number=target_doc_number,
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
                    RadiologyLab.objects.filter(id=orig_id).update(billing_waiting_status=0, completed=0)
                elif orig_model == 'OtherService' and orig_id:
                    OtherService.objects.filter(id=orig_id).update(completed=1)
                elif orig_model == 'NurseWaitingList' and orig_id:
                    NurseWaitingList.objects.filter(id=orig_id).update(completed=1)
                elif orig_model == 'GetRegistrationFee':
                    GetRegistrationFee.objects.filter(patient=patient).update(completed=1)
                elif orig_model in ['PatientAppointment', 'Appointment'] and orig_id:
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

        # Update or create TransactionUpdate safely outside the atomic transaction block
        if invoices_to_create:
            try:
                tu = TransactionUpdate.objects.filter(patient=patient, completed=0).order_by('-id').first()
                if not tu:
                    tu = TransactionUpdate(patient=patient, completed=0)

                created_doc_numbers = list(dict.fromkeys(inv.invoice_number for inv in invoices_to_create))
                primary_doc = created_doc_numbers[0] if created_doc_numbers else (claim_number if is_hmo else invoice_number)
                tu.invoice_ids = str(primary_doc)[:20]
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

        # Categorize created invoices
        claim_invoices = [inv for inv in invoices_to_create if inv.invoice_number.startswith('CLM-')]
        patient_invoices = [inv for inv in invoices_to_create if inv.invoice_number.startswith('INV-')]

        claim_total = sum(float(inv.price) for inv in claim_invoices)
        inv_total = sum(float(inv.price) for inv in patient_invoices)
        has_split = (len(claim_invoices) > 0 and len(patient_invoices) > 0)

        primary_number = claim_number if (is_hmo and claim_invoices) else invoice_number
        bill_num_clean = primary_number.replace('INV-', '').replace('CLM-', '')
        if not bill_num_clean.isdigit():
            bill_num_clean = f"{abs(hash(primary_number)) % 9000000 + 1000000}"

        now_dt = timezone.localtime()
        formatted_dt = now_dt.strftime('%d %B %Y %I:%M%p').lower()

        if has_split:
            msg = f"Encounter Bill Created: HMO Claim #{claim_number} ({len(claim_invoices)} covered items: ₦{claim_total:,.2f}) and Patient Invoice #{invoice_number} ({len(patient_invoices)} pay-from-purse items: ₦{inv_total:,.2f}) successfully generated!"
        elif is_hmo and claim_invoices:
            msg = f"HMO Claim #{claim_number} ({len(claim_invoices)} covered items: ₦{claim_total:,.2f}) successfully generated."
        else:
            msg = f"Patient Invoice #{invoice_number} ({len(patient_invoices)} items: ₦{inv_total:,.2f}) successfully generated."

        staff_name = ''
        if user:
            staff_name = (getattr(user, 'fullname', None) or '').strip() or user.get_full_name() or user.username
        if not staff_name:
            staff_name = (request.data.get('staff_name') or '').strip()
        if not staff_name and existing_claim_today and existing_claim_today.staff:
            staff_name = (getattr(existing_claim_today.staff, 'fullname', None) or '').strip() or existing_claim_today.staff.get_full_name() or existing_claim_today.staff.username
        if not staff_name:
            staff_name = 'Cashier / Billing Desk'

        # Gather previous patient balances
        prev_balance = 0.0
        try:
            prev_tu = TransactionUpdate.objects.filter(patient=patient).exclude(invoice_ids__icontains=primary_number).order_by('-id').first()
            if prev_tu and prev_tu.invoice_raised:
                prev_balance = float(prev_tu.invoice_raised)
        except Exception:
            pass

        return Response({
            'status': 'success',
            'has_split': has_split,
            'bill_type': 'split' if has_split else ('claim' if (is_hmo and claim_invoices) else 'invoice'),
            'claim_number': claim_number if claim_invoices else None,
            'claim_items_count': len(claim_invoices),
            'claim_total': claim_total,
            'claim_items': [
                {
                    'service_item': inv.product,
                    'quantity': inv.qty,
                    'rate': inv.price / (inv.qty or 1),
                    'total': inv.price,
                    'payment_option': inv.payment_option,
                } for inv in claim_invoices
            ],
            'invoice_number': invoice_number if patient_invoices else (claim_number if is_hmo else invoice_number),
            'inv_items_count': len(patient_invoices),
            'inv_total': inv_total,
            'invoice_items': [
                {
                    'service_item': inv.product,
                    'quantity': inv.qty,
                    'rate': inv.price / (inv.qty or 1),
                    'total': inv.price,
                    'payment_option': inv.payment_option,
                } for inv in patient_invoices
            ],
            'primary_number': primary_number,
            'bill_number': bill_num_clean,
            'receipt_number': receipt_number,
            'is_paid': mark_as_paid,
            'items_count': len(invoices_to_create),
            'total_amount': total_amount,
            'message': msg,
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

    @action(detail=False, methods=['post'], url_path='approve-hmo-claim')
    def approve_hmo_claim(self, request):
        """
        Approves an HMO claim (or batch of claim items under invoice_number),
        marking them as completed=1 so that OPD pharmacy and clinical departments
        can clear and dispense medications or services to the patient.
        """
        from django.db import transaction
        from Billings.models import TransactionUpdate, Invoice

        invoice_numbers = request.data.get('invoice_numbers')
        invoice_number = request.data.get('invoice_number') or request.data.get('claim_number')
        invoice_id = request.data.get('invoice_id')

        if not invoice_numbers and invoice_number:
            invoice_numbers = [invoice_number]

        if not invoice_numbers and not invoice_id:
            return Response({'error': 'claim_number, invoice_number or invoice_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        with transaction.atomic():
            if invoice_numbers:
                invoices = list(Invoice.objects.select_related('patient', 'category').filter(invoice_number__in=invoice_numbers))
            else:
                invoices = list(Invoice.objects.select_related('patient', 'category').filter(id=invoice_id))

            if not invoices:
                return Response({'error': 'HMO Claim not found'}, status=status.HTTP_404_NOT_FOUND)

            patient = invoices[0].patient
            inv_num = invoices[0].invoice_number or f"CLM-{invoices[0].id}"

            # Mark all matching claim invoices as approved (completed=1)
            if invoice_numbers:
                Invoice.objects.filter(invoice_number__in=invoice_numbers).update(completed=1)
            else:
                Invoice.objects.filter(id=invoice_id).update(completed=1)

            if patient:
                try:
                    tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
                    tu.completed = 1
                    tu.updated_date = timezone.now()
                    tu.save()
                except Exception:
                    pass

        return Response({
            'status': 'success',
            'invoice_number': inv_num,
            'claim_number': inv_num,
            'patient_name': f"{patient.surname} {patient.first_name}" if patient else 'Patient',
            'hospital_number': patient.hospital_number if patient else '',
            'sponsor': patient.sponsor.name if (patient and patient.sponsor) else 'HMO / Sponsor',
            'items_approved': len(invoices),
            'message': f"HMO Claim #{inv_num} ({len(invoices)} items) successfully approved! Prescriptions and services are now cleared for dispensing."
        }, status=status.HTTP_200_OK)


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
    pagination_class = None
    permission_classes = [permissions.AllowAny]
    filter_backends = [filters.SearchFilter]
    search_fields = ['item', 'patient__surname', 'patient__first_name', 'patient__hospital_number']

    def get_queryset(self):
        qs = super().get_queryset()
        completed = self.request.query_params.get('completed', None)
        if completed is not None and completed != '':
            qs = qs.filter(completed=completed)

        item_type = self.request.query_params.get('item_type', '').strip()
        if item_type:
            if item_type.lower() in ['lab', 'la', 'l']:
                qs = qs.filter(item_type__in=['L', 'LA', 'Lab'])
            elif item_type.lower() in ['radio', 'ra', 'r']:
                qs = qs.filter(item_type__in=['R', 'RA', 'Radio'])
            else:
                qs = qs.filter(item_type__iexact=item_type)

        date_param = self.request.query_params.get('date', '').strip() or None
        start_date = self.request.query_params.get('start_date', '').strip() or None
        end_date = self.request.query_params.get('end_date', '').strip() or None

        if date_param:
            qs = qs.filter(created_date__date=date_param)
        else:
            if start_date:
                qs = qs.filter(created_date__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_date__date__lte=end_date)
        return qs

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        plan = serializer.validated_data.get('plan') or (patient.plan if patient else None)
        serializer.save(staff=user, category=category, plan=plan)

    @action(detail=True, methods=['post'], url_path='upload-result')
    def upload_result(self, request, pk=None):
        """
        Upload lab result or radiology scan result linked directly to this order ID.
        Marks order as completed and updates waiting status.
        """
        order = self.get_object()
        user = request.user if request.user.is_authenticated else None
        results_text = request.data.get('results', '')
        file_obj = request.FILES.get('file') or request.FILES.get('scan') or request.FILES.get('file_upload')

        is_radio = order.item_type in ['R', 'RA', 'Radio']

        if is_radio:
            result_instance = ScanResult.objects.create(
                order=order,
                investigation=order.item,
                results=results_text,
                scan=file_obj,
                patient=order.patient,
                staff=user,
                waiting_status=1
            )
            serializer = ScanResultSerializer(result_instance, context={'request': request})
        else:
            result_instance = LabResult.objects.create(
                order=order,
                investigation=order.item,
                results=results_text,
                file_upload=file_obj,
                patient=order.patient,
                staff=user,
                waiting_status=1
            )
            serializer = LabResultSerializer(result_instance, context={'request': request})

        order.completed = 1
        order.radiolab_waiting_status = 1
        order.save(update_fields=['completed', 'radiolab_waiting_status'])

        return Response({
            'message': 'Result recorded successfully',
            'order_id': order.id,
            'result': serializer.data
        }, status=status.HTTP_201_CREATED)


class LabResultViewSet(viewsets.ModelViewSet):
    queryset = LabResult.objects.all().select_related('patient', 'staff', 'order').order_by('-created_date')
    serializer_class = LabResultSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        res = serializer.save(staff=user, waiting_status=1)
        if res.order:
            res.order.completed = 1
            res.order.radiolab_waiting_status = 1
            res.order.save(update_fields=['completed', 'radiolab_waiting_status'])


class ScanResultViewSet(viewsets.ModelViewSet):
    queryset = ScanResult.objects.all().select_related('patient', 'staff', 'order').order_by('-created_date')
    serializer_class = ScanResultSerializer
    permission_classes = [permissions.AllowAny]

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        res = serializer.save(staff=user, waiting_status=1)
        if res.order:
            res.order.completed = 1
            res.order.radiolab_waiting_status = 1
            res.order.save(update_fields=['completed', 'radiolab_waiting_status'])



# Inventory ViewSets
from inventory.models import Product as InventoryProduct, Transaction as InventoryTransaction, ProductRequests as InventoryProductRequests
from .serializers import InventoryProductSerializer, InventoryTransactionSerializer, InventoryProductRequestSerializer

class InventoryProductViewSet(viewsets.ModelViewSet):
    queryset = InventoryProduct.objects.all().order_by('-created_date')
    serializer_class = InventoryProductSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['product_name', 'product_id', 'description']

    def perform_create(self, serializer):
        staff = self.request.user if self.request.user.is_authenticated else None
        product_id = serializer.validated_data.get('product_id')
        if not product_id or not str(product_id).strip():
            from inventory.utils import get_next_isl_sku
            serializer.save(staff=staff, product_id=get_next_isl_sku())
        else:
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

        # Date filtering (today, specific date, or date range)
        date_param = self.request.query_params.get('date', '').strip() or None
        start_date = self.request.query_params.get('start_date', '').strip() or None
        end_date = self.request.query_params.get('end_date', '').strip() or None

        if date_param:
            qs = qs.filter(created_date__date=date_param)
        else:
            if start_date:
                qs = qs.filter(created_date__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_date__date__lte=end_date)

        status_param = self.request.query_params.get('status', None)
        if status_param and status_param.lower() != 'all':
            qs = qs.filter(status__iexact=status_param)

        # Filter by payment clearance: 'cleared', 'paid', 'unpaid', 'pending'
        payment_param = self.request.query_params.get('payment', None)
        if payment_param:
            p_val = payment_param.lower()
            if p_val in ['cleared', 'paid', 'billed']:
                qs = qs.filter(status__in=['billed', 'dispensed'])
            elif p_val in ['unpaid', 'pending']:
                qs = qs.filter(status='pending')

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
            dispense_unit = p.get('dispense_unit')
            if not dispense_unit or dispense_unit in ['Pieces', 'pieces']:
                if dosage_form in ['Syrup', 'Suspension']:
                    dispense_unit = 'Bottles'
                elif dosage_form == 'Injection' or 'inj' in item_name.lower():
                    dispense_unit = 'Ampoules' if ('amp' in dose_unit.lower() or 'amp' in item_name.lower()) else 'Vials'
                elif dosage_form == 'Inhaler':
                    dispense_unit = 'Inhalers'
                elif dosage_form == 'Ointment':
                    dispense_unit = 'Tubes'
                elif dosage_form == 'Suppository':
                    dispense_unit = 'Suppositories'
                elif dosage_form == 'Sachet':
                    dispense_unit = 'Sachets'
                elif dosage_form == 'Capsule':
                    dispense_unit = 'Capsules'
                elif dosage_form == 'Caplet':
                    dispense_unit = 'Caplets'
                else:
                    dispense_unit = 'Tablets'

            dispense_quantity = int(p.get('dispense_quantity') or p.get('quantity') or 0)
            dispense_detail = p.get('dispense_detail') or ''
            if (dosage_form == 'Injection' or 'inj' in item_name.lower()) and 'tablets' in dispense_detail.lower():
                dispense_detail = f"{dispense_quantity} {dispense_unit}"
            elif dispense_detail:
                dispense_detail = dispense_detail.replace('(Pieces)', '').replace('(pieces)', '').strip()
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
        STRICT REQUIREMENT: Before medication can be dispensed, it MUST be cleared by billing:
        - For Private/Self-Pay: Must be cleared by cashier with payment receipt (Invoice completed=1).
        - For HMO/Insurance: Must be an approved claim (Invoice completed=1).
        - Pay-from-purse items: Require private cashier payment clearance even for HMO patients.
        """
        from Billings.models import Invoice

        prescription = self.get_object()
        if prescription.status == 'dispensed':
            return Response({'detail': 'Medication has already been dispensed.'}, status=status.HTTP_400_BAD_REQUEST)

        patient = prescription.patient
        cat_name = (patient.category.category if patient and patient.category else '').lower()
        spon_name = (patient.sponsor.name if patient and patient.sponsor else '').lower()
        is_pay_from_purse = '[pay from your purse]' in (prescription.comment or '').lower() or '[pay from your purse]' in (prescription.instruction or '').lower()
        is_hmo = (not is_pay_from_purse) and any(k in cat_name or k in spon_name for k in ['hmo', 'nhis', 'insurance', 'retainer'])

        # Check billing clearance in Invoice table
        invoice = Invoice.objects.filter(
            original_source_model='WrittenPrescriptions',
            original_source_id=prescription.id
        ).order_by('-id').first()

        is_cleared = bool(invoice and invoice.completed == 1)

        if not is_cleared:
            if is_hmo:
                if invoice:
                    return Response({
                        'detail': f"Dispense Blocked: HMO Claim #{invoice.invoice_number} for {prescription.item} has not been approved by Billing yet. Approval is required before medication can be dispensed."
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response({
                        'detail': f"Dispense Blocked: {prescription.item} has not been billed under an HMO claim yet. The Billing / HMO desk must process and approve the claim first."
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                if invoice:
                    return Response({
                        'detail': f"Dispense Blocked: Payment for {prescription.item} (Invoice #{invoice.invoice_number}) has NOT been cleared at Cashier / Billing yet. Receipt payment clearance is required before dispensing."
                    }, status=status.HTTP_400_BAD_REQUEST)
                else:
                    return Response({
                        'detail': f"Dispense Blocked: {prescription.item} has not been billed yet. Patient must be billed and clear payment at Cashier before dispensing."
                    }, status=status.HTTP_400_BAD_REQUEST)

        qty_to_deduct = prescription.dispense_quantity or prescription.quantity or 1
        stock_deducted = 0
        remaining_stock = None
        store_name = 'OPD Pharmacy'

        # Resolve active dispensing pharmacy branch
        store_id = request.data.get('store_id') or request.query_params.get('store_id')
        target_store = None
        if store_id:
            try:
                target_store = PharmacyStore.objects.filter(id=int(store_id)).first()
            except (ValueError, TypeError):
                pass
        if not target_store:
            target_store = PharmacyStore.objects.filter(store_type='opd_pharmacy', is_active=True).first() or \
                           PharmacyStore.objects.filter(is_active=True).first()

        if target_store:
            store_name = target_store.name

        # 1. Match Product in Hospital Catalog
        product = Product.objects.filter(product_name__iexact=prescription.item).first()
        if not product and prescription.item:
            first_word = prescription.item.split()[0]
            product = Product.objects.filter(product_name__icontains=first_word).first()

        # 2. Strict Stock Validation: Must have sufficient stock in branch to dispense
        available_stock = 0
        store_stock = None
        if target_store and product:
            store_stock = StoreStock.objects.filter(store=target_store, product=product).first()
            if store_stock:
                available_stock = store_stock.stock

        matching_drug = None
        if available_stock <= 0:
            matching_drug = OpdDrugs.objects.filter(product_name__iexact=prescription.item).first()
            if not matching_drug and prescription.item:
                matching_drug = OpdDrugs.objects.filter(product_name__icontains=prescription.item.split()[0]).first()
            if matching_drug:
                available_stock = max(available_stock, matching_drug.stock)

        if available_stock < qty_to_deduct:
            return Response({
                'detail': f"Dispense Blocked: Insufficient shelf stock for {prescription.item} at {store_name}. Available stock is {available_stock} (needs {qty_to_deduct}). The pharmacy must restock or request a stock requisition before dispensing this medication."
            }, status=status.HTTP_400_BAD_REQUEST)

        # 3. Mark as dispensed once stock is verified
        user = request.user if request.user.is_authenticated else None
        prescription.status = 'dispensed'
        prescription.dispensed_at = timezone.now()
        if user and user.is_authenticated:
            prescription.dispensed_by = user
        prescription.save()

        # 4. Deduct from StoreStock (Branch Shelf Inventory)
        if target_store and product:
            store_stock, _ = StoreStock.objects.get_or_create(store=target_store, product=product, defaults={'stock': 0})
            if store_stock:
                orig_stock = store_stock.stock
                store_stock.stock = max(0, orig_stock - qty_to_deduct)
                store_stock.save(update_fields=['stock', 'updated_date'])
                stock_deducted = qty_to_deduct
                remaining_stock = store_stock.stock

                # Decrement FEFO batches if any exist
                needed = qty_to_deduct
                for batch in store_stock.batches.filter(quantity__gt=0).order_by('expiry_date'):
                    if needed <= 0:
                        break
                    take = min(batch.quantity, needed)
                    batch.quantity -= take
                    batch.save(update_fields=['quantity'])
                    needed -= take

        # 3. Capture in Central Inventory Transaction Ledger
        if product:
            pat_str = f"Patient: {patient.surname} {patient.first_name} (#{patient.hospital_number})" if patient else "Prescription Dispense"
            dest_label = f"{pat_str} via {store_name}"[:30]
            try:
                Transaction.objects.create(
                    product=product,
                    quantity=qty_to_deduct,
                    price=product.price,
                    transaction_type='DISPENSE',
                    destination=dest_label,
                    staff=user
                )
            except Exception as e:
                logger.warning(f"Error logging Transaction: {e}")

        # 4. Fallback / Sync OpdDrugs and OpdDrugsUpdate
        matching_drug = OpdDrugs.objects.filter(product_name__iexact=prescription.item).first()
        if not matching_drug and prescription.item:
            matching_drug = OpdDrugs.objects.filter(product_name__icontains=prescription.item.split()[0]).first()
        if matching_drug:
            matching_drug.stock = max(0, matching_drug.stock - qty_to_deduct)
            matching_drug.save(update_fields=['stock', 'status'])
            if remaining_stock is None:
                remaining_stock = matching_drug.stock
                stock_deducted = qty_to_deduct
            try:
                OpdDrugsUpdate.objects.create(
                    product=matching_drug,
                    quantity=qty_to_deduct,
                    price=matching_drug.price,
                    transaction_type='DISPENSE',
                    destination=f"Patient: {patient.hospital_number}" if patient else "OPD Dispense",
                    staff=user
                )
            except Exception as e:
                logger.warning(f"Error logging OpdDrugsUpdate: {e}")

        # 5. Capture in AdministerDrugs for patient clinical chart & case notes
        try:
            AdministerDrugs.objects.create(
                item=prescription.item,
                quantity=qty_to_deduct,
                rate=product.price if product else (matching_drug.price if matching_drug else 0),
                total=((product.price if product else (matching_drug.price if matching_drug else 0)) * qty_to_deduct),
                patient=patient,
                staff=user
            )
        except Exception as e:
            logger.warning(f"Error recording AdministerDrugs: {e}")

        serializer = self.get_serializer(prescription)
        return Response({
            'success': True,
            'prescription': serializer.data,
            'stock_deducted': stock_deducted,
            'remaining_stock': remaining_stock,
            'store_name': store_name,
            'drug_name': product.product_name if product else (matching_drug.product_name if matching_drug else prescription.item),
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

    @action(detail=False, methods=['get'], url_path='patient-queue')
    def patient_queue(self, request):
        """
        Get prescription queue grouped by patient for today or a filtered date,
        showing their prescription items, payment clearance, and dispensing status.
        Distinguishes between Private payment clearance and HMO claim approval.
        """
        from collections import defaultdict
        from Billings.models import Invoice

        target_date_str = request.query_params.get('date', '').strip() or None
        start_date = request.query_params.get('start_date', '').strip() or None
        end_date = request.query_params.get('end_date', '').strip() or None
        search = request.query_params.get('search', '').strip()
        clearance_filter = request.query_params.get('clearance_filter', '').strip().lower()
        if not clearance_filter and request.query_params.get('cleared_only', '').lower() in ['1', 'true', 'yes']:
            clearance_filter = 'cleared'

        qs = WrittenPrescriptions.objects.select_related('patient', 'patient__category', 'patient__sponsor', 'provider', 'dispensed_by')

        if target_date_str:
            qs = qs.filter(created_date__date=target_date_str)
        elif start_date or end_date:
            if start_date:
                qs = qs.filter(created_date__date__gte=start_date)
            if end_date:
                qs = qs.filter(created_date__date__lte=end_date)
        else:
            # Default to today if no date params given
            qs = qs.filter(created_date__date=timezone.now().date())

        if search:
            qs = qs.filter(
                Q(patient__surname__icontains=search) |
                Q(patient__first_name__icontains=search) |
                Q(patient__hospital_number__icontains=search) |
                Q(item__icontains=search)
            )

        qs = qs.order_by('-created_date')

        # Group prescriptions by patient
        patient_groups = defaultdict(list)
        for rx in qs:
            patient_groups[rx.patient_id].append(rx)

        # Batch lookup for invoice completion
        all_rx_ids = [rx.id for rx in qs]
        cleared_rx_ids = set(
            Invoice.objects.filter(
                original_source_model='WrittenPrescriptions',
                original_source_id__in=all_rx_ids,
                completed=1
            ).values_list('original_source_id', flat=True)
        )
        invoices_map = {
            inv.original_source_id: inv
            for inv in Invoice.objects.filter(
                original_source_model='WrittenPrescriptions',
                original_source_id__in=all_rx_ids
            ).order_by('id')
        }

        # Resolve active dispensing pharmacy branch for real-time shelf stock lookup
        store_id = request.query_params.get('store_id')
        target_store = None
        if store_id:
            try:
                target_store = PharmacyStore.objects.filter(id=int(store_id)).first()
            except (ValueError, TypeError):
                pass
        if not target_store:
            target_store = PharmacyStore.objects.filter(store_type='opd_pharmacy', is_active=True).first() or \
                           PharmacyStore.objects.filter(is_active=True).first()

        store_name = target_store.name if target_store else 'OPD Pharmacy'

        # Pre-fetch StoreStock for target_store to avoid N+1 queries
        all_store_stocks = []
        if target_store:
            all_store_stocks = list(StoreStock.objects.filter(store=target_store).select_related('product'))
        all_opd_drugs = list(OpdDrugs.objects.all())

        def get_pharmacy_stock_for_item(item_name):
            if not item_name:
                return 0
            clean_item = item_name.strip().lower()
            # 1. Exact match on Product.product_name
            for ss in all_store_stocks:
                if ss.product and ss.product.product_name.strip().lower() == clean_item:
                    return ss.stock
            # 2. Token match (e.g. "Ibuprofen" in "Ibuprofen 400mg Tablet")
            first_token = clean_item.split()[0] if clean_item.split() else ''
            if first_token:
                for ss in all_store_stocks:
                    if ss.product:
                        p_clean = ss.product.product_name.strip().lower()
                        if first_token in p_clean or p_clean in clean_item:
                            return ss.stock
            # 3. Fallback to OpdDrugs
            for od in all_opd_drugs:
                if od.product_name and od.product_name.strip().lower() == clean_item:
                    return od.stock
            if first_token:
                for od in all_opd_drugs:
                    if od.product_name:
                        o_clean = od.product_name.strip().lower()
                        if first_token in o_clean or o_clean in clean_item:
                            return od.stock
            return 0

        patient_list = []
        for patient_id, rx_items in patient_groups.items():
            pat = rx_items[0].patient
            if not pat:
                continue

            pat_cat_name = (pat.category.category if pat.category else '').lower()
            pat_spon_name = (pat.sponsor.name if pat.sponsor else '').lower()
            pat_is_hmo = any(k in pat_cat_name or k in pat_spon_name for k in ['hmo', 'nhis', 'insurance', 'retainer'])

            # Serialize items
            serialized_items = []
            has_cleared_item = False
            pending_dispense_count = 0
            dispensed_count = 0
            pending_hmo_approval_count = 0
            pending_cashier_payment_count = 0

            for rx in rx_items:
                is_pay_from_purse = '[pay from your purse]' in (rx.comment or '').lower() or '[pay from your purse]' in (rx.instruction or '').lower()
                rx_is_hmo = (not is_pay_from_purse) and pat_is_hmo
                inv = invoices_map.get(rx.id)

                # Item is cleared ONLY if dispensed or completed=1 in Invoice (billing approved / paid)
                is_cleared = (rx.status == 'dispensed') or (rx.id in cleared_rx_ids)
                if is_cleared:
                    has_cleared_item = True

                if rx.status == 'dispensed':
                    dispensed_count += 1
                    payment_status = 'Dispensed'
                    clearance_status_text = 'Dispensed'
                    clearance_badge_type = 'success'
                else:
                    pending_dispense_count += 1
                    if is_cleared:
                        if rx_is_hmo:
                            payment_status = 'HMO Claim Approved'
                            clearance_status_text = 'HMO Claim Approved'
                            clearance_badge_type = 'emerald'
                        else:
                            payment_status = 'Paid / Cleared'
                            clearance_status_text = 'Payment Cleared by Billing'
                            clearance_badge_type = 'success'
                    else:
                        if rx_is_hmo:
                            pending_hmo_approval_count += 1
                            if inv:
                                payment_status = 'Awaiting HMO Claim Approval'
                                clearance_status_text = 'Awaiting HMO Approval'
                            else:
                                payment_status = 'Awaiting HMO Claim Billing'
                                clearance_status_text = 'Awaiting HMO Billing'
                            clearance_badge_type = 'warning'
                        else:
                            pending_cashier_payment_count += 1
                            if inv:
                                payment_status = 'Pending Cashier Payment'
                                clearance_status_text = 'Pending Cashier Payment'
                            else:
                                payment_status = 'Awaiting Cashier Billing'
                                clearance_status_text = 'Awaiting Cashier Billing'
                            clearance_badge_type = 'danger'

                req_qty = rx.dispense_quantity or rx.quantity or 1
                available_stock = get_pharmacy_stock_for_item(rx.item)
                has_sufficient_stock = (available_stock >= req_qty)

                serialized_items.append({
                    'id': rx.id,
                    'item': rx.item,
                    'instruction': rx.instruction,
                    'quantity': rx.quantity,
                    'dosage_form': rx.dosage_form,
                    'route': rx.route,
                    'strength': rx.strength,
                    'dose_qty': rx.dose_qty,
                    'dose_unit': rx.dose_unit,
                    'frequency': rx.frequency,
                    'duration': rx.duration,
                    'duration_unit': rx.duration_unit,
                    'dispense_unit': rx.dispense_unit,
                    'dispense_quantity': rx.dispense_quantity,
                    'dispense_detail': rx.dispense_detail,
                    'comment': rx.comment,
                    'status': rx.status,
                    'is_hmo': rx_is_hmo,
                    'clearance_type': 'hmo_claim' if rx_is_hmo else 'private_payment',
                    'is_pay_from_purse': is_pay_from_purse,
                    'invoice_number': inv.invoice_number if inv else None,
                    'invoice_completed': inv.completed if inv else None,
                    'is_cleared': is_cleared,
                    'payment_status': payment_status,
                    'clearance_status_text': clearance_status_text,
                    'clearance_badge_type': clearance_badge_type,
                    'pharmacy_stock': available_stock,
                    'has_sufficient_stock': has_sufficient_stock,
                    'pharmacy_store_name': store_name,
                    'pharmacy_store_id': target_store.id if target_store else None,
                    'provider_name': rx.provider.fullname if rx.provider else 'Doctor',
                    'dispensed_at': rx.dispensed_at.isoformat() if rx.dispensed_at else None,
                    'dispensed_by_name': rx.dispensed_by.fullname if rx.dispensed_by else None,
                    'created_date': rx.created_date.isoformat() if rx.created_date else None,
                })

            # Handle clearance filtering
            if clearance_filter in ['cleared', 'cleared_only']:
                if not has_cleared_item:
                    continue
            elif clearance_filter == 'awaiting_payment':
                if pending_cashier_payment_count == 0:
                    continue
            elif clearance_filter == 'awaiting_hmo':
                if pending_hmo_approval_count == 0:
                    continue

            all_cleared = all(item['is_cleared'] for item in serialized_items)
            any_cleared = any(item['is_cleared'] for item in serialized_items)

            # Informative clearance summary label
            if pending_dispense_count == 0 and dispensed_count > 0:
                payment_clearance = 'Completed & Dispensed'
            elif all_cleared:
                payment_clearance = 'HMO Claim Approved' if pat_is_hmo else 'Payment Cleared'
            elif any_cleared:
                payment_clearance = 'Partially Cleared'
            else:
                payment_clearance = 'Awaiting HMO Claim Approval' if pat_is_hmo else 'Awaiting Cashier Payment'

            all_in_stock = all(
                item['has_sufficient_stock']
                for item in serialized_items
                if item['status'] != 'dispensed'
            )

            patient_list.append({
                'patient_id': pat.id,
                'patient_name': f"{pat.surname} {pat.first_name}",
                'hospital_number': pat.hospital_number or '-',
                'phone_number': pat.phone_number or '',
                'gender': pat.gender or '',
                'age': getattr(pat, 'get_age', None) or getattr(pat, 'age', '') or '',
                'category': pat.category.category if pat.category else 'General / Self-Pay',
                'sponsor': pat.sponsor.name if pat.sponsor else None,
                'is_hmo': pat_is_hmo,
                'total_prescriptions': len(serialized_items),
                'pending_dispense_count': pending_dispense_count,
                'dispensed_count': dispensed_count,
                'pending_hmo_approval_count': pending_hmo_approval_count,
                'pending_cashier_payment_count': pending_cashier_payment_count,
                'is_fully_cleared': all_cleared,
                'is_partially_cleared': any_cleared and not all_cleared,
                'all_items_in_stock': all_in_stock,
                'pharmacy_store_name': store_name,
                'pharmacy_store_id': target_store.id if target_store else None,
                'payment_clearance': payment_clearance,
                'prescriptions': serialized_items,
                'latest_prescription_time': rx_items[0].created_date.isoformat() if rx_items else None,
            })

        return Response({
            'total_patients': len(patient_list),
            'date': target_date_str or str(timezone.now().date()),
            'active_store': {
                'id': target_store.id if target_store else None,
                'name': store_name,
            },
            'patients': patient_list
        }, status=status.HTTP_200_OK)


# =========================================================================
# Multi-Location Pharmacy & Store Inventory ViewSets
# =========================================================================

class PharmacyStoreViewSet(viewsets.ModelViewSet):
    """
    Manage physical or logical pharmacies and store locations.
    Allows hospital admin to dynamically create and configure pharmacies/stores.
    """
    queryset = PharmacyStore.objects.all().select_related('in_charge').order_by('-is_central', 'name')
    serializer_class = PharmacyStoreSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        store_type = self.request.query_params.get('store_type', None)
        if store_type:
            qs = qs.filter(store_type=store_type)
        active_only = self.request.query_params.get('active_only', None)
        if active_only in ['1', 'true', 'yes']:
            qs = qs.filter(is_active=True)
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(Q(name__icontains=search) | Q(code__icontains=search))
        return qs

    def list(self, request, *args, **kwargs):
        # Auto-ensure primary Central Medical Store exists if no stores exist or no central store is designated
        try:
            if not PharmacyStore.objects.filter(is_central=True).exists():
                existing = PharmacyStore.objects.filter(name__icontains='central').first()
                if existing:
                    existing.is_central = True
                    existing.store_type = 'central_store'
                    existing.save(update_fields=['is_central', 'store_type'])
                elif not PharmacyStore.objects.exists():
                    PharmacyStore.objects.create(
                        name='Central Medical Store',
                        code='CMS-01',
                        store_type='central_store',
                        location='Main Warehouse (Ground Floor)',
                        description='Primary hospital pharmaceutical receiving and distribution warehouse',
                        is_central=True,
                        is_active=True,
                    )
        except Exception:
            pass
        return super().list(request, *args, **kwargs)

    def perform_create(self, serializer):
        user = self.request.user if self.request.user.is_authenticated else None
        serializer.save()

    @action(detail=True, methods=['get'], url_path='stock')
    def get_store_stock(self, request, pk=None):
        """
        List all inventory stock records held by this specific pharmacy or store.
        """
        store = self.get_object()
        qs = StoreStock.objects.filter(store=store).select_related('product', 'store').prefetch_related('batches')
        search = request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(product__product_name__icontains=search) |
                Q(product__product_id__icontains=search)
            )
        low_stock_only = request.query_params.get('low_stock', None)
        if low_stock_only in ['1', 'true', 'yes']:
            from django.db.models import F
            qs = qs.filter(stock__lte=F('low_stock_threshold'))
        serializer = StoreStockSerializer(qs, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @action(detail=False, methods=['get'], url_path='overview')
    def overview(self, request):
        """
        High level multi-store summary showing all pharmacies, their item counts, and valuation.
        """
        stores = PharmacyStore.objects.filter(is_active=True).prefetch_related('stocks__product')
        result = []
        for s in stores:
            serializer = self.get_serializer(s)
            result.append(serializer.data)
        return Response(result, status=status.HTTP_200_OK)


class StoreStockViewSet(viewsets.ModelViewSet):
    """
    Per-store inventory ledger tracking on-hand stock and low-stock alerts.
    """
    queryset = StoreStock.objects.all().select_related('store', 'product').prefetch_related('batches').order_by('store', 'product__product_name')
    serializer_class = StoreStockSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        store_id = self.request.query_params.get('store', None)
        if store_id:
            try:
                target_store = PharmacyStore.objects.filter(id=store_id).first()
                if target_store and (target_store.is_central or target_store.store_type == 'central_store'):
                    existing_product_ids = set(StoreStock.objects.filter(store=target_store).values_list('product_id', flat=True))
                    missing_products = Product.objects.exclude(id__in=existing_product_ids)
                    if missing_products.exists():
                        new_stocks = [
                            StoreStock(
                                store=target_store,
                                product=p,
                                stock=p.stock or 0,
                                low_stock_threshold=p.low_stock_threshold or 10,
                                expiry_date=p.expiry_date
                            )
                            for p in missing_products
                        ]
                        StoreStock.objects.bulk_create(new_stocks, ignore_conflicts=True)
            except Exception:
                pass
            qs = qs.filter(store_id=store_id)
        product_id = self.request.query_params.get('product', None)
        if product_id:
            qs = qs.filter(product_id=product_id)
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(product__product_name__icontains=search) |
                Q(product__product_id__icontains=search) |
                Q(store__name__icontains=search) |
                Q(batches__batch_number__icontains=search)
            ).distinct()
        low_stock_only = self.request.query_params.get('low_stock', None)
        if low_stock_only in ['1', 'true', 'yes']:
            from django.db.models import F
            qs = qs.filter(stock__lte=F('low_stock_threshold'))
        expiring_soon = self.request.query_params.get('expiring_soon', None)
        if expiring_soon in ['1', 'true', 'yes']:
            from datetime import date, timedelta
            threshold = date.today() + timedelta(days=60)
            qs = qs.filter(expiry_date__isnull=False, expiry_date__lte=threshold)
        return qs

    @action(detail=False, methods=['post'], url_path='adjust')
    def adjust_stock(self, request):
        """
        Manual stock-taking adjustment with mandatory staff security PIN verification.
        Captures who performed the adjustment for audit compliance and records a StockMovement entry.
        """
        pin = request.data.get('pin') or request.data.get('security_pin')
        if not pin or str(pin).strip() == '':
            return Response(
                {'error': 'Staff Security PIN is required to authorize physical stock adjustment.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw_pin = str(pin).strip()
        staff_user = None

        # 1. Verify against current session user
        if request.user and request.user.is_authenticated and hasattr(request.user, 'check_pin') and getattr(request.user, 'has_pin', False) and request.user.check_pin(raw_pin):
            staff_user = request.user
        else:
            # 2. Match against active staff users by PIN
            for u in User.objects.filter(is_active=True):
                if hasattr(u, 'check_pin') and getattr(u, 'has_pin', False) and u.check_pin(raw_pin):
                    staff_user = u
                    break

        if not staff_user:
            return Response(
                {'error': 'Incorrect Security PIN. Authorization denied. Please enter your valid 4-digit staff PIN.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        store_id = request.data.get('store_id')
        product_id = request.data.get('product_id')
        new_stock = request.data.get('new_stock')
        reason = request.data.get('reason', 'Physical count adjustment')

        if store_id is None or product_id is None or new_stock is None:
            return Response({'error': 'store_id, product_id, and new_stock are required'}, status=status.HTTP_400_BAD_REQUEST)

        store = PharmacyStore.objects.filter(id=store_id).first()
        product = Product.objects.filter(id=product_id).first()
        if not store or not product:
            return Response({'error': 'Store or Product not found'}, status=status.HTTP_404_NOT_FOUND)

        store_stock, _ = StoreStock.objects.get_or_create(store=store, product=product, defaults={'stock': 0})
        old_stock = store_stock.stock
        store_stock.stock = max(0, int(new_stock))
        store_stock.save()

        # Update central product stock if adjusting central warehouse
        if store.is_central or getattr(store, 'store_type', '') == 'central_store':
            product.stock = store_stock.stock
            product.staff = staff_user
            product.save(update_fields=['stock', 'staff'])
        else:
            product.staff = staff_user
            product.save(update_fields=['staff'])

        delta = store_stock.stock - old_stock
        editor_display = (
            f"{staff_user.first_name} {staff_user.last_name}".strip()
            or getattr(staff_user, 'full_name', '')
            or staff_user.username
        )
        notes_str = f"Adjusted by {editor_display} (PIN Verified). Reason: {reason} | Variance: {'+' if delta > 0 else ''}{delta} units (from {old_stock} to {store_stock.stock})"

        StockMovement.objects.create(
            store=store,
            product=product,
            movement_type='ADJUSTMENT',
            quantity=delta,
            balance_after=store_stock.stock,
            reference_number=f"ADJ-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            notes=notes_str,
            performed_by=staff_user
        )

        return Response({
            'success': True,
            'message': f"Stock adjusted successfully to {store_stock.stock} units by {editor_display} (PIN Verified).",
            'editor_name': editor_display,
            'store_stock': StoreStockSerializer(store_stock).data,
            'delta': delta,
            'new_stock': store_stock.stock
        }, status=status.HTTP_200_OK)

    def _do_edit_item(self, request, stock_id=None):
        """
        Edit medication details and stock parameters with mandatory staff security PIN verification.
        Captures who performed the edit for audit compliance and records a StockMovement entry.
        """
        from decimal import Decimal
        from django.db.models import Q

        pin = request.data.get('pin') or request.data.get('security_pin')
        if not pin or str(pin).strip() == '':
            return Response(
                {'error': 'Staff Security PIN is required to authorize editing this medication.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        raw_pin = str(pin).strip()
        staff_user = None

        # 1. Verify against current session user
        if request.user and request.user.is_authenticated and hasattr(request.user, 'check_pin') and getattr(request.user, 'has_pin', False) and request.user.check_pin(raw_pin):
            staff_user = request.user
        else:
            # 2. Match against active staff users by PIN
            for u in User.objects.filter(is_active=True):
                if hasattr(u, 'check_pin') and getattr(u, 'has_pin', False) and u.check_pin(raw_pin):
                    staff_user = u
                    break

        if not staff_user:
            return Response(
                {'error': 'Incorrect Security PIN. Authorization denied. Please enter your valid 4-digit staff PIN.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        target_id = stock_id or request.data.get('id') or request.data.get('stock_id') or request.data.get('store_stock_id')
        if not target_id:
            return Response({'error': 'Stock record ID is required.'}, status=status.HTTP_400_BAD_REQUEST)

        store_stock = StoreStock.objects.filter(id=target_id).select_related('store', 'product').first()
        if not store_stock:
            return Response({'error': 'Stock record not found.'}, status=status.HTTP_404_NOT_FOUND)

        prod = store_stock.product
        changes = []

        # 1. Medication Name
        new_name = request.data.get('product_name')
        if new_name and str(new_name).strip() and str(new_name).strip() != prod.product_name:
            old_name = prod.product_name
            prod.product_name = str(new_name).strip()
            changes.append(f"Name: '{old_name}' -> '{prod.product_name}'")
            PharmacyTariff.objects.filter(product_name__iexact=old_name).update(
                product_name=prod.product_name,
                staff=staff_user
            )

        # 2. Selling Price / Unit Cost
        new_price_raw = request.data.get('price') or request.data.get('rate')
        if new_price_raw is not None and str(new_price_raw).strip() != '':
            try:
                new_price = Decimal(str(new_price_raw).replace(',', '').replace('₦', '').strip())
                if new_price >= 0 and new_price != prod.price:
                    changes.append(f"Price: ₦{prod.price} -> ₦{new_price}")
                    prod.price = new_price
                    PharmacyTariff.objects.filter(
                        Q(product_id=prod.product_id) | Q(product_name__iexact=prod.product_name),
                        sponsor__isnull=True,
                        plan__isnull=True
                    ).update(rate=new_price, staff=staff_user)
            except Exception:
                pass

        # 3. Unit of Measurement / Dosage Type
        new_uom = request.data.get('minimum_UoM') or request.data.get('uom')
        if new_uom and str(new_uom).strip() != prod.minimum_UoM:
            clean_uom = str(new_uom).strip().lower()[:22]
            changes.append(f"UoM: '{prod.minimum_UoM}' -> '{clean_uom}'")
            prod.minimum_UoM = clean_uom

        # 4. Low Stock Alert Threshold
        new_thresh = request.data.get('low_stock_threshold')
        if new_thresh is not None and str(new_thresh).strip() != '':
            try:
                nt = max(0, int(new_thresh))
                if nt != store_stock.low_stock_threshold:
                    changes.append(f"Threshold: {store_stock.low_stock_threshold} -> {nt}")
                    store_stock.low_stock_threshold = nt
                    prod.low_stock_threshold = nt
            except Exception:
                pass

        # 5. Batch Number & Expiry Date
        new_batch = request.data.get('batch_number')
        if new_batch is not None:
            clean_b = str(new_batch).strip()
            if clean_b != (store_stock.batch_number or ''):
                changes.append(f"Batch: '{store_stock.batch_number}' -> '{clean_b}'")
                store_stock.batch_number = clean_b

        new_expiry = request.data.get('expiry_date')
        if new_expiry is not None:
            clean_exp = str(new_expiry).strip()[:10] if str(new_expiry).strip() else None
            if clean_exp != str(store_stock.expiry_date or ''):
                changes.append(f"Expiry: '{store_stock.expiry_date}' -> '{clean_exp}'")
                store_stock.expiry_date = clean_exp
                prod.expiry_date = clean_exp

        # 6. Stock Count
        new_stock_raw = request.data.get('stock')
        delta = 0
        if new_stock_raw is not None and str(new_stock_raw).strip() != '':
            try:
                new_s = max(0, int(new_stock_raw))
                old_s = store_stock.stock or 0
                if new_s != old_s:
                    delta = new_s - old_s
                    changes.append(f"Stock: {old_s} -> {new_s} ({delta:+d})")
                    store_stock.stock = new_s
                    prod.stock = new_s
            except Exception:
                pass

        # Save updates with staff tracking
        prod.staff = staff_user
        prod.save()
        store_stock.save()

        # Update or record batch
        if store_stock.batch_number:
            StoreStockBatch.objects.update_or_create(
                store=store_stock.store,
                product=prod,
                batch_number=store_stock.batch_number,
                defaults={
                    'quantity': store_stock.stock,
                    'expiry_date': store_stock.expiry_date,
                    'store_stock': store_stock
                }
            )

        # Audit movement record
        editor_display = staff_user.fullname or staff_user.username
        change_desc = "; ".join(changes) if changes else "Medication details verified"
        user_notes = request.data.get('notes') or request.data.get('reason') or ''
        notes_str = f"Edited by {editor_display} (PIN Verified). Changes: {change_desc}"
        if user_notes:
            notes_str += f" | Notes: {user_notes}"
        movement_type = 'ADJUSTMENT' if delta != 0 else 'MODIFICATION'

        StockMovement.objects.create(
            store=store_stock.store,
            product=prod,
            movement_type=movement_type,
            quantity=delta,
            balance_after=store_stock.stock,
            reference_number=f"EDIT-{timezone.now().strftime('%Y%m%d%H%M%S')}",
            notes=notes_str,
            performed_by=staff_user
        )

        return Response({
            'success': True,
            'message': f"Medication '{prod.product_name}' updated successfully by {editor_display} (PIN Verified).",
            'editor_name': editor_display,
            'editor_id': staff_user.id,
            'changes': changes,
            'store_stock': StoreStockSerializer(store_stock).data
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='edit-item')
    def edit_item(self, request):
        return self._do_edit_item(request)

    @action(detail=True, methods=['post', 'patch', 'put'], url_path='edit-item')
    def edit_single_item(self, request, pk=None):
        return self._do_edit_item(request, stock_id=pk)

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        """
        Download pre-populated Excel (.xlsx) or CSV receiving template containing ALL existing medical items
        in the database (1,037+ products) with their current stock and unit costs.
        """
        import io, openpyxl, csv
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from django.http import HttpResponse

        store_id = request.query_params.get('store')
        target_store = PharmacyStore.objects.filter(id=store_id).first() if store_id else (
            PharmacyStore.objects.filter(is_central=True).first() or PharmacyStore.objects.first()
        )

        file_format = (request.query_params.get('format') or 'xlsx').lower()
        category = (request.query_params.get('category') or 'all').lower()

        # Query all products in database
        products_qs = Product.objects.all().order_by('product_name')

        # Stock map for current on-hand quantities
        stock_map = {}
        if target_store:
            for s in StoreStock.objects.filter(store=target_store).values('product_id', 'stock'):
                stock_map[s['product_id']] = s['stock']

        items_data = []
        for p in products_qs:
            name = p.product_name or ''
            uom = p.minimum_UoM or 'tablets'

            # Apply category filter if requested
            if category == 'tablets' and not (uom == 'tablets' or 'tab' in name.lower()):
                continue
            elif category == 'capsules' and not (uom == 'capsules' or 'cap' in name.lower()):
                continue
            elif category == 'injections' and not (uom in ['vial', 'ampoules', 'syringes'] or any(k in name.lower() for k in ['inj', 'vial', 'ampoule', 'infusion'])):
                continue
            elif category == 'syrups' and not (uom in ['bottles', 'mls', 'tins'] or any(k in name.lower() for k in ['syrup', 'suspension', 'liquid'])):
                continue
            elif category == 'ointments' and not (uom in ['tubes', 'tins'] or any(k in name.lower() for k in ['ointment', 'cream', 'gel'])):
                continue

            current_stock = stock_map.get(p.id, p.stock or 0)
            items_data.append({
                'Medication_Name': name,
                'Dosage_Type_UOM': uom,
                'Current_In_Stock': current_stock,
                'Quantity_Received': '',
                'Batch_Number': '',
                'Expiry_Date': '',
                'Unit_Cost': float(p.price) if p.price else '',
            })

        # Add 5 blank template rows for new drugs
        for i in range(1, 6):
            items_data.append({
                'Medication_Name': f"[Enter New Medication {i} Name if not listed]",
                'Dosage_Type_UOM': category if category != 'all' else 'tablets',
                'Current_In_Stock': 0,
                'Quantity_Received': '',
                'Batch_Number': '',
                'Expiry_Date': '',
                'Unit_Cost': '',
            })

        if file_format == 'csv':
            response = HttpResponse(content_type='text/csv')
            response['Content-Disposition'] = 'attachment; filename="Vendor_Receiving_Template_ALL.csv"'
            writer = csv.writer(response)
            writer.writerow(['Medication_Name', 'Dosage_Type_UOM', 'Current_In_Stock', 'Quantity_Received', 'Batch_Number', 'Expiry_Date', 'Unit_Cost'])
            for item in items_data:
                writer.writerow([
                    item['Medication_Name'],
                    item['Dosage_Type_UOM'],
                    item['Current_In_Stock'],
                    item['Quantity_Received'],
                    item['Batch_Number'],
                    item['Expiry_Date'],
                    item['Unit_Cost']
                ])
            return response

        # Excel (.xlsx) format
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "GRN_Receiving_Template"
        ws.views.sheetView[0].showGridLines = True

        headers = ['Medication_Name', 'Dosage_Type_UOM', 'Current_In_Stock', 'Quantity_Received', 'Batch_Number', 'Expiry_Date', 'Unit_Cost']
        ws.append(headers)

        header_fill = PatternFill(start_color="0F766E", end_color="0F766E", fill_type="solid")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        thin_border = Border(
            left=Side(style='thin', color='CBD5E1'),
            right=Side(style='thin', color='CBD5E1'),
            top=Side(style='thin', color='CBD5E1'),
            bottom=Side(style='thin', color='CBD5E1')
        )

        for col_num in range(1, len(headers) + 1):
            cell = ws.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
            cell.border = thin_border
        ws.row_dimensions[1].height = 28

        for row_idx, item in enumerate(items_data, start=2):
            ws.append([
                item['Medication_Name'],
                item['Dosage_Type_UOM'],
                item['Current_In_Stock'],
                item['Quantity_Received'],
                item['Batch_Number'],
                item['Expiry_Date'],
                item['Unit_Cost']
            ])
            for col_num in range(1, len(headers) + 1):
                c = ws.cell(row=row_idx, column=col_num)
                c.border = thin_border
                if col_num in (3, 4, 7):
                    c.alignment = Alignment(horizontal="right")
                elif col_num in (2, 5, 6):
                    c.alignment = Alignment(horizontal="center")
                else:
                    c.alignment = Alignment(horizontal="left")

        widths = {'A': 42, 'B': 18, 'C': 18, 'D': 20, 'E': 18, 'F': 16, 'G': 16}
        for col, width in widths.items():
            ws.column_dimensions[col].width = width

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = 'attachment; filename="Vendor_Receiving_Template_ALL.xlsx"'
        return response

    @action(detail=False, methods=['post'], url_path='bulk-upload-stock')
    def bulk_upload_stock(self, request):
        """
        Bulk upload delivered items from CSV / Excel directly into Central Medical Store (or specified store).
        Automatically creates missing Products with sequential ISL-xxx SKUs, records StoreStockBatch (FEFO),
        updates StoreStock and Product.stock, records StockMovement, and syncs PharmacyTariff.
        """
        import io, csv, uuid
        from decimal import Decimal
        from django.db import transaction
        from inventory.utils import get_next_isl_sku

        store_id = request.data.get('store_id') or request.data.get('store')
        if not store_id:
            store = PharmacyStore.objects.filter(is_central=True).first() or PharmacyStore.objects.first()
        else:
            store = PharmacyStore.objects.filter(id=store_id).first()

        if not store:
            return Response({'error': 'Target store not found.'}, status=status.HTTP_404_NOT_FOUND)

        raw_rows = []
        uploaded_file = request.FILES.get('file')

        if uploaded_file:
            filename = uploaded_file.name.lower()
            try:
                if filename.endswith('.csv'):
                    decoded_file = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                    reader = csv.DictReader(io.StringIO(decoded_file))
                    for row in reader:
                        raw_rows.append(row)
                elif filename.endswith(('.xlsx', '.xls')):
                    import pandas as pd
                    df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                    df = df.where(pd.notnull(df), None)
                    raw_rows = df.to_dict(orient='records')
                else:
                    return Response(
                        {'error': 'Unsupported file format. Please upload a CSV (.csv) or Excel (.xlsx, .xls) file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response({'error': f'Error reading uploaded file: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        elif 'items' in request.data:
            raw_rows = request.data.get('items', [])
        else:
            return Response({'error': 'No file or items array provided.'}, status=status.HTTP_400_BAD_REQUEST)

        if not raw_rows:
            return Response({'error': 'The uploaded file contains no data rows.'}, status=status.HTTP_400_BAD_REQUEST)

        staff = request.user if request.user.is_authenticated else User.objects.first()
        grn_ref = f"BULK-GRN-{timezone.now().strftime('%Y%m%d%H%M')}-{uuid.uuid4().hex[:4].upper()}"

        created_prods = 0
        updated_prods = 0
        stocked_count = 0
        total_units = 0

        with transaction.atomic():
            for idx, row in enumerate(raw_rows, start=1):
                if not isinstance(row, dict):
                    continue
                clean = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
                name = (
                    clean.get('medication_name')
                    or clean.get('product_name')
                    or clean.get('drug_name')
                    or clean.get('name')
                    or clean.get('item')
                )
                if not name or not str(name).strip() or str(name).strip().startswith('['):
                    continue
                name = str(name).strip()

                uom = str(clean.get('dosage_type_uom') or clean.get('uom') or clean.get('unit') or 'tablets').strip() or 'tablets'
                
                qty_raw = clean.get('quantity_received') or clean.get('quantity') or clean.get('current_in_stock') or clean.get('qty') or 1
                try:
                    qty = int(float(str(qty_raw).replace(',', '').strip()))
                    if qty <= 0:
                        qty = 1
                except Exception:
                    qty = 1

                batch_num = str(clean.get('batch_number') or clean.get('batch') or clean.get('lot') or '').strip()
                expiry = clean.get('expiry_date') or clean.get('expiry') or None
                if expiry:
                    expiry = str(expiry).strip()[:10]

                cost_raw = clean.get('unit_cost') or clean.get('cost') or clean.get('price') or clean.get('rate') or 0
                try:
                    cost = Decimal(str(cost_raw).replace(',', '').replace('₦', '').strip())
                except Exception:
                    cost = Decimal('0.00')

                # 1. Product
                prod = Product.objects.filter(product_name__iexact=name).first()
                if not prod:
                    sku = get_next_isl_sku()
                    prod = Product.objects.create(
                        product_name=name,
                        product_id=sku,
                        minimum_UoM=uom.lower()[:22],
                        price=cost,
                        stock=0,
                        low_stock_threshold=10,
                        staff=staff
                    )
                    created_prods += 1
                else:
                    if cost > 0 and (prod.price == 0 or prod.price is None):
                        prod.price = cost
                        prod.save(update_fields=['price'])
                    updated_prods += 1

                # 2. StoreStock
                store_stock, _ = StoreStock.objects.get_or_create(
                    store=store,
                    product=prod,
                    defaults={'stock': 0, 'low_stock_threshold': 10}
                )
                store_stock.stock = (store_stock.stock or 0) + qty
                if batch_num:
                    store_stock.batch_number = batch_num
                if expiry:
                    store_stock.expiry_date = expiry
                store_stock.save()

                # 3. StoreStockBatch (FEFO lot tracking)
                if batch_num:
                    batch_obj, _ = StoreStockBatch.objects.get_or_create(
                        store=store,
                        product=prod,
                        batch_number=batch_num,
                        defaults={
                            'quantity': 0,
                            'expiry_date': expiry,
                            'store_stock': store_stock
                        }
                    )
                    batch_obj.quantity = (batch_obj.quantity or 0) + qty
                    if expiry:
                        batch_obj.expiry_date = expiry
                    batch_obj.store_stock = store_stock
                    batch_obj.save()

                # 4. Product global stock
                prod.stock = store_stock.stock
                prod.save(update_fields=['stock'])

                # 5. StockMovement audit
                StockMovement.objects.create(
                    store=store,
                    product=prod,
                    movement_type='PURCHASE_GRN',
                    quantity=qty,
                    balance_after=store_stock.stock,
                    reference_number=grn_ref,
                    notes=f"Bulk inventory intake: {qty} units (Batch: {batch_num or 'N/A'})",
                    performed_by=staff
                )

                # 6. PharmacyTariff
                PharmacyTariff.objects.update_or_create(
                    product_name=prod.product_name,
                    sponsor=None,
                    plan=None,
                    defaults={
                        'product_id': prod.product_id,
                        'rate': cost if cost > 0 else Decimal('500.00'),
                        'staff': staff
                    }
                )

                stocked_count += 1
                total_units += qty

        return Response({
            'success': True,
            'message': f"Successfully imported and stocked {stocked_count} medical items ({total_units:,} units) into {store.name}!",
            'stocked_count': stocked_count,
            'total_units': total_units,
            'created_products': created_prods,
            'updated_products': updated_prods,
            'store_name': store.name,
        }, status=status.HTTP_200_OK)

    @action(detail=False, methods=['post'], url_path='receive-vendor-stock')
    def receive_vendor_stock(self, request):
        """
        Receive purchased medications from a vendor / pharmaceutical supplier directly into
        Central Medical Store (or specified store) and update real-time stock balances
        along with complete PURCHASE_GRN audit trail entries.
        """
        import uuid
        from django.db import transaction

        store_id = request.data.get('store_id') or request.data.get('store')
        vendor_id = request.data.get('vendor_id') or request.data.get('vendor')
        vendor_name_custom = request.data.get('vendor_name', '').strip()
        invoice_number = request.data.get('invoice_number', '').strip()
        notes = request.data.get('notes', '').strip()
        items_data = request.data.get('items', [])

        # Default to Central Medical Store if store_id not explicitly given
        if not store_id:
            store = PharmacyStore.objects.filter(is_central=True).first()
        else:
            store = PharmacyStore.objects.filter(id=store_id).first()

        if not store:
            return Response({'error': 'Target store / Central Medical Store not found'}, status=status.HTTP_404_NOT_FOUND)

        if not items_data:
            return Response({'error': 'At least one medication item must be received'}, status=status.HTTP_400_BAD_REQUEST)

        # Lookup vendor name if vendor_id passed
        vendor_name = vendor_name_custom
        if vendor_id:
            vendor = PharmacyVendor.objects.filter(id=vendor_id).first()
            if vendor:
                vendor_name = vendor.name

        if not vendor_name:
            vendor_name = 'External Supplier / Vendor'

        grn_ref = invoice_number or f"GRN-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"
        user = request.user if request.user.is_authenticated else None

        received_results = []

        try:
            with transaction.atomic():
                for itm in items_data:
                    prod_id = itm.get('product_id') or itm.get('product')
                    qty = int(itm.get('quantity') or itm.get('quantity_received') or 0)
                    if not prod_id or qty <= 0:
                        continue

                    product = Product.objects.filter(id=prod_id).first()
                    if not product:
                        continue

                    batch_num = (itm.get('batch_number') or '').strip()
                    expiry = itm.get('expiry_date') or None

                    store_stock, _ = StoreStock.objects.get_or_create(
                        store=store,
                        product=product,
                        defaults={'stock': 0}
                    )
                    store_stock.stock += qty

                    # Record individual batch lot in StoreStockBatch (FEFO Tracking)
                    if batch_num:
                        batch_obj, _ = StoreStockBatch.objects.get_or_create(
                            store=store,
                            product=product,
                            batch_number=batch_num,
                            defaults={
                                'store_stock': store_stock,
                                'expiry_date': expiry,
                                'quantity': 0,
                                'supplier': vendor_name
                            }
                        )
                        batch_obj.quantity += qty
                        if expiry:
                            batch_obj.expiry_date = expiry
                        batch_obj.store_stock = store_stock
                        if vendor_name and not batch_obj.supplier:
                            batch_obj.supplier = vendor_name
                        batch_obj.save()

                    # Set primary store_stock batch & expiry to earliest active batch (FEFO protocol)
                    earliest_batch = store_stock.batches.filter(quantity__gt=0, expiry_date__isnull=False).order_by('expiry_date').first()
                    if earliest_batch:
                        store_stock.batch_number = earliest_batch.batch_number
                        store_stock.expiry_date = earliest_batch.expiry_date
                    elif batch_num:
                        store_stock.batch_number = batch_num
                        if expiry:
                            store_stock.expiry_date = expiry

                    store_stock.save()

                    # Increment global Product.stock if store is central
                    if store.is_central:
                        product.stock = (product.stock or 0) + qty
                        product.save(update_fields=['stock'])

                    # Audit trail: PURCHASE_GRN
                    audit_notes = f"Received from {vendor_name}"
                    if notes:
                        audit_notes += f" - {notes}"

                    StockMovement.objects.create(
                        store=store,
                        product=product,
                        movement_type='PURCHASE_GRN',
                        quantity=qty,
                        balance_after=store_stock.stock,
                        reference_number=grn_ref,
                        notes=audit_notes,
                        performed_by=user
                    )

                    received_results.append({
                        'product_id': product.id,
                        'product_name': product.product_name,
                        'quantity_received': qty,
                        'new_stock': store_stock.stock
                    })

                if not received_results:
                    return Response({'error': 'No valid items with positive quantities were provided'}, status=status.HTTP_400_BAD_REQUEST)

                return Response({
                    'success': True,
                    'message': f"Successfully received and stocked {len(received_results)} item(s) into {store.name}!",
                    'grn_reference': grn_ref,
                    'store_name': store.name,
                    'vendor_name': vendor_name,
                    'items_count': len(received_results),
                    'results': received_results
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': f"Failed to receive vendor stock: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)



class StockTransferViewSet(viewsets.ModelViewSet):
    """
    Manage stock distributions from Central Store to Pharmacy branches.
    Handles dispatch, in-transit status, and receipt confirmation.
    """
    queryset = StockTransfer.objects.all().select_related(
        'source_store', 'destination_store', 'dispatched_by', 'received_by'
    ).prefetch_related('items__product').order_by('-created_date')
    serializer_class = StockTransferSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        source_id = self.request.query_params.get('source', None)
        if source_id:
            qs = qs.filter(source_store_id=source_id)
        destination_id = self.request.query_params.get('destination', None)
        if destination_id:
            qs = qs.filter(destination_store_id=destination_id)
        status_param = self.request.query_params.get('status', None)
        if status_param and status_param != 'all':
            qs = qs.filter(status=status_param)
        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(transfer_number__icontains=search) |
                Q(source_store__name__icontains=search) |
                Q(destination_store__name__icontains=search)
            )
        return qs

    def create(self, request, *args, **kwargs):
        """
        Create a distribution transfer with multiple drug line items.
        Automatically checks source store stock and sets in_transit.
        """
        import uuid
        from django.db import transaction

        source_id = request.data.get('source_store') or request.data.get('source_store_id')
        dest_id = request.data.get('destination_store') or request.data.get('destination_store_id')
        notes = request.data.get('notes', '')
        items_data = request.data.get('items', [])

        if not source_id or not dest_id:
            return Response({'error': 'Source store and Destination pharmacy are required'}, status=status.HTTP_400_BAD_REQUEST)

        if str(source_id) == str(dest_id):
            return Response({'error': 'Source and Destination cannot be the same store'}, status=status.HTTP_400_BAD_REQUEST)

        if not items_data:
            return Response({'error': 'At least one drug item must be selected for transfer'}, status=status.HTTP_400_BAD_REQUEST)

        source_store = PharmacyStore.objects.filter(id=source_id).first()
        dest_store = PharmacyStore.objects.filter(id=dest_id).first()
        if not source_store or not dest_store:
            return Response({'error': 'Invalid source or destination store'}, status=status.HTTP_404_NOT_FOUND)

        user = request.user if request.user.is_authenticated else None
        transfer_number = f"TRF-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"

        try:
            with transaction.atomic():
                transfer = StockTransfer.objects.create(
                    transfer_number=transfer_number,
                    source_store=source_store,
                    destination_store=dest_store,
                    status='in_transit',
                    notes=notes,
                    dispatched_by=user,
                    dispatched_at=timezone.now()
                )

                for itm in items_data:
                    prod_id = itm.get('product') or itm.get('product_id')
                    qty_sent = int(itm.get('quantity_sent') or itm.get('quantity') or 0)
                    if not prod_id or qty_sent <= 0:
                        continue

                    prod = Product.objects.filter(id=prod_id).first()
                    if not prod:
                        continue

                    # Validate source stock
                    src_stock, _ = StoreStock.objects.get_or_create(
                        store=source_store, product=prod, defaults={'stock': prod.stock or 0}
                    )
                    if src_stock.stock < qty_sent:
                        raise ValueError(f"Insufficient stock for {prod.product_name} in {source_store.name}. Available: {src_stock.stock}, Requested: {qty_sent}")

                    # Deduct from source store
                    src_stock.stock -= qty_sent
                    src_stock.save()

                    # Deduct from global Product.stock if source is central store
                    if source_store.is_central:
                        prod.stock = max(0, (prod.stock or 0) - qty_sent)
                        prod.save(update_fields=['stock'])

                    # Audit trail: TRANSFER_OUT
                    StockMovement.objects.create(
                        store=source_store,
                        product=prod,
                        movement_type='TRANSFER_OUT',
                        quantity=-qty_sent,
                        balance_after=src_stock.stock,
                        reference_number=transfer.transfer_number,
                        notes=f"Dispatched to {dest_store.name}",
                        performed_by=user
                    )

                    StockTransferItem.objects.create(
                        transfer=transfer,
                        product=prod,
                        quantity_sent=qty_sent,
                        quantity_received=0,
                        batch_number=itm.get('batch_number') or src_stock.batch_number or '',
                        expiry_date=itm.get('expiry_date') or src_stock.expiry_date,
                        notes=itm.get('notes', '')
                    )

                serializer = self.get_serializer(transfer)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f"Failed to create transfer: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='receive')
    def receive_stock(self, request, pk=None):
        """
        Receiving pharmacy clicks 'Confirm Receipt' to accept physical goods into its inventory.
        Atomically increments destination pharmacy stock and logs audit trail.
        """
        from django.db import transaction

        transfer = self.get_object()
        if transfer.status == 'received':
            return Response({'error': 'This transfer has already been received.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        received_items_data = request.data.get('items', [])
        received_map = {int(i.get('item_id')): int(i.get('quantity_received', 0)) for i in received_items_data if 'item_id' in i}

        try:
            with transaction.atomic():
                for item in transfer.items.all():
                    qty_to_receive = received_map.get(item.id, item.quantity_sent)
                    item.quantity_received = max(0, qty_to_receive)
                    item.save(update_fields=['quantity_received'])

                    # Increment destination pharmacy stock
                    dest_stock, _ = StoreStock.objects.get_or_create(
                        store=transfer.destination_store,
                        product=item.product,
                        defaults={'stock': 0, 'low_stock_threshold': 10}
                    )
                    dest_stock.stock += item.quantity_received
                    if item.batch_number:
                        dest_stock.batch_number = item.batch_number
                    if item.expiry_date:
                        dest_stock.expiry_date = item.expiry_date
                    dest_stock.save()

                    # Audit trail: TRANSFER_IN
                    StockMovement.objects.create(
                        store=transfer.destination_store,
                        product=item.product,
                        movement_type='TRANSFER_IN',
                        quantity=item.quantity_received,
                        balance_after=dest_stock.stock,
                        reference_number=transfer.transfer_number,
                        notes=f"Received from {transfer.source_store.name}",
                        performed_by=user
                    )

                transfer.status = 'received'
                transfer.received_by = user
                transfer.received_at = timezone.now()
                transfer.save(update_fields=['status', 'received_by', 'received_at'])

                # If tied to a requisition, mark it completed
                if transfer.requisition:
                    transfer.requisition.status = 'completed'
                    transfer.requisition.save(update_fields=['status'])

                serializer = self.get_serializer(transfer)
                return Response({
                    'success': True,
                    'message': f"Stock successfully received into {transfer.destination_store.name}!",
                    'transfer': serializer.data
                }, status=status.HTTP_200_OK)

        except Exception as e:
            return Response({'error': f"Failed to receive stock: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StockRequisitionViewSet(viewsets.ModelViewSet):
    """
    Pharmacy Stock Requisition ViewSet.
    Allows branch pharmacies to request medications from Central Medical Store.
    """
    queryset = StockRequisition.objects.all().select_related(
        'requesting_store', 'fulfilling_store', 'requested_by', 'approved_by'
    ).prefetch_related('items__product').order_by('-created_date')
    serializer_class = StockRequisitionSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        requesting_id = self.request.query_params.get('requesting_store', None)
        if requesting_id:
            qs = qs.filter(requesting_store_id=requesting_id)
        fulfilling_id = self.request.query_params.get('fulfilling_store', None)
        if fulfilling_id:
            qs = qs.filter(fulfilling_store_id=fulfilling_id)
        store_id = self.request.query_params.get('store', None)
        if store_id:
            qs = qs.filter(Q(requesting_store_id=store_id) | Q(fulfilling_store_id=store_id))
        status_param = self.request.query_params.get('status', None)
        if status_param and status_param != 'all':
            qs = qs.filter(status=status_param)
        return qs

    def create(self, request, *args, **kwargs):
        """
        Create a new drug requisition from a branch pharmacy to central store or other pharmacy.
        """
        import uuid
        from django.db import transaction

        req_store_id = request.data.get('requesting_store') or request.data.get('requesting_store_id')
        ful_store_id = request.data.get('fulfilling_store') or request.data.get('fulfilling_store_id')

        if not req_store_id:
            return Response({'error': 'Requesting pharmacy is required'}, status=status.HTTP_400_BAD_REQUEST)

        # Default fulfilling store to primary Central Store if not specified
        if not ful_store_id:
            central = PharmacyStore.objects.filter(is_central=True).first()
            if central:
                ful_store_id = central.id
            else:
                return Response({'error': 'No Central Store found to fulfill requisition'}, status=status.HTTP_400_BAD_REQUEST)

        if str(req_store_id) == str(ful_store_id):
            return Response({'error': 'Requesting pharmacy and fulfilling location cannot be the same.'}, status=status.HTTP_400_BAD_REQUEST)

        requesting_store = PharmacyStore.objects.filter(id=req_store_id).first()
        fulfilling_store = PharmacyStore.objects.filter(id=ful_store_id).first()
        items_data = request.data.get('items', [])

        if not items_data:
            return Response({'error': 'At least one medication must be requested'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        req_number = f"REQ-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"

        try:
            with transaction.atomic():
                requisition = StockRequisition.objects.create(
                    requisition_number=req_number,
                    requesting_store=requesting_store,
                    fulfilling_store=fulfilling_store,
                    priority=request.data.get('priority', 'normal'),
                    notes=request.data.get('notes', ''),
                    status='pending',
                    requested_by=user
                )

                for itm in items_data:
                    prod_id = itm.get('product') or itm.get('product_id')
                    qty = int(itm.get('quantity_requested') or itm.get('quantity') or 0)
                    if not prod_id or qty <= 0:
                        continue
                    prod = Product.objects.filter(id=prod_id).first()
                    if not prod:
                        continue

                    StockRequisitionItem.objects.create(
                        requisition=requisition,
                        product=prod,
                        quantity_requested=qty,
                        quantity_approved=qty,
                        notes=itm.get('notes', '')
                    )

                serializer = self.get_serializer(requisition)
                return Response(serializer.data, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': f"Failed to create requisition: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'], url_path='fulfill')
    def fulfill_requisition(self, request, pk=None):
        """
        Store manager approves and fulfills the requisition, generating an outgoing StockTransfer.
        """
        import uuid
        from django.db import transaction

        req = self.get_object()
        if req.status in ['dispatched', 'completed']:
            return Response({'error': 'This requisition has already been dispatched or completed.'}, status=status.HTTP_400_BAD_REQUEST)

        user = request.user if request.user.is_authenticated else None
        transfer_number = f"TRF-{timezone.now().strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"

        try:
            with transaction.atomic():
                approval_notes = request.data.get('notes', '').strip()
                transfer_notes = f"Fulfillment for Requisition #{req.requisition_number}"
                if approval_notes:
                    transfer_notes += f" - Note: {approval_notes}"

                transfer = StockTransfer.objects.create(
                    transfer_number=transfer_number,
                    source_store=req.fulfilling_store,
                    destination_store=req.requesting_store,
                    requisition=req,
                    status='in_transit',
                    notes=transfer_notes,
                    dispatched_by=user,
                    dispatched_at=timezone.now()
                )

                # Map any customized approved quantities from request payload: items: [{ id: 1, quantity_approved: 5, notes: '' }]
                custom_items = request.data.get('items', [])
                approved_map = {}
                item_notes_map = {}
                for itm_data in custom_items:
                    item_id = itm_data.get('id')
                    if item_id is not None:
                        try:
                            approved_map[str(item_id)] = max(0, int(itm_data.get('quantity_approved', 0)))
                        except (ValueError, TypeError):
                            approved_map[str(item_id)] = 0
                        if 'notes' in itm_data:
                            item_notes_map[str(item_id)] = itm_data.get('notes', '')

                dispatched_count = 0
                for itm in req.items.all():
                    if str(itm.id) in approved_map:
                        qty_to_send = approved_map[str(itm.id)]
                        itm.quantity_approved = qty_to_send
                        if str(itm.id) in item_notes_map:
                            itm.notes = item_notes_map[str(itm.id)]
                        itm.save(update_fields=['quantity_approved', 'notes'])
                    else:
                        qty_to_send = itm.quantity_approved if itm.quantity_approved > 0 else itm.quantity_requested
                        itm.quantity_approved = qty_to_send
                        itm.save(update_fields=['quantity_approved'])

                    # Skip items that were approved for 0 units (rejected or unavailable)
                    if qty_to_send <= 0:
                        continue

                    src_stock, _ = StoreStock.objects.get_or_create(
                        store=req.fulfilling_store,
                        product=itm.product,
                        defaults={'stock': itm.product.stock or 0}
                    )
                    if src_stock.stock < qty_to_send:
                        raise ValueError(f"Insufficient stock for {itm.product.product_name} in {req.fulfilling_store.name}. Available: {src_stock.stock}, Approved: {qty_to_send}")

                    src_stock.stock -= qty_to_send
                    src_stock.save()

                    if req.fulfilling_store.is_central:
                        itm.product.stock = max(0, (itm.product.stock or 0) - qty_to_send)
                        itm.product.save(update_fields=['stock'])

                    StockMovement.objects.create(
                        store=req.fulfilling_store,
                        product=itm.product,
                        movement_type='TRANSFER_OUT',
                        quantity=-qty_to_send,
                        balance_after=src_stock.stock,
                        reference_number=transfer.transfer_number,
                        notes=f"Requisition fulfillment to {req.requesting_store.name}",
                        performed_by=user
                    )

                    StockTransferItem.objects.create(
                        transfer=transfer,
                        product=itm.product,
                        quantity_sent=qty_to_send,
                        quantity_received=0,
                        notes=itm.notes
                    )
                    dispatched_count += 1

                req.status = 'dispatched'
                req.approved_by = user
                if approval_notes:
                    req.notes = f"{req.notes}\n[Approval Note]: {approval_notes}" if req.notes else f"[Approval Note]: {approval_notes}"
                req.save(update_fields=['status', 'approved_by', 'notes'])

                return Response({
                    'success': True,
                    'message': f"Requisition #{req.requisition_number} approved and dispatched to {req.requesting_store.name}!",
                    'transfer_number': transfer.transfer_number
                }, status=status.HTTP_200_OK)

        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            return Response({'error': f"Failed to fulfill requisition: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class StockMovementViewSet(viewsets.ReadOnlyModelViewSet):
    """
    Read-only Stock Movement audit trail ledger.
    """
    queryset = StockMovement.objects.all().select_related('store', 'product', 'performed_by').order_by('-created_date')
    serializer_class = StockMovementSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        store_id = self.request.query_params.get('store', None)
        if store_id:
            qs = qs.filter(store_id=store_id)
        product_id = self.request.query_params.get('product', None)
        if product_id:
            qs = qs.filter(product_id=product_id)
        movement_type = self.request.query_params.get('type', None)
        if movement_type:
            qs = qs.filter(movement_type=movement_type)
        return qs


class PharmacyVendorViewSet(viewsets.ModelViewSet):
    """
    CRUD API for Pharmaceutical Vendors, Manufacturers & Suppliers.
    """
    queryset = PharmacyVendor.objects.all().order_by('name')
    serializer_class = PharmacyVendorSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None

    def get_queryset(self):
        qs = super().get_queryset()
        # Seed default vendors if table is empty
        if not qs.exists():
            default_vendors = [
                {'name': 'Chi Pharmaceuticals Ltd', 'code': 'VND-CHI', 'contact_person': 'Alhaji Sanusi Chi', 'phone': '+234 803 111 2233', 'email': 'orders@chipharm.com', 'address': '14 Wharf Road, Apapa, Lagos', 'product_lines': 'Antibiotics, IV Infusions, Ceftriaxone', 'rating': '5.0', 'status': 'Active'},
                {'name': 'May & Baker Nigeria Plc', 'code': 'VND-MNB', 'contact_person': 'Mrs. Funke Adeyemi', 'phone': '+234 802 333 4455', 'email': 'sales@may-baker.com', 'address': '3/5 Sapara Street, Ikeja, Lagos', 'product_lines': 'Analgesics, Paracetamol, Anti-Malarials', 'rating': '4.8', 'status': 'Active'},
                {'name': 'Fidson Healthcare Plc', 'code': 'VND-FID', 'contact_person': 'Dr. Emeka Okafor', 'phone': '+234 809 777 8899', 'email': 'supply@fidson.com', 'address': 'Km 38 Lagos-Abeokuta Expressway, Sango-Ota', 'product_lines': 'Gastrointestinal, Antacids, Cough Syrups', 'rating': '4.9', 'status': 'Active'},
                {'name': 'Emzor Pharmaceutical Industries', 'code': 'VND-EMZ', 'contact_person': 'Mr. Chidi Okon', 'phone': '+234 802 000 1122', 'email': 'orders@emzorpharma.com', 'address': 'Ajao Estate, Isolo, Lagos', 'product_lines': 'Multivitamins, Pediatric Syrups, Pain Relief', 'rating': '4.9', 'status': 'Active'},
            ]
            for v_data in default_vendors:
                PharmacyVendor.objects.create(**v_data)
            qs = PharmacyVendor.objects.all().order_by('name')

        search = self.request.query_params.get('search', '').strip()
        if search:
            qs = qs.filter(
                Q(name__icontains=search) |
                Q(code__icontains=search) |
                Q(product_lines__icontains=search) |
                Q(contact_person__icontains=search)
            )
        status_param = self.request.query_params.get('status', None)
        if status_param and status_param.lower() != 'all':
            qs = qs.filter(status__iexact=status_param)
        return qs


