from rest_framework import serializers
from users.models import User, Category
from patients.models import PatientProfile, PatientCategory, PatientPlan, PatientAppointment, Sponsor, FamilyFolder, FamilyMember
from queue_operations.models import (
    VisitPurpose, NurseWaitingList, PatientBackgroundHealth, DoctorWaitingList,
    PatientEncounter, PatientDiagnosis, PresentingComplaint, WrittenPrescriptions,
    ConsultationDraft
)
from Billings.models import Invoice, Receipt, Deposit, Refund, TransactionUpdate
from IPD.models import AdmissionTable, Ward, Bed, BedAllocation
from ANC.models import ANCRegistration
from OPD_pharm.models import OpdDrugs
from radio_lab.models import RadiologyLab


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'department', 'modules']


class UserSerializer(serializers.ModelSerializer):
    department_name = serializers.CharField(source='department.department', read_only=True)
    department_modules = serializers.JSONField(source='department.modules', read_only=True)
    avatar_url = serializers.SerializerMethodField(read_only=True)

    def get_avatar_url(self, obj):
        if obj.avatar:
            try:
                val = str(obj.avatar)
                if not val or val == 'image/avatar.svg':
                    return None
                url = obj.avatar.url
                request = self.context.get('request')
                if request and url.startswith('/'):
                    return request.build_absolute_uri(url)
                return url
            except Exception:
                val = str(obj.avatar)
                if val and val != 'image/avatar.svg':
                    return f"/media/{val}"
        return None

    role_name = serializers.SerializerMethodField(read_only=True)
    role_modules = serializers.SerializerMethodField(read_only=True)
    role_submodules = serializers.SerializerMethodField(read_only=True)

    def get_role_name(self, obj):
        if obj.role:
            return obj.role.name
        if obj.department and obj.department.department:
            return obj.department.department
        return 'Admin'

    def get_role_modules(self, obj):
        role = obj.role
        if not role and obj.department:
            from users.models import Role
            role = Role.objects.filter(name__iexact=obj.department.department).first()
        if not role:
            from users.models import Role
            role = Role.objects.filter(name='Admin').first()
        if role:
            from users.models import RolePermission
            return list(RolePermission.objects.filter(role=role).values_list('module__code', flat=True))
        return []

    def get_role_submodules(self, obj):
        role = obj.role
        if not role and obj.department:
            from users.models import Role
            role = Role.objects.filter(name__iexact=obj.department.department).first()
        if not role:
            from users.models import Role
            role = Role.objects.filter(name='Admin').first()
        if role:
            from users.models import RolePermission
            perms = RolePermission.objects.filter(role=role).prefetch_related('submodules')
            sub_dict = {}
            for p in perms:
                sub_dict[p.module.code] = list(p.submodules.values_list('code', flat=True))
            return sub_dict
        return {}

    role_submodule_details = serializers.SerializerMethodField(read_only=True)

    def get_role_submodule_details(self, obj):
        role = obj.role
        if not role and obj.department:
            from users.models import Role
            role = Role.objects.filter(name__iexact=obj.department.department).first()
        if not role:
            from users.models import Role
            role = Role.objects.filter(name='Admin').first()
        if role:
            from users.models import RolePermission
            perms = RolePermission.objects.filter(role=role).prefetch_related('submodules', 'module').order_by('module__order', 'module__id')
            modules_list = []
            for p in perms:
                subs = [
                    {
                        'id': s.id,
                        'name': s.name,
                        'code': s.code,
                        'route': s.route or '',
                        'icon': s.icon or 'fa-circle',
                        'tab_key': s.tab_key or '',
                        'sub_tab': s.sub_tab or '',
                        'sub_sub_tab': s.sub_sub_tab or '',
                        'order': s.order,
                    }
                    for s in p.submodules.filter(is_active=True).order_by('order', 'id')
                ]
                modules_list.append({
                    'id': p.module.id,
                    'code': p.module.code,
                    'name': p.module.name,
                    'icon': p.module.icon,
                    'color': p.module.color,
                    'primary_tab': p.module.primary_tab,
                    'submodules': subs
                })
            return modules_list
        return []

    class Meta:
        model = User
        fields = [
            'id', 'username', 'fullname', 'email', 'status', 'gender',
            'phone_number', 'address', 'dob', 'department', 'department_name',
            'department_modules', 'role', 'role_name', 'role_modules', 'role_submodules',
            'role_submodule_details',
            'active', 'created', 'avatar', 'avatar_url'
        ]
        extra_kwargs = {
            'password': {'write_only': True},
            'avatar': {'required': False, 'allow_null': True}
        }


class PatientCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientCategory
        fields = ['id', 'category']


class SponsorSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.category', read_only=True)
    category = serializers.PrimaryKeyRelatedField(
        queryset=PatientCategory.objects.all(), required=False, allow_null=True
    )
    plans_count = serializers.SerializerMethodField(read_only=True)
    patient_count = serializers.SerializerMethodField(read_only=True)

    def get_plans_count(self, obj):
        try:
            return obj.plans.count()
        except Exception:
            return 0

    def get_patient_count(self, obj):
        try:
            return obj.patientprofile_set.count()
        except Exception:
            return 0

    class Meta:
        model = Sponsor
        fields = [
            'id', 'name', 'code', 'category', 'category_name',
            'plans_count', 'patient_count', 'created_date'
        ]


class PatientPlanSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.category', read_only=True)
    category = serializers.PrimaryKeyRelatedField(
        queryset=PatientCategory.objects.all(), required=False, allow_null=True
    )
    sponsor_name = serializers.CharField(source='sponsor.name', read_only=True)
    sponsor_code = serializers.CharField(source='sponsor.code', read_only=True)
    sponsor = serializers.PrimaryKeyRelatedField(
        queryset=Sponsor.objects.all(), required=False, allow_null=True
    )
    patient_count = serializers.SerializerMethodField(read_only=True)

    def get_patient_count(self, obj):
        try:
            return obj.patientprofile_set.count()
        except Exception:
            return 0

    class Meta:
        model = PatientPlan
        fields = [
            'id', 'plan', 'code', 'sponsor', 'sponsor_name', 'sponsor_code',
            'category', 'category_name', 'patient_count'
        ]


class PatientProfileSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='get_full_name', read_only=True)
    patient_full_name = serializers.CharField(source='get_full_name', read_only=True)
    category_name = serializers.CharField(source='category.category', read_only=True)
    sponsor_name = serializers.CharField(source='get_sponsor_name', read_only=True)
    sponsor_category = serializers.CharField(source='sponsor.category.category', read_only=True, default='')
    plan_name = serializers.CharField(source='plan.plan', read_only=True)
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(source='get_age', read_only=True)
    created_by_name = serializers.CharField(source='created_by.fullname', read_only=True)
    family_name = serializers.CharField(source='family_folder.family_name', read_only=True)
    family_number = serializers.CharField(source='family_folder.family_number', read_only=True)
    family_folder_type = serializers.CharField(source='family_folder.folder_type', read_only=True)

    def validate_email_address(self, value):
        if not value or not str(value).strip():
            return None
        return value

    def create(self, validated_data):
        if not validated_data.get('sponsor') and validated_data.get('plan') and getattr(validated_data['plan'], 'sponsor', None):
            validated_data['sponsor'] = validated_data['plan'].sponsor

        if not validated_data.get('hospital_number'):
            import random
            sponsor = validated_data.get('sponsor')
            rand_num = random.randint(1000, 9999)
            if sponsor and getattr(sponsor, 'code', None) and sponsor.code.strip():
                validated_data['hospital_number'] = f"{sponsor.code.strip().upper()}/ISL-{rand_num}"
            else:
                validated_data['hospital_number'] = f"ISL-{rand_num}"

        return super().create(validated_data)

    class Meta:
        model = PatientProfile
        fields = [
            'id', 'hospital_number', 'surname', 'first_name', 'other_name',
            'patient_name', 'patient_full_name',
            'full_name', 'dob', 'age', 'gender', 'patient_type', 'phone_number',
            'address', 'category', 'category_name', 'sponsor', 'sponsor_name', 'sponsor_category',
            'plan', 'plan_name', 'email_address', 'allergies', 'relationship_to_patient',
            'phone_numbers', 'next_of_kin_name', 'next_of_kin_relationship', 'next_of_kin_phone',
            'insurance_policy_number', 'active', 'deactivated_date', 'deactivated_by', 'packages',
            'family_folder', 'family_name', 'family_number', 'family_folder_type', 'family_member_suffix',
            'created_date', 'created_by', 'created_by_name'
        ]


