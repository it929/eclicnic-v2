from rest_framework import serializers
from users.models import User, Category
from patients.models import PatientProfile, PatientCategory, PatientPlan, PatientAppointment, Sponsor
from queue_operations.models import VisitPurpose, NurseWaitingList, PatientBackgroundHealth, DoctorWaitingList, PatientEncounter
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

    class Meta:
        model = User
        fields = [
            'id', 'username', 'fullname', 'email', 'status', 'gender',
            'phone_number', 'address', 'dob', 'department', 'department_name',
            'department_modules', 'active', 'created'
        ]
        extra_kwargs = {'password': {'write_only': True}}


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
    category_name = serializers.CharField(source='category.category', read_only=True)
    sponsor_name = serializers.CharField(source='get_sponsor_name', read_only=True)
    plan_name = serializers.CharField(source='plan.plan', read_only=True)
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(source='get_age', read_only=True)
    created_by_name = serializers.CharField(source='created_by.fullname', read_only=True)

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
            'full_name', 'dob', 'age', 'gender', 'patient_type', 'phone_number',
            'address', 'category', 'category_name', 'sponsor', 'sponsor_name',
            'plan', 'plan_name', 'email_address', 'allergies', 'relationship_to_patient',
            'phone_numbers', 'insurance_policy_number', 'active', 'packages',
            'created_date', 'created_by', 'created_by_name'
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
    today_vitals = serializers.SerializerMethodField(read_only=True)
    has_vitals = serializers.SerializerMethodField(read_only=True)

    class Meta:
        model = PatientAppointment
        fields = [
            'id', 'patient', 'patient_name', 'hospital_number', 'patient_phone',
            'patient_gender', 'patient_age', 'category_name',
            'provider', 'provider_name', 'clinician', 'purpose', 'visit_type',
            'arrival_date', 'arrival_time', 'comment', 'anc_weeks', 'created_date',
            'completed', 'is_today', 'is_upcoming', 'is_expired', 'is_completed', 'is_cancelled',
            'today_vitals', 'has_vitals'
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


# Billings Serializers
class InvoiceSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = Invoice
        fields = '__all__'


class ReceiptSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = Receipt
        fields = '__all__'


class DepositSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

    class Meta:
        model = Deposit
        fields = '__all__'


class RefundSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    staff_name = serializers.CharField(source='staff.fullname', read_only=True)

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
