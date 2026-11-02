import datetime
from decimal import Decimal
from django.db import transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework import viewsets, permissions, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView

from radio_lab.models import (
    LabParameter,
    LabInvestigation,
    LabInvestigationParameter,
    LabParameterReferenceRange,
    LabOrderResultItem,
    RadiologyLab,
    LabResult
)
from .lab_serializers import (
    LabParameterSerializer,
    LabInvestigationSerializer,
    LabInvestigationParameterSerializer,
    LabParameterReferenceRangeSerializer,
    LabOrderResultItemSerializer
)


def get_patient_demographic_group(patient):
    """
    Given a PatientProfile instance, compute age in days/months/years
    and return the matching demographic_group key.
    """
    dob = getattr(patient, 'dob', None) or getattr(patient, 'date_of_birth', None) if patient else None
    if not patient or not dob:
        gender = getattr(patient, 'gender', '').lower() if patient else ''
        if gender in ['female', 'f']:
            return 'adult_female'
        elif gender in ['male', 'm']:
            return 'adult_male'
        return 'general'
    today = datetime.date.today()
    days = (today - dob).days

    if days < 0:
        return 'general'
    if days <= 3:
        return 'neonate_0_3d'
    if days <= 14:
        return 'neonate_4_14d'
    if days <= 90:
        return 'infant_15d_3m'
    if days <= 180:
        return 'infant_3m_6m'
    if days <= 365:
        return 'infant_6m_1y'
    if days <= 730:
        return 'child_1_2y'
    if days <= 1825:
        return 'child_2_5y'
    if days <= 4380:  # ~12 years
        return 'child_5_12y'

    gender = (patient.gender or '').lower()
    if gender in ['female', 'f']:
        return 'adult_female'
    elif gender in ['male', 'm']:
        return 'adult_male'
    return 'general'


def evaluate_result_flag(value_str, ref_range):
    """
    Given a numeric result string and a LabParameterReferenceRange,
    determine if it's NORMAL, LOW, HIGH, CRITICAL_LOW, or CRITICAL_HIGH.
    """
    if not value_str or not ref_range:
        return ''
    try:
        val = Decimal(str(value_str).strip())
    except Exception:
        return ''

    # Critical thresholds take precedence
    if ref_range.low_critical is not None and val < ref_range.low_critical:
        return 'CRITICAL_LOW'
    if ref_range.high_critical is not None and val > ref_range.high_critical:
        return 'CRITICAL_HIGH'

    # Normal boundary checks
    if ref_range.low_boundary is not None and val < ref_range.low_boundary:
        return 'LOW'
    if ref_range.high_boundary is not None and val > ref_range.high_boundary:
        return 'HIGH'

    if ref_range.low_boundary is not None or ref_range.high_boundary is not None:
        return 'NORMAL'

    return ''


class LabParameterViewSet(viewsets.ModelViewSet):
    """CRUD viewset for individual lab test parameters."""
    queryset = LabParameter.objects.all().order_by('category', 'display_order', 'name')
    serializer_class = LabParameterSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code', 'category', 'specimen']

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__iexact=category)
        can_alone = self.request.query_params.get('can_be_done_alone')
        if can_alone is not None:
            qs = qs.filter(can_be_done_alone=(can_alone.lower() in ['true', '1']))
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() in ['true', '1']))
        return qs

    @action(detail=True, methods=['get', 'post'])
    def reference_ranges(self, request, pk=None):
        """
        GET: Returns all 11 demographic groups (with existing data or blank templates).
        POST: Bulk updates or creates reference ranges for this parameter.
        """
        parameter = self.get_object()

        if request.method == 'GET':
            existing = {r.demographic_group: r for r in parameter.reference_ranges.all()}
            choices = LabParameterReferenceRange.DEMOGRAPHIC_CHOICES
            result = []
            for group_code, group_label in choices:
                obj = existing.get(group_code)
                if obj:
                    result.append(LabParameterReferenceRangeSerializer(obj).data)
                else:
                    result.append({
                        'id': None,
                        'parameter': parameter.id,
                        'demographic_group': group_code,
                        'demographic_group_display': group_label,
                        'common_value': '',
                        'low_boundary': None,
                        'high_boundary': None,
                        'low_critical': None,
                        'high_critical': None,
                        'high_level': '',
                        'low_level': ''
                    })
            return Response(result)

        elif request.method == 'POST':
            ranges_data = request.data
            if not isinstance(ranges_data, list):
                ranges_data = [ranges_data]

            with transaction.atomic():
                saved_ranges = []
                for item in ranges_data:
                    group = item.get('demographic_group')
                    if not group:
                        continue
                    obj, _ = LabParameterReferenceRange.objects.get_or_create(
                        parameter=parameter,
                        demographic_group=group
                    )
                    obj.common_value = item.get('common_value', '') or ''
                    obj.low_boundary = item.get('low_boundary') if item.get('low_boundary') not in ['', None] else None
                    obj.high_boundary = item.get('high_boundary') if item.get('high_boundary') not in ['', None] else None
                    obj.low_critical = item.get('low_critical') if item.get('low_critical') not in ['', None] else None
                    obj.high_critical = item.get('high_critical') if item.get('high_critical') not in ['', None] else None
                    obj.high_level = item.get('high_level', '') or ''
                    obj.low_level = item.get('low_level', '') or ''
                    obj.save()
                    saved_ranges.append(LabParameterReferenceRangeSerializer(obj).data)

            return Response(saved_ranges, status=status.HTTP_200_OK)


