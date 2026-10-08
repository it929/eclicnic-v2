from rest_framework import serializers
from users.models import User, Category
from patients.models import PatientProfile, PatientCategory, PatientPlan, PatientAppointment
from queue_operations.models import VisitPurpose, NurseWaitingList, PatientBackgroundHealth
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
            'phone_number', 'address', 'department', 'department_name',
            'department_modules', 'active', 'created'
        ]
        extra_kwargs = {'password': {'write_only': True}}


class PatientCategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = PatientCategory
        fields = ['id', 'category']


class PatientPlanSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.category', read_only=True)

    class Meta:
        model = PatientPlan
        fields = ['id', 'plan', 'code', 'category', 'category_name']


class PatientProfileSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.category', read_only=True)
    plan_name = serializers.CharField(source='plan.plan', read_only=True)
    full_name = serializers.CharField(read_only=True)
    age = serializers.IntegerField(source='get_age', read_only=True)
    created_by_name = serializers.CharField(source='created_by.fullname', read_only=True)

    def validate_email_address(self, value):
        if not value or not str(value).strip():
            return None
        return value

    def create(self, validated_data):
        if not validated_data.get('hospital_number'):
            import random
            validated_data['hospital_number'] = str(random.randint(1000, 9999))
        return super().create(validated_data)

    class Meta:
        model = PatientProfile
        fields = [
            'id', 'hospital_number', 'surname', 'first_name', 'other_name',
            'full_name', 'dob', 'age', 'gender', 'patient_type', 'phone_number',
            'address', 'category', 'category_name', 'plan', 'plan_name',
            'email_address', 'allergies', 'relationship_to_patient',
            'insurance_policy_number', 'active', 'packages', 'created_date',
            'created_by', 'created_by_name'
        ]


class VisitPurposeSerializer(serializers.ModelSerializer):
    class Meta:
        model = VisitPurpose
        fields = ['id', 'purpose', 'price', 'specialist_id']


class NurseWaitingListSerializer(serializers.ModelSerializer):
    patient_name = serializers.CharField(source='patient.get_full_name', read_only=True)
    hospital_number = serializers.CharField(source='patient.hospital_number', read_only=True)
    attendant_name = serializers.CharField(source='attendant.fullname', read_only=True)

    class Meta:
        model = NurseWaitingList
        fields = '__all__'


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
