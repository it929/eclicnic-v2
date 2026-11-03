from rest_framework import serializers
from decimal import Decimal
from radio_lab.models import (
    LabParameter,
    LabInvestigation,
    LabInvestigationParameter,
    LabParameterReferenceRange,
    LabOrderResultItem,
    RadiologyLab,
    RadiologyProcedure
)

class LabParameterReferenceRangeSerializer(serializers.ModelSerializer):
    demographic_group_display = serializers.CharField(source='get_demographic_group_display', read_only=True)

    class Meta:
        model = LabParameterReferenceRange
        fields = [
            'id',
            'parameter',
            'demographic_group',
            'demographic_group_display',
            'common_value',
            'low_boundary',
            'high_boundary',
            'low_critical',
            'high_critical',
            'high_level',
            'low_level'
        ]


class LabParameterSerializer(serializers.ModelSerializer):
    reference_ranges = LabParameterReferenceRangeSerializer(many=True, read_only=True)
    investigation_count = serializers.SerializerMethodField()

    class Meta:
        model = LabParameter
        fields = [
            'id',
            'code',
            'name',
            'category',
            'measurement_unit',
            'result_type',
            'normal_result_description',
            'can_be_done_alone',
            'base_price',
            'specimen',
            'sample_bottle_color',
            'sample_quantity',
            'display_order',
            'low_interpretation',
            'high_interpretation',
            'low_comments',
            'high_comments',
            'general_comments',
            'is_active',
            'created_date',
            'reference_ranges',
            'investigation_count'
        ]

    def get_investigation_count(self, obj):
        return obj.investigation_mappings.count()


class LabInvestigationParameterSerializer(serializers.ModelSerializer):
    parameter_id = serializers.PrimaryKeyRelatedField(
        queryset=LabParameter.objects.all(), source='parameter', write_only=True
    )
    parameter = LabParameterSerializer(read_only=True)

    class Meta:
        model = LabInvestigationParameter
        fields = [
            'id',
            'investigation',
            'parameter',
            'parameter_id',
            'order',
            'is_required'
        ]


class LabInvestigationSerializer(serializers.ModelSerializer):
    parameter_mappings = LabInvestigationParameterSerializer(many=True, read_only=True)
    accumulated_price = serializers.SerializerMethodField()
    effective_price = serializers.SerializerMethodField()
    parameters_summary = serializers.SerializerMethodField()
    parameter_count = serializers.SerializerMethodField()
    parameter_ids = serializers.ListField(
        child=serializers.IntegerField(), write_only=True, required=False
    )

    class Meta:
        model = LabInvestigation
        fields = [
            'id',
            'code',
            'name',
            'category',
            'specimen',
            'sample_bottle_color',
            'sample_quantity',
            'base_price',
            'use_accumulated_price',
            'is_panel',
            'is_active',
            'created_date',
            'parameter_mappings',
            'accumulated_price',
            'effective_price',
            'parameters_summary',
            'parameter_count',
            'parameter_ids'
        ]

    def get_accumulated_price(self, obj):
        return float(obj.get_accumulated_price())

    def get_effective_price(self, obj):
        return float(obj.effective_price())

    def get_parameters_summary(self, obj):
        mappings = obj.parameter_mappings.select_related('parameter').all()
        return [m.parameter.name for m in mappings]

    def get_parameter_count(self, obj):
        return obj.parameter_mappings.count()

    def create(self, validated_data):
        parameter_ids = validated_data.pop('parameter_ids', None)
        investigation = super().create(validated_data)
        if parameter_ids is not None:
            self._sync_parameters(investigation, parameter_ids)
        return investigation

    def update(self, instance, validated_data):
        parameter_ids = validated_data.pop('parameter_ids', None)
        investigation = super().update(instance, validated_data)
        if parameter_ids is not None:
            self._sync_parameters(investigation, parameter_ids)
        return investigation

    def _sync_parameters(self, investigation, parameter_ids):
        # Keep existing order or update mappings
        LabInvestigationParameter.objects.filter(investigation=investigation).delete()
        for idx, pid in enumerate(parameter_ids):
            try:
                param = LabParameter.objects.get(id=pid)
                LabInvestigationParameter.objects.create(
                    investigation=investigation,
                    parameter=param,
                    order=idx + 1
                )
            except LabParameter.DoesNotExist:
                continue


