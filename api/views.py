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
from patients.models import PatientProfile, PatientCategory, PatientPlan, PatientAppointment, Sponsor
from queue_operations.models import NurseWaitingList, VisitPurpose, DoctorWaitingList, PatientEncounter
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

        return Response({
            'token': token.key,
            'user': user_data,
            'department': user.department.department if user.department else 'Admin',
            'modules': user.department.modules if (user.department and user.department.modules) else [],
        })


class CurrentUserView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        serializer = UserSerializer(request.user)
        return Response({
            'user': serializer.data,
            'department': request.user.department.department if request.user.department else 'Admin',
            'modules': request.user.department.modules if (request.user.department and request.user.department.modules) else [],
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
            'user': UserSerializer(user).data,
            'has_pin': bool(user.pin and user.pin != 0),
            'department': user.department.department if user.department else 'Admin'
        })

    def put(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        pin_code = request.data.get('pin_code')
        if user.pin and user.pin != 0:
            if not pin_code or str(pin_code) != str(user.pin):
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
        user.save()

        return Response({
            'detail': 'Profile updated successfully!',
            'user': UserSerializer(user).data
        })


class ChangePasswordView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        user = request.user if request.user.is_authenticated else User.objects.first()
        if not user:
            return Response({'detail': 'User not found.'}, status=status.HTTP_404_NOT_FOUND)

        old_password = request.data.get('old_password', '')
        new_password = request.data.get('new_password', '')

        if not new_password:
            return Response({'detail': 'New password is required.'}, status=status.HTTP_400_BAD_REQUEST)

        if user.has_usable_password() and request.user.is_authenticated:
            if not user.check_password(old_password):
                return Response({'detail': 'Current password is incorrect.'}, status=status.HTTP_400_BAD_REQUEST)

        user.set_password(new_password)
        user.save()
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

        user.pin = int(new_pin)
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
        qs = super().get_queryset()
        query = self.request.query_params.get('search', None)
        if query:
            qs = qs.filter(
                Q(surname__icontains=query) |
                Q(first_name__icontains=query) |
                Q(other_name__icontains=query) |
                Q(hospital_number__icontains=query) |
                Q(phone_number__icontains=query)
            )
        category_id = self.request.query_params.get('category', None)
        if category_id:
            qs = qs.filter(category_id=category_id)
        active = self.request.query_params.get('active', None)
        if active is not None:
            qs = qs.filter(active=active)
        return qs

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

        current_user = request.user if (request.user and request.user.is_authenticated) else None
        authorizing_staff = None

        if current_user and getattr(current_user, 'pin', 0) == pin_int and pin_int > 0:
            authorizing_staff = current_user
        else:
            matching_staff = User.objects.filter(pin=pin_int, is_active=True).exclude(pin=0).first()
            if matching_staff:
                authorizing_staff = matching_staff
            elif current_user and getattr(current_user, 'pin', 0) == 0:
                return Response(
                    {'detail': 'Your account has no security PIN configured. Please set your 4-digit PIN in Profile Settings.'},
                    status=status.HTTP_400_BAD_REQUEST
                )
            else:
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
            qs = qs.filter(arrival_date=today, completed=0).order_by('arrival_time', 'created_date')
        elif status_filter == 'upcoming':
            qs = qs.filter(arrival_date__gt=today, completed=0).order_by('arrival_date', 'arrival_time')
        elif status_filter == 'completed':
            qs = qs.filter(completed=1)
        elif status_filter == 'cancelled':
            qs = qs.filter(completed=2)
        elif status_filter == 'expired':
            qs = qs.filter(arrival_date__lt=today, completed=0)

        date_param = self.request.query_params.get('date', None)
        if date_param:
            qs = qs.filter(arrival_date=date_param)

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
        today_count = PatientAppointment.objects.filter(arrival_date=today, completed=0).count()
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
    queryset = Invoice.objects.all().select_related('patient', 'category', 'staff').order_by('-created_date')
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
        import random
        user = self.request.user if self.request.user.is_authenticated else None
        patient = serializer.validated_data.get('patient')
        category = serializer.validated_data.get('category') or (patient.category if patient else None)
        invoice_number = serializer.validated_data.get('invoice_number') or f"INV-{random.randint(10000, 99999)}"
        invoice = serializer.save(staff=user, category=category, invoice_number=invoice_number)
        if patient:
            try:
                tu, _ = TransactionUpdate.objects.get_or_create(patient=patient, completed=0)
                tu.invoice_raised = (tu.invoice_raised or 0) + 1
                tu.save()
            except Exception:
                pass


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