class LabInvestigationViewSet(viewsets.ModelViewSet):
    """CRUD viewset for investigation panels (e.g. FBC, LFT, Lipid Profile)."""
    queryset = LabInvestigation.objects.all().prefetch_related('parameter_mappings__parameter').order_by('category', 'name')
    serializer_class = LabInvestigationSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code', 'category', 'specimen']

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__iexact=category)
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() in ['true', '1']))
        return qs

    @action(detail=True, methods=['get'])
    def parameters(self, request, pk=None):
        """Return ordered list of parameters with full details and reference ranges."""
        investigation = self.get_object()
        mappings = investigation.parameter_mappings.select_related('parameter').all()
        data = []
        for m in mappings:
            p_data = LabParameterSerializer(m.parameter).data
            data.append({
                'mapping_id': m.id,
                'order': m.order,
                'is_required': m.is_required,
                'parameter': p_data
            })
        return Response(data)


class LabTestSearchView(APIView):
    """
    Unified search endpoint returning both Investigations (panels) and Standalone Parameters.
    Resolves plan-specific tariff rates if patient, sponsor, or plan is provided.
    Used by Doctor Consultation CPOE and Lab Reception.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        category = request.query_params.get('category', '').strip()
        patient_id = request.query_params.get('patient')
        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')

        # Resolve target sponsor & plan if provided
        target_sponsor = None
        target_plan = None
        if patient_id:
            try:
                from patients.models import PatientProfile
                pat = PatientProfile.objects.select_related('sponsor', 'plan').get(id=patient_id)
                target_sponsor = pat.sponsor
                target_plan = pat.plan
            except Exception:
                pass

        if not target_sponsor and sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'self', 'cash'):
            try:
                from patients.models import Sponsor
                target_sponsor = Sponsor.objects.filter(id=sponsor_id).first()
            except Exception:
                pass

        if not target_plan and plan_id and str(plan_id).lower() not in ('all', 'general', 'self', 'cash'):
            try:
                from patients.models import PatientPlan
                target_plan = PatientPlan.objects.filter(id=plan_id).first()
            except Exception:
                pass

        # Build tariff rate lookup from RadioLabInventory
        from radio_lab.models import RadioLabInventory
        tariff_lookup = {}
        tariff_metadata = {}

        if target_sponsor or target_plan:
            t_qs = RadioLabInventory.objects.filter(type='L').select_related('sponsor', 'plan')
            if target_sponsor and target_plan:
                t_qs = t_qs.filter(
                    Q(sponsor=target_sponsor, plan=target_plan) |
                    Q(plan=target_plan) |
                    (Q(sponsor=target_sponsor) & Q(plan__isnull=True))
                )
            elif target_plan:
                t_qs = t_qs.filter(plan=target_plan)
            elif target_sponsor:
                t_qs = t_qs.filter(Q(sponsor=target_sponsor) | Q(plan__sponsor=target_sponsor))

            # Store best rate: prioritize exact plan -> sponsor -> general
            for ptr in t_qs:
                t_type = ptr.test_type or 'investigation'
                r_val = float(ptr.rate)
                p_code = (ptr.item_id or '').strip().upper()
                p_name = ptr.item.strip().lower()
                meta = {
                    'rate': r_val,
                    'plan_name': ptr.plan.plan if ptr.plan else '',
                    'sponsor_name': ptr.sponsor.name if ptr.sponsor else (ptr.plan.sponsor.name if ptr.plan and ptr.plan.sponsor else ''),
                    'is_plan_tariff': True,
                    'parameter_ids': ptr.parameter_ids if hasattr(ptr, 'parameter_ids') else [],
                }
                if p_code:
                    tariff_lookup[(p_code, t_type)] = r_val
                    tariff_metadata[(p_code, t_type)] = meta
                if p_name:
                    tariff_lookup[(p_name, t_type)] = r_val
                    tariff_metadata[(p_name, t_type)] = meta

        # 1. Investigations (Panels)
        inv_qs = LabInvestigation.objects.filter(is_active=True).prefetch_related('parameter_mappings__parameter')
        if query:
            inv_qs = inv_qs.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(category__icontains=query))
        if category:
            inv_qs = inv_qs.filter(category__iexact=category)

        # 2. Standalone Parameters
        param_qs = LabParameter.objects.filter(is_active=True, can_be_done_alone=True)
        if query:
            param_qs = param_qs.filter(Q(name__icontains=query) | Q(code__icontains=query) | Q(category__icontains=query))
        if category:
            param_qs = param_qs.filter(category__iexact=category)

        results = []

        # Format investigations
        for inv in inv_qs[:40]:
            inv_code = (inv.code or '').strip().upper()
            inv_name = inv.name.strip().lower()
            t_rate = tariff_lookup.get((inv_code, 'investigation')) or tariff_lookup.get((inv_name, 'investigation'))
            t_meta = tariff_metadata.get((inv_code, 'investigation')) or tariff_metadata.get((inv_name, 'investigation')) or {}

            param_names = [m.parameter.name for m in inv.parameter_mappings.all()]
            eff_price = t_rate if t_rate is not None else float(inv.effective_price())

            results.append({
                'id': f'inv_{inv.id}',
                'real_id': inv.id,
                'type': 'investigation',
                'badge': 'PANEL',
                'name': inv.name,
                'code': inv.code,
                'category': inv.category or 'General Lab',
                'specimen': inv.specimen,
                'sample_bottle_color': inv.sample_bottle_color,
                'sample_quantity': inv.sample_quantity,
                'price': eff_price,
                'rate': eff_price,
                'plan_name': t_meta.get('plan_name', ''),
                'sponsor_name': t_meta.get('sponsor_name', ''),
                'is_plan_tariff': t_meta.get('is_plan_tariff', False),
                'use_accumulated_price': inv.use_accumulated_price,
                'accumulated_price': float(inv.get_accumulated_price()),
                'parameter_count': len(param_names),
                'parameters_summary': param_names,
                'description': f"Panel ({len(param_names)} tests): " + ", ".join(param_names[:5]) + ("..." if len(param_names) > 5 else "")
            })

        # Format parameters
        for param in param_qs[:40]:
            p_code = (param.code or '').strip().upper()
            p_name = param.name.strip().lower()
            t_rate = tariff_lookup.get((p_code, 'parameter')) or tariff_lookup.get((p_name, 'parameter'))
            t_meta = tariff_metadata.get((p_code, 'parameter')) or tariff_metadata.get((p_name, 'parameter')) or {}
            eff_price = t_rate if t_rate is not None else float(param.base_price)

            results.append({
                'id': f'param_{param.id}',
                'real_id': param.id,
                'type': 'parameter',
                'badge': 'SINGLE',
                'name': param.name,
                'code': param.code,
                'category': param.category or 'General Lab',
                'specimen': param.specimen,
                'sample_bottle_color': param.sample_bottle_color,
                'sample_quantity': param.sample_quantity,
                'price': eff_price,
                'rate': eff_price,
                'plan_name': t_meta.get('plan_name', ''),
                'sponsor_name': t_meta.get('sponsor_name', ''),
                'is_plan_tariff': t_meta.get('is_plan_tariff', False),
                'parameter_count': 1,
                'parameters_summary': [param.name],
                'description': f"Single test • {param.measurement_unit}" if param.measurement_unit else "Single test"
            })

        # Sort alphabetically or query match
        results.sort(key=lambda x: (x['name'].lower()))
        return Response(results)


class LabOrderTemplateView(APIView):
    """
    Given a RadiologyLab order ID, returns the patient demographic info
    and the structured list of parameters to test (with pre-matched reference ranges).
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request, order_id):
        try:
            order = RadiologyLab.objects.select_related('patient').get(id=order_id)
        except RadiologyLab.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        patient = order.patient
        demo_group = get_patient_demographic_group(patient)
        demo_display = dict(LabParameterReferenceRange.DEMOGRAPHIC_CHOICES).get(demo_group, 'General')

        # Check existing result items
        existing_items = list(order.parameter_results.all().order_by('display_order'))

        if existing_items:
            items_data = LabOrderResultItemSerializer(existing_items, many=True).data
            return Response({
                'order_id': order.id,
                'item_name': order.item,
                'demographic_group': demo_group,
                'demographic_group_display': demo_display,
                'patient_name': f"{patient.surname} {patient.first_name}" if patient else "Unknown",
                'patient_gender': patient.gender if patient else "",
                'patient_dob': getattr(patient, 'dob', None) or getattr(patient, 'date_of_birth', None) if patient else None,
                'already_recorded': True,
                'parameters': items_data
            })

        # Attempt to match order.item to a LabInvestigation
        inv = LabInvestigation.objects.filter(
            Q(name__iexact=order.item) | Q(code__iexact=order.item)
        ).prefetch_related('parameter_mappings__parameter__reference_ranges').first()

        params_to_fill = []

        if inv:
            for mapping in inv.parameter_mappings.all():
                p = mapping.parameter
                ref = p.reference_ranges.filter(demographic_group=demo_group).first()
                if not ref:
                    # fallback to general
                    ref = p.reference_ranges.filter(demographic_group='general').first()

                ref_display = ''
                if ref:
                    if ref.low_boundary is not None and ref.high_boundary is not None:
                        ref_display = f"{ref.low_boundary} - {ref.high_boundary}"
                    elif ref.common_value:
                        ref_display = ref.common_value

                params_to_fill.append({
                    'id': None,
                    'order': order.id,
                    'parameter': p.id,
                    'investigation': inv.id,
                    'parameter_name': p.name,
                    'result_value': '',
                    'unit': p.measurement_unit or '',
                    'reference_range_display': ref_display,
                    'flag': '',
                    'display_order': mapping.order,
                    'low_boundary': float(ref.low_boundary) if ref and ref.low_boundary is not None else None,
                    'high_boundary': float(ref.high_boundary) if ref and ref.high_boundary is not None else None,
                    'low_critical': float(ref.low_critical) if ref and ref.low_critical is not None else None,
                    'high_critical': float(ref.high_critical) if ref and ref.high_critical is not None else None,
                })
        else:
            # Check if it matches a standalone parameter
            param = LabParameter.objects.filter(
                Q(name__iexact=order.item) | Q(code__iexact=order.item)
            ).prefetch_related('reference_ranges').first()

            if param:
                ref = param.reference_ranges.filter(demographic_group=demo_group).first()
                if not ref:
                    ref = param.reference_ranges.filter(demographic_group='general').first()

                ref_display = ''
                if ref:
                    if ref.low_boundary is not None and ref.high_boundary is not None:
                        ref_display = f"{ref.low_boundary} - {ref.high_boundary}"
                    elif ref.common_value:
                        ref_display = ref.common_value

                params_to_fill.append({
                    'id': None,
                    'order': order.id,
                    'parameter': param.id,
                    'investigation': None,
                    'parameter_name': param.name,
                    'result_value': '',
                    'unit': param.measurement_unit or '',
                    'reference_range_display': ref_display,
                    'flag': '',
                    'display_order': 1,
                    'low_boundary': float(ref.low_boundary) if ref and ref.low_boundary is not None else None,
                    'high_boundary': float(ref.high_boundary) if ref and ref.high_boundary is not None else None,
                    'low_critical': float(ref.low_critical) if ref and ref.low_critical is not None else None,
                    'high_critical': float(ref.high_critical) if ref and ref.high_critical is not None else None,
                })
            else:
                # Custom/ad-hoc test: provide a single editable row
                params_to_fill.append({
                    'id': None,
                    'order': order.id,
                    'parameter': None,
                    'investigation': None,
                    'parameter_name': order.item,
                    'result_value': '',
                    'unit': '',
                    'reference_range_display': '',
                    'flag': '',
                    'display_order': 1,
                    'low_boundary': None,
                    'high_boundary': None,
                    'low_critical': None,
                    'high_critical': None,
                })

        return Response({
            'order_id': order.id,
            'item_name': order.item,
            'demographic_group': demo_group,
            'demographic_group_display': demo_display,
            'patient_name': f"{patient.surname} {patient.first_name}" if patient else "Unknown",
            'patient_gender': patient.gender if patient else "",
            'patient_dob': getattr(patient, 'dob', None) or getattr(patient, 'date_of_birth', None) if patient else None,
            'already_recorded': False,
            'parameters': params_to_fill
        })