class LabOrderResultItemSerializer(serializers.ModelSerializer):
    flag_display = serializers.CharField(source='get_flag_display', read_only=True)
    result_type = serializers.SerializerMethodField()
    normal_result_description = serializers.SerializerMethodField()
    low_boundary = serializers.SerializerMethodField()
    high_boundary = serializers.SerializerMethodField()
    low_critical = serializers.SerializerMethodField()
    high_critical = serializers.SerializerMethodField()

    class Meta:
        model = LabOrderResultItem
        fields = [
            'id',
            'order',
            'parameter',
            'investigation',
            'parameter_name',
            'result_value',
            'unit',
            'result_type',
            'normal_result_description',
            'low_boundary',
            'high_boundary',
            'low_critical',
            'high_critical',
            'reference_range_display',
            'flag',
            'flag_display',
            'display_order',
            'entered_by',
            'entered_by_name',
            'entered_at',
            'created_date'
        ]

    def get_result_type(self, obj):
        if obj.parameter and obj.parameter.result_type:
            return obj.parameter.result_type
        val = str(obj.result_value or '').strip().lower()
        if val in ['positive', 'negative', 'reactive', 'non-reactive']:
            return 'qualitative'
        return 'numeric'

    def get_normal_result_description(self, obj):
        return obj.parameter.normal_result_description if obj.parameter else ''

    def _get_ref(self, obj):
        if not hasattr(obj, '_cached_ref'):
            ref = None
            if obj.parameter and obj.order and obj.order.patient:
                patient = obj.order.patient
                dob = getattr(patient, 'dob', None) or getattr(patient, 'date_of_birth', None)
                gender = (patient.gender or '').lower() if patient else ''
                from datetime import date
                demo_group = 'general'
                if dob:
                    days = (date.today() - dob).days
                    if days <= 3: demo_group = 'neonate_0_3d'
                    elif days <= 14: demo_group = 'neonate_4_14d'
                    elif days <= 90: demo_group = 'infant_15d_3m'
                    elif days <= 180: demo_group = 'infant_3m_6m'
                    elif days <= 365: demo_group = 'infant_6m_1y'
                    elif days <= 730: demo_group = 'child_1_2y'
                    elif days <= 1825: demo_group = 'child_2_5y'
                    elif days <= 4380: demo_group = 'child_5_12y'
                    else: demo_group = 'adult_female' if gender in ['female', 'f'] else 'adult_male'
                else:
                    demo_group = 'adult_female' if gender in ['female', 'f'] else ('adult_male' if gender in ['male', 'm'] else 'general')

                ref = obj.parameter.reference_ranges.filter(demographic_group=demo_group).first()
                if not ref:
                    ref = obj.parameter.reference_ranges.filter(demographic_group='general').first()
            obj._cached_ref = ref
        return obj._cached_ref

    def get_low_boundary(self, obj):
        ref = self._get_ref(obj)
        return float(ref.low_boundary) if ref and ref.low_boundary is not None else None

    def get_high_boundary(self, obj):
        ref = self._get_ref(obj)
        return float(ref.high_boundary) if ref and ref.high_boundary is not None else None

    def get_low_critical(self, obj):
        ref = self._get_ref(obj)
        return float(ref.low_critical) if ref and ref.low_critical is not None else None

    def get_high_critical(self, obj):
        ref = self._get_ref(obj)
        return float(ref.high_critical) if ref and ref.high_critical is not None else None



class RadiologyProcedureSerializer(serializers.ModelSerializer):
    category_display = serializers.CharField(source='get_category_display', read_only=True)

    class Meta:
        model = RadiologyProcedure
        fields = [
            'id',
            'code',
            'name',
            'category',
            'category_display',
            'body_part',
            'base_price',
            'preparation_instructions',
            'estimated_duration_minutes',
            'is_active',
            'created_date',
            'updated_date',
        ]