class FamilyMemberSerializer(serializers.ModelSerializer):
    patient_name = serializers.SerializerMethodField(read_only=True)
    patient_surname = serializers.SerializerMethodField(read_only=True)
    patient_first_name = serializers.SerializerMethodField(read_only=True)
    patient_dob = serializers.SerializerMethodField(read_only=True)
    patient_age = serializers.SerializerMethodField(read_only=True)
    patient_gender = serializers.SerializerMethodField(read_only=True)
    patient_phone = serializers.SerializerMethodField(read_only=True)
    patient_category_name = serializers.SerializerMethodField(read_only=True)
    patient_sponsor_name = serializers.SerializerMethodField(read_only=True)
    patient_plan_name = serializers.SerializerMethodField(read_only=True)
    patient_avatar = serializers.SerializerMethodField(read_only=True)

    def get_patient_name(self, obj):
        return obj.patient.get_full_name() if obj.patient else None

    def get_patient_surname(self, obj):
        return obj.patient.surname if obj.patient else None

    def get_patient_first_name(self, obj):
        return obj.patient.first_name if obj.patient else None

    def get_patient_dob(self, obj):
        return obj.patient.dob if obj.patient else None

    def get_patient_age(self, obj):
        return obj.patient.get_age if obj.patient else None

    def get_patient_gender(self, obj):
        return obj.patient.gender if obj.patient else None

    def get_patient_phone(self, obj):
        return obj.patient.phone_number if obj.patient else None

    def get_patient_category_name(self, obj):
        if obj.patient and obj.patient.category:
            return obj.patient.category.category
        return None

    def get_patient_sponsor_name(self, obj):
        if obj.patient:
            return obj.patient.get_sponsor_name()
        return None

    def get_patient_plan_name(self, obj):
        if obj.patient and obj.patient.plan:
            return obj.patient.plan.plan
        return None

    def get_patient_avatar(self, obj):
        try:
            if obj.patient and obj.patient.avatar and str(obj.patient.avatar) != 'patient-profile/avatar.svg':
                return obj.patient.avatar.url
        except Exception:
            pass
        return None

    class Meta:
        model = FamilyMember
        fields = [
            'id', 'family', 'patient', 'patient_name', 'patient_surname', 'patient_first_name',
            'patient_dob', 'patient_age', 'patient_gender', 'patient_phone', 'patient_category_name',
            'patient_sponsor_name', 'patient_plan_name', 'patient_avatar', 'letter_suffix', 'assigned_hospital_number',
            'original_hospital_number', 'relationship', 'is_principal', 'added_date', 'added_by'
        ]


class FamilyFolderSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.category', read_only=True)
    sponsor_name = serializers.CharField(source='sponsor.name', read_only=True)
    sponsor_code = serializers.CharField(source='sponsor.code', read_only=True)
    principal_patient_name = serializers.SerializerMethodField(read_only=True)
    principal_patient_hospital_number = serializers.SerializerMethodField(read_only=True)
    principal_patient_phone = serializers.SerializerMethodField(read_only=True)
    principal_patient_plan = serializers.SerializerMethodField(read_only=True)
    principal_patient_sponsor = serializers.SerializerMethodField(read_only=True)
    member_count = serializers.IntegerField(read_only=True)
    members = FamilyMemberSerializer(many=True, read_only=True)
    created_by_name = serializers.CharField(source='created_by.fullname', read_only=True)

    def get_principal_patient_name(self, obj):
        return obj.principal_patient.get_full_name() if obj.principal_patient else None

    def get_principal_patient_hospital_number(self, obj):
        return obj.principal_patient.hospital_number if obj.principal_patient else None

    def get_principal_patient_phone(self, obj):
        return obj.principal_patient.phone_number if obj.principal_patient else None

    def get_principal_patient_plan(self, obj):
        if obj.principal_patient and obj.principal_patient.plan:
            return obj.principal_patient.plan.plan
        return None

    def get_principal_patient_sponsor(self, obj):
        if obj.principal_patient:
            return obj.principal_patient.get_sponsor_name()
        return None

    class Meta:
        model = FamilyFolder
        fields = [
            'id', 'family_name', 'family_number', 'category', 'category_name',
            'sponsor', 'sponsor_name', 'sponsor_code', 'folder_type',
            'physical_folder_number', 'storage_location',
            'principal_patient', 'principal_patient_name', 'principal_patient_hospital_number', 'principal_patient_phone',
            'principal_patient_plan', 'principal_patient_sponsor',
            'phone_number', 'address', 'notes', 'member_count', 'members',
            'created_by', 'created_by_name', 'created_date', 'updated_date', 'is_active'
        ]



class VisitPurposeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitPurpose
        fields = ['id', 'purpose', 'price', 'specialist_id']


class NurseWaitingListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    attendant_name = serializers.CharField(source='attendant.fullname', read_only=True)
    category_name = serializers.CharField(source='category.category', read_only=True)
    plan_name = serializers.CharField(source='plan.plan', read_only=True)
    gender = serializers.CharField(source='patient.gender', read_only=True)
    age = serializers.IntegerField(source='patient.get_age', read_only=True)

    class Meta:
        model = NurseWaitingList
        fields = '__all__'


class DoctorWaitingListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)
    category_name = serializers.CharField(source='category.category', read_only=True)
    plan_name = serializers.CharField(source='plan.plan', read_only=True)
    pin_code = serializers.CharField(write_only=True, required=False, allow_null=True, allow_blank=True)
    queue_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)

    class Meta:
        model = DoctorWaitingList
        fields = '__all__'

    def create(self, validated_data):
        validated_data.pop('pin_code', None)
        validated_data.pop('queue_id', None)
        return super().create(validated_data)


class PatientAppointmentSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    patient_phone = serializers.CharField(source='patient.phone_number', read_only=True)
    patient_gender = serializers.CharField(source='patient.gender', read_only=True)
    patient_age = serializers.IntegerField(source='patient.get_age', read_only=True)
    category_name = serializers.CharField(source='patient.category.category', read_only=True)
    provider_name = serializers.CharField(source='provider.fullname', read_only=True)
    is_today = serializers.BooleanField(read_only=True)
    is_upcoming = serializers.BooleanField(read_only=True)
    is_expired = serializers.BooleanField(read_only=True)
    is_completed = serializers.BooleanField(read_only=True)
    is_cancelled = serializers.BooleanField(read_only=True)
    consultation_paid = serializers.SerializerMethodField(read_only=True)
    consultation_invoiced = serializers.SerializerMethodField(read_only=True)
    has_draft = serializers.SerializerMethodField(read_only=True)
    today_vitals = serializers.SerializerMethodField(read_only=True)
    has_vitals = serializers.SerializerMethodField(read_only=True)
    has_action_taken = serializers.SerializerMethodField(read_only=True)
    can_cancel = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PatientAppointment
        fields = [
            'id', 'patient', 'patient_name', 'hospital_number', 'patient_phone',
            'patient_gender', 'patient_age', 'category_name',
            'provider', 'provider_name', 'clinician', 'purpose', 'visit_type',
            'arrival_date', 'arrival_time', 'comment', 'anc_weeks', 'created_date',
            'completed', 'is_today', 'is_upcoming', 'is_expired', 'is_completed', 'is_cancelled',
            'consultation_paid', 'consultation_invoiced', 'has_draft',
            'today_vitals', 'has_vitals', 'has_action_taken', 'can_cancel'
        ]

    def get_today_vitals(self, obj):
        if not obj.patient_id:
            return None
        from queue_operations.models import DoctorWaitingList
        from django.utils import timezone
        today = timezone.localdate()
        target_date = obj.arrival_date or today

        vitals = DoctorWaitingList.objects.filter(
            patient_id=obj.patient_id,
            created_date__date=target_date
        ).select_related('staff').order_by('-created_date').first()

        if not vitals and target_date != today:
            vitals = DoctorWaitingList.objects.filter(
                patient_id=obj.patient_id,
                created_date__date=today
            ).select_related('staff').order_by('-created_date').first()

        if not vitals:
            return None

        staff_name = None
        if vitals.staff:
            staff_name = vitals.staff.fullname or vitals.staff.get_full_name() or vitals.staff.username
        elif vitals.completed_by:
            staff_name = vitals.completed_by

        created_time_str = None
        created_date_str = None
        if vitals.created_date:
            local_dt = timezone.localtime(vitals.created_date)
            created_time_str = local_dt.strftime('%H:%M')
            created_date_str = local_dt.strftime('%b %d, %Y %H:%M')

        return {
            'id': vitals.id,
            'temperature': vitals.temperature,
            'bp': vitals.bp,
            'pulse': vitals.pulse,
            'respiratory_rate': vitals.respiratory_rate,
            'sp_02': vitals.sp_02,
            'weight': vitals.weight,
            'height': vitals.height,
            'unit': vitals.unit or 'cm',
            'bmi': vitals.bmi,
            'blood_glucose': vitals.blood_glucose,
            'urine_ph': vitals.urine_ph,
            'urine_protein': vitals.urine_protein,
            'urine_glucose': vitals.urine_glucose,
            'comment': vitals.comment,
            'staff_name': staff_name,
            'time': created_time_str,
            'datetime': created_date_str,
        }

    def get_has_vitals(self, obj):
        return bool(self.get_today_vitals(obj))

    def get_has_action_taken(self, obj):
        return obj.has_actions_taken()

    def get_can_cancel(self, obj):
        return obj.can_cancel

    def get_consultation_paid(self, obj):
        if not obj.patient_id:
            return False
        from Billings.models import Invoice
        from django.utils import timezone
        today = timezone.localdate()
        target_date = obj.arrival_date or today
        return Invoice.objects.filter(
            patient_id=obj.patient_id,
            product__icontains='Consultation',
            created_date__date=target_date,
            completed=1
        ).exists()

    def get_consultation_invoiced(self, obj):
        if not obj.patient_id:
            return False
        from Billings.models import Invoice
        from django.utils import timezone
        today = timezone.localdate()
        target_date = obj.arrival_date or today
        return Invoice.objects.filter(
            patient_id=obj.patient_id,
            product__icontains='Consultation',
            created_date__date=target_date
        ).exists()

    def get_has_draft(self, obj):
        if not obj.patient_id:
            return False
        return ConsultationDraft.objects.filter(patient_id=obj.patient_id).exists()