class LabOrderResultItemViewSet(viewsets.ModelViewSet):
    """ViewSet for managing individual result rows and batch-saving completed test panels."""
    queryset = LabOrderResultItem.objects.all().order_by('display_order')
    serializer_class = LabOrderResultItemSerializer
    permission_classes = [permissions.AllowAny]

    def get_queryset(self):
        qs = super().get_queryset()
        order_id = self.request.query_params.get('order_id')
        if order_id:
            qs = qs.filter(order_id=order_id)
        return qs

    @action(detail=False, methods=['post'])
    def bulk_save(self, request):
        """
        Saves all result items for an order in one atomic transaction,
        evaluates flags, creates backwards-compatible LabResult summary,
        and marks the RadiologyLab order as completed.
        """
        order_id = request.data.get('order_id')
        items_data = request.data.get('results', [])
        comments = request.data.get('comments', '')

        if not order_id:
            return Response({'error': 'order_id is required'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            order = RadiologyLab.objects.select_related('patient').get(id=order_id)
        except RadiologyLab.DoesNotExist:
            return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)

        demo_group = get_patient_demographic_group(order.patient)

        with transaction.atomic():
            # Delete previous structured items for this order to allow overwrite
            LabOrderResultItem.objects.filter(order=order).delete()

            created_items = []
            summary_lines = []

            for idx, item in enumerate(items_data):
                param_id = item.get('parameter')
                param_obj = None
                ref_obj = None
                if param_id:
                    try:
                        param_obj = LabParameter.objects.get(id=param_id)
                        ref_obj = param_obj.reference_ranges.filter(demographic_group=demo_group).first()
                        if not ref_obj:
                            ref_obj = param_obj.reference_ranges.filter(demographic_group='general').first()
                    except LabParameter.DoesNotExist:
                        pass

                val = str(item.get('result_value', '') or '').strip()
                unit = item.get('unit', '') or (param_obj.measurement_unit if param_obj else '')
                ref_display = item.get('reference_range_display', '')

                # Compute flag if not explicitly provided
                flag = item.get('flag', '')
                if not flag and ref_obj and val:
                    flag = evaluate_result_flag(val, ref_obj)

                obj = LabOrderResultItem.objects.create(
                    order=order,
                    parameter=param_obj,
                    investigation_id=item.get('investigation'),
                    parameter_name=item.get('parameter_name') or (param_obj.name if param_obj else 'Test'),
                    result_value=val,
                    unit=unit,
                    reference_range_display=ref_display,
                    flag=flag,
                    display_order=idx + 1
                )
                created_items.append(obj)

                flag_str = f" [{flag}]" if flag and flag != 'NORMAL' else ""
                ref_str = f" (Ref: {ref_display})" if ref_display else ""
                unit_str = f" {unit}" if unit else ""
                summary_lines.append(f"{obj.parameter_name}: {val}{unit_str}{ref_str}{flag_str}")

            if comments:
                summary_lines.append(f"\nComments: {comments}")

            # Update or create legacy LabResult so existing views/reports continue working seamlessly
            full_summary = "\n".join(summary_lines)
            user = request.user if request.user.is_authenticated else None

            lab_res = LabResult.objects.filter(order=order).first()
            if lab_res:
                lab_res.results = full_summary
                lab_res.waiting_status = 1
                lab_res.save()
            else:
                LabResult.objects.create(
                    order=order,
                    investigation=order.item,
                    results=full_summary,
                    waiting_status=1,
                    patient=order.patient,
                    staff=user
                )

            # Mark order completed
            order.completed = 1
            order.radiolab_waiting_status = 1
            order.save(update_fields=['completed', 'radiolab_waiting_status'])

        return Response({
            'message': 'Lab results saved successfully',
            'order_id': order.id,
            'count': len(created_items),
            'results': LabOrderResultItemSerializer(created_items, many=True).data
        }, status=status.HTTP_201_CREATED)