# Billings Serializers
class InvoiceSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.SerializerMethodField()
    sponsor = serializers.SerializerMethodField()
    plan = serializers.SerializerMethodField()
    category_name = serializers.SerializerMethodField()
    is_hmo = serializers.SerializerMethodField()
    policy_number = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    gender = serializers.SerializerMethodField()
    age = serializers.SerializerMethodField()
    address = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = '__all__'

    def get_staff_name(self, obj):
        if obj.staff:
            return (getattr(obj.staff, 'fullname', None) or '').strip() or obj.staff.get_full_name() or obj.staff.username or ''
        return ''

    def get_sponsor(self, obj):
        if obj.invoice_number and str(obj.invoice_number).startswith('INV-'):
            pay_opt = (obj.payment_option or '').strip().lower()
            if pay_opt != 'claim':
                return 'PAY FROM PURSE / CASH'
        if obj.patient and obj.patient.sponsor:
            return obj.patient.sponsor.name
        return None

    def get_plan(self, obj):
        if obj.invoice_number and str(obj.invoice_number).startswith('INV-'):
            pay_opt = (obj.payment_option or '').strip().lower()
            if pay_opt != 'claim':
                return 'OUT-OF-POCKET TARIFF'
        if obj.patient and obj.patient.plan:
            return obj.patient.plan.plan
        return None

    def get_category_name(self, obj):
        if obj.invoice_number and str(obj.invoice_number).startswith('INV-'):
            pay_opt = (obj.payment_option or '').strip().lower()
            if pay_opt != 'claim':
                return 'Private'
        if obj.category:
            return getattr(obj.category, 'category', str(obj.category))
        if obj.patient and obj.patient.category:
            return obj.patient.category.category
        return None

    def get_is_hmo(self, obj):
        if obj.invoice_number and str(obj.invoice_number).startswith('INV-'):
            return False
        pay_opt = (obj.payment_option or '').strip().lower()
        if pay_opt and pay_opt not in ['claim', 'hmo']:
            return False

        if obj.invoice_number and str(obj.invoice_number).startswith('CLM-'):
            return True
        if pay_opt in ['claim', 'hmo']:
            return True

        cat = ''
        if obj.category:
            cat = getattr(obj.category, 'category', str(obj.category)).lower()
        elif obj.patient and obj.patient.category:
            cat = (obj.patient.category.category or '').lower()
        if 'hmo' in cat:
            return True
        if obj.patient and obj.patient.sponsor:
            s_name = (obj.patient.sponsor.name or '').lower()
            if any(w in s_name for w in ['hmo', 'insurance', 'nhis', 'managed care', 'aiico', 'hygeia', 'reliance', 'axa', 'leadway']):
                return True
        return False

    def get_policy_number(self, obj):
        if obj.patient:
            return obj.patient.insurance_policy_number or ''
        return ''

    def get_phone_number(self, obj):
        if obj.patient:
            return obj.patient.phone_number or ''
        return ''

    def get_gender(self, obj):
        if obj.patient:
            return obj.patient.gender or ''
        return ''

    def get_age(self, obj):
        if obj.patient:
            return obj.patient.get_age if hasattr(obj.patient, 'get_age') and obj.patient.get_age is not None else ''
        return ''

    def get_address(self, obj):
        if obj.patient:
            return obj.patient.address or ''
        return ''


class ReceiptSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.SerializerMethodField()
    sponsor = serializers.SerializerMethodField()

    def get_staff_name(self, obj):
        if obj.staff:
            return (getattr(obj.staff, 'fullname', None) or '').strip() or obj.staff.get_full_name() or obj.staff.username or ''
        return ''

    def get_sponsor(self, obj):
        if obj.patient and obj.patient.sponsor:
            return obj.patient.sponsor.name
        return 'Self-Pay / Cash'

    class Meta:
        model = Receipt
        fields = '__all__'


class DepositSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.SerializerMethodField()

    def get_staff_name(self, obj):
        if obj.staff:
            return (getattr(obj.staff, 'fullname', None) or '').strip() or obj.staff.get_full_name() or obj.staff.username or ''
        return ''

    class Meta:
        model = Deposit
        fields = '__all__'


class RefundSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.SerializerMethodField()

    def get_staff_name(self, obj):
        if obj.staff:
            return (getattr(obj.staff, 'fullname', None) or '').strip() or obj.staff.get_full_name() or obj.staff.username or ''
        return ''

    class Meta:
        model = Refund
        fields = '__all__'


# IPD Serializers
class WardSerializer(serializers.ModelSerializer):
    available_beds = serializers.SerializerMethodField()

    class Meta:
        model = Ward
        fields = ['id', 'ward_name', 'price', 'available_beds']

    def get_available_beds(self, obj):
        return obj.beds.filter(is_occupied=False).count()


class BedSerializer(serializers.ModelSerializer):
    ward_name = serializers.CharField(source='ward.ward_name', read_only=True)

    class Meta:
        model = Bed
        fields = ['id', 'ward', 'ward_name', 'bed_name', 'bed_status', 'is_occupied']


class AdmissionTableSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    doctor_name = serializers.CharField(source='doctor_admitted.fullname', read_only=True)

    class Meta:
        model = AdmissionTable
        fields = '__all__'


class BedAllocationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    ward_name = serializers.CharField(source='ward.ward_name', read_only=True)
    bed_name = serializers.CharField(source='bed.bed_name', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = BedAllocation
        fields = '__all__'


# ANC Serializers
class ANCRegistrationSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    created_by_name = serializers.CharField(source='created_by.fullname', read_only=True)

    class Meta:
        model = ANCRegistration
        fields = '__all__'


# Pharmacy Serializers
class OpdDrugsSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = OpdDrugs
        fields = [
            'id', 'product_name', 'product_id', 'description', 'price',
            'stock', 'minimum_UoM', 'unit', 'low_stock_threshold', 'status',
            'activation_status', 'expiry_date', 'staff', 'staff_name', 'created_date'
        ]


# Radiology & Laboratory Serializers
class RadiologyLabSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    category_name = serializers.CharField(source='category.category', read_only=True)
    plan_name = serializers.CharField(source='plan.plan', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = RadiologyLab
        fields = '__all__'


# Inventory Serializers
from inventory.models import Product as InventoryProduct, Transaction as InventoryTransaction, ProductRequests as InventoryProductRequests

class InventoryProductSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = InventoryProduct
        fields = '__all__'


class InventoryTransactionSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = InventoryTransaction
        fields = '__all__'


class InventoryProductRequestSerializer(serializers.ModelSerializer):
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = InventoryProductRequests
        fields = '__all__'


class PatientEncounterSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source='provider.fullname', read_only=True)
    patient_name = serializers.SerializerMethodField(read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)

    def get_patient_name(self, obj):
        if obj.patient:
            return f"{obj.patient.surname} {obj.patient.first_name}"
        return "Unknown"

    class Meta:
        model = PatientEncounter
        fields = [
            'id', 'patient', 'provider', 'provider_name', 'patient_name',
            'hospital_number', 'chief_complaint', 'history_of_present_illness',
            'diagnosis', 'comments_on_diagnosis', 'anc_weeks', 'created_at', 'updated_at'
        ]
        read_only_fields = ['provider', 'created_at', 'updated_at']


class PatientDiagnosisSerializer(serializers.ModelSerializer):
    name = serializers.CharField(source='description', read_only=True)

    class Meta:
        model = PatientDiagnosis
        fields = ['id', 'description', 'name', 'category', 'icd10_code', 'icd11_code', 'is_active']


class PresentingComplaintSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = PresentingComplaint
        fields = ['id', 'name', 'category', 'category_display', 'is_active', 'created_at']


class WrittenPrescriptionSerializer(serializers.ModelSerializer):
    provider_name = serializers.CharField(source='provider.fullname', read_only=True)
    patient_name = serializers.SerializerMethodField(read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    dispensed_by_name = serializers.CharField(source='dispensed_by.fullname', read_only=True)

    def get_patient_name(self, obj):
        if obj.patient:
            return f"{obj.patient.surname} {obj.patient.first_name}"
        return "Unknown"

    class Meta:
        model = WrittenPrescriptions
        fields = [
            'id', 'patient', 'patient_name', 'hospital_number', 'provider', 'provider_name',
            'item', 'instruction', 'quantity', 'dosage_form', 'route', 'strength',
            'dose_qty', 'dose_unit', 'frequency', 'duration', 'duration_unit',
            'dispense_unit', 'dispense_quantity', 'dispense_detail', 'comment',
            'start_date', 'status', 'dispensed_at', 'dispensed_by', 'dispensed_by_name',
            'created_date'
        ]
        read_only_fields = ['provider', 'created_date', 'dispensed_at', 'dispensed_by']


class ConsultationDraftSerializer(serializers.ModelSerializer):
    doctor_name = serializers.CharField(source='doctor.fullname', read_only=True)
    patient_name = serializers.SerializerMethodField(read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)

    def get_patient_name(self, obj):
        if obj.patient:
            return f"{obj.patient.surname} {obj.patient.first_name}"
        return "Unknown"

    class Meta:
        model = ConsultationDraft
        fields = [
            'id', 'patient', 'doctor', 'doctor_name', 'patient_name', 'hospital_number',
            'appointment', 'draft_data', 'created_at', 'updated_at'
        ]
        read_only_fields = ['doctor', 'created_at', 'updated_at']


