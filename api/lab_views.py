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
    LabResult,
    RadiologyProcedure
)
from .lab_serializers import (
    LabParameterSerializer,
    LabInvestigationSerializer,
    LabInvestigationParameterSerializer,
    LabParameterReferenceRangeSerializer,
    LabOrderResultItemSerializer,
    RadiologyProcedureSerializer
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


def evaluate_result_flag(value_str, ref_range, result_type='numeric'):
    """
    Given a result string, ref_range, and result_type:
    - If qualitative: 'Positive' -> 'HIGH', 'Negative' -> 'NORMAL'
    - If numeric: evaluates against low_critical, high_critical, low_boundary, high_boundary
    """
    if not value_str:
        return ''
    val_clean = str(value_str).strip()
    if not val_clean:
        return ''

    # Qualitative check
    if result_type == 'qualitative' or val_clean.lower() in ['positive', 'negative', 'reactive', 'non-reactive']:
        if val_clean.lower() in ['positive', 'reactive']:
            return 'HIGH'
        if val_clean.lower() in ['negative', 'non-reactive']:
            return 'NORMAL'

    if not ref_range:
        return ''

    try:
        val = Decimal(val_clean)
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
    and the structured list of parameters to test (with pre-matched reference ranges),
    merging any previously entered partial results and who signed each parameter.
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

        # Map existing result items (if any partial/historic results were previously saved)
        existing_items = list(order.parameter_results.all().order_by('display_order'))
        existing_map = {}
        for ei in existing_items:
            if ei.parameter_id:
                existing_map[f"param_{ei.parameter_id}"] = ei
            if ei.parameter_name:
                existing_map[ei.parameter_name.strip().lower()] = ei

        # Attempt to match order.item to a LabInvestigation (Panel)
        inv = LabInvestigation.objects.filter(
            Q(name__iexact=order.item) | Q(code__iexact=order.item)
        ).prefetch_related('parameter_mappings__parameter__reference_ranges').first()

        params_to_fill = []
        handled_existing_ids = set()

        if inv:
            for mapping in inv.parameter_mappings.all():
                p = mapping.parameter
                ref = p.reference_ranges.filter(demographic_group=demo_group).first()
                if not ref:
                    ref = p.reference_ranges.filter(demographic_group='general').first()

                ref_display = ''
                if ref:
                    if ref.low_boundary is not None and ref.high_boundary is not None:
                        ref_display = f"{ref.low_boundary} - {ref.high_boundary}"
                    elif ref.common_value:
                        ref_display = ref.common_value

                match_key = f"param_{p.id}"
                existing_obj = existing_map.get(match_key) or existing_map.get(p.name.strip().lower())
                if existing_obj:
                    handled_existing_ids.add(existing_obj.id)

                val = existing_obj.result_value if existing_obj else ''
                flag = existing_obj.flag if existing_obj else ''
                entered_by_name = existing_obj.entered_by_name if existing_obj else ''
                entered_at_str = existing_obj.entered_at.isoformat() if (existing_obj and existing_obj.entered_at) else None

                params_to_fill.append({
                    'id': existing_obj.id if existing_obj else None,
                    'order': order.id,
                    'parameter': p.id,
                    'investigation': inv.id,
                    'parameter_name': p.name,
                    'result_value': val,
                    'unit': p.measurement_unit or (existing_obj.unit if existing_obj else ''),
                    'result_type': p.result_type or 'numeric',
                    'normal_result_description': p.normal_result_description or '',
                    'reference_range_display': ref_display or (existing_obj.reference_range_display if existing_obj else ''),
                    'flag': flag,
                    'display_order': mapping.order,
                    'low_boundary': float(ref.low_boundary) if ref and ref.low_boundary is not None else None,
                    'high_boundary': float(ref.high_boundary) if ref and ref.high_boundary is not None else None,
                    'low_critical': float(ref.low_critical) if ref and ref.low_critical is not None else None,
                    'high_critical': float(ref.high_critical) if ref and ref.high_critical is not None else None,
                    'entered_by': existing_obj.entered_by_id if existing_obj else None,
                    'entered_by_name': entered_by_name,
                    'entered_at': entered_at_str,
                })

            # Also include any ad-hoc / custom parameters previously added
            for existing_obj in existing_items:
                if existing_obj.id not in handled_existing_ids:
                    params_to_fill.append({
                        'id': existing_obj.id,
                        'order': order.id,
                        'parameter': existing_obj.parameter_id,
                        'investigation': existing_obj.investigation_id,
                        'parameter_name': existing_obj.parameter_name,
                        'result_value': existing_obj.result_value or '',
                        'unit': existing_obj.unit or '',
                        'result_type': 'numeric',
                        'normal_result_description': '',
                        'reference_range_display': existing_obj.reference_range_display or '',
                        'flag': existing_obj.flag or '',
                        'display_order': existing_obj.display_order,
                        'low_boundary': None,
                        'high_boundary': None,
                        'low_critical': None,
                        'high_critical': None,
                        'entered_by': existing_obj.entered_by_id,
                        'entered_by_name': existing_obj.entered_by_name or '',
                        'entered_at': existing_obj.entered_at.isoformat() if existing_obj.entered_at else None,
                    })

        elif existing_items:
            # If no investigation mapping but existing items exist, return them
            for existing_obj in existing_items:
                params_to_fill.append({
                    'id': existing_obj.id,
                    'order': order.id,
                    'parameter': existing_obj.parameter_id,
                    'investigation': existing_obj.investigation_id,
                    'parameter_name': existing_obj.parameter_name,
                    'result_value': existing_obj.result_value or '',
                    'unit': existing_obj.unit or '',
                    'result_type': 'numeric',
                    'normal_result_description': '',
                    'reference_range_display': existing_obj.reference_range_display or '',
                    'flag': existing_obj.flag or '',
                    'display_order': existing_obj.display_order,
                    'low_boundary': None,
                    'high_boundary': None,
                    'low_critical': None,
                    'high_critical': None,
                    'entered_by': existing_obj.entered_by_id,
                    'entered_by_name': existing_obj.entered_by_name or '',
                    'entered_at': existing_obj.entered_at.isoformat() if existing_obj.entered_at else None,
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
                    'result_type': param.result_type or 'numeric',
                    'normal_result_description': param.normal_result_description or '',
                    'reference_range_display': ref_display,
                    'flag': '',
                    'display_order': 1,
                    'low_boundary': float(ref.low_boundary) if ref and ref.low_boundary is not None else None,
                    'high_boundary': float(ref.high_boundary) if ref and ref.high_boundary is not None else None,
                    'low_critical': float(ref.low_critical) if ref and ref.low_critical is not None else None,
                    'high_critical': float(ref.high_critical) if ref and ref.high_critical is not None else None,
                    'entered_by': None,
                    'entered_by_name': '',
                    'entered_at': None,
                })
            else:
                # Custom/ad-hoc test
                params_to_fill.append({
                    'id': None,
                    'order': order.id,
                    'parameter': None,
                    'investigation': None,
                    'parameter_name': order.item,
                    'result_value': '',
                    'unit': '',
                    'result_type': 'numeric',
                    'normal_result_description': '',
                    'reference_range_display': '',
                    'flag': '',
                    'display_order': 1,
                    'low_boundary': None,
                    'high_boundary': None,
                    'low_critical': None,
                    'high_critical': None,
                    'entered_by': None,
                    'entered_by_name': '',
                    'entered_at': None,
                })

        # Calculate counts
        filled_count = len([p for p in params_to_fill if p.get('result_value') and str(p.get('result_value')).strip()])
        is_partial = (filled_count > 0 and filled_count < len(params_to_fill)) and order.completed != 1

        return Response({
            'order_id': order.id,
            'item_name': order.item,
            'demographic_group': demo_group,
            'demographic_group_display': demo_display,
            'patient_name': f"{patient.surname} {patient.first_name}" if patient else "Unknown",
            'patient_gender': patient.gender if patient else "",
            'patient_dob': getattr(patient, 'dob', None) or getattr(patient, 'date_of_birth', None) if patient else None,
            'already_recorded': filled_count > 0,
            'is_partial': is_partial,
            'is_completed': order.completed == 1,
            'filled_count': filled_count,
            'total_count': len(params_to_fill),
            'parameters': params_to_fill
        })


class LabOrderResultItemViewSet(viewsets.ModelViewSet):
    """ViewSet for managing individual result rows, PIN verification, partial drafts, and batch-saving completed test panels."""
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
        Saves result items for an order in one atomic transaction with mandatory PIN verification.
        Supports partial saving (saving ready parameters while awaiting remaining readouts),
        captures attending staff credentials and timestamps on each parameter row,
        and marks the order as completed only when all parameters are ready or finalized.
        """
        order_id = request.data.get('order_id')
        items_data = request.data.get('results', [])
        if isinstance(items_data, str):
            import json
            try:
                items_data = json.loads(items_data)
            except Exception:
                items_data = []
        comments = request.data.get('comments', '')
        pin_code = request.data.get('pin_code')
        finalize = request.data.get('finalize', False)
        if isinstance(finalize, str):
            finalize = finalize.lower() in ['true', '1']
        file_obj = request.FILES.get('file') or request.FILES.get('file_upload')

        if not order_id:
            return Response({'detail': 'order_id is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Mandatory Security PIN Verification
        if not pin_code or str(pin_code).strip() == '':
            return Response(
                {'detail': 'Security PIN is required. Please enter your 4-digit PIN to authorize and sign laboratory findings.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        pin_str = str(pin_code).strip()
        if not pin_str.isdigit():
            return Response(
                {'detail': 'Invalid security PIN format. PIN must contain numeric digits only.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Identify attending staff member
        user = None
        if request.user and request.user.is_authenticated:
            user = request.user
        elif request.data.get('staff_id'):
            from users.models import User
            user = User.objects.filter(id=request.data.get('staff_id'), is_active=True).first()
        elif request.data.get('staff_username'):
            from users.models import User
            user = User.objects.filter(username__iexact=str(request.data.get('staff_username')).strip(), is_active=True).first()

        if not user:
            return Response(
                {'detail': 'Authentication required. Please log in as an attending staff member to authorize lab results.'},
                status=status.HTTP_401_UNAUTHORIZED
            )

        # Verify PIN against user's PIN
        if not user.has_pin:
            staff_name = getattr(user, 'fullname', '') or user.username
            return Response(
                {'detail': f'Staff member "{staff_name}" has no security PIN configured. Please set your 4-digit PIN in Profile Settings before recording lab results.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not user.check_pin(pin_str):
            return Response(
                {'detail': 'Incorrect Security PIN. Result entry authorization denied.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            order = RadiologyLab.objects.select_related('patient').get(id=order_id)
        except RadiologyLab.DoesNotExist:
            return Response({'detail': 'Order not found.'}, status=status.HTTP_404_NOT_FOUND)

        demo_group = get_patient_demographic_group(order.patient)

        # Ensure at least one parameter value or remarks is provided
        non_empty_items = [item for item in items_data if str(item.get('result_value', '') or '').strip()]
        if not non_empty_items and not comments.strip():
            return Response(
                {'detail': 'Please provide readout findings for at least one parameter or provide remarks.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Determine completion: if user explicitly requested finalize, or if ALL parameters are filled
        is_completed = bool(finalize) or (len(items_data) > 0 and len(non_empty_items) >= len(items_data))

        with transaction.atomic():
            existing_map = {}
            for existing_item in LabOrderResultItem.objects.filter(order=order):
                if existing_item.parameter_id:
                    existing_map[f"param_{existing_item.parameter_id}"] = existing_item
                if existing_item.parameter_name:
                    existing_map[existing_item.parameter_name.strip().lower()] = existing_item

            created_items = []
            summary_lines = []
            author_name = getattr(user, 'fullname', '') or user.username

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

                param_name = item.get('parameter_name') or (param_obj.name if param_obj else 'Test')
                val = str(item.get('result_value', '') or '').strip()
                unit = item.get('unit', '') or (param_obj.measurement_unit if param_obj else '')
                ref_display = item.get('reference_range_display', '')

                # Compute flag if value is present
                flag = item.get('flag', '')
                if not flag and val:
                    res_type = param_obj.result_type if param_obj else item.get('result_type', 'numeric')
                    flag = evaluate_result_flag(val, ref_obj, res_type)

                match_key = f"param_{param_id}" if param_id else param_name.strip().lower()
                existing_item = existing_map.get(match_key)

                if existing_item:
                    obj = existing_item
                    obj.parameter = param_obj
                    obj.investigation_id = item.get('investigation') or obj.investigation_id
                    obj.parameter_name = param_name
                    obj.unit = unit
                    obj.reference_range_display = ref_display
                    obj.display_order = idx + 1

                    if val:
                        # If value changed or was not previously attributed, stamp with current user
                        if obj.result_value != val or not obj.entered_by:
                            obj.result_value = val
                            obj.flag = flag
                            obj.entered_by = user
                            obj.entered_by_name = author_name
                            obj.entered_at = timezone.now()
                    else:
                        obj.result_value = ''
                        obj.flag = ''
                    obj.save()
                else:
                    obj = LabOrderResultItem.objects.create(
                        order=order,
                        parameter=param_obj,
                        investigation_id=item.get('investigation'),
                        parameter_name=param_name,
                        result_value=val,
                        unit=unit,
                        reference_range_display=ref_display,
                        flag=flag if val else '',
                        display_order=idx + 1,
                        entered_by=user if val else None,
                        entered_by_name=author_name if val else '',
                        entered_at=timezone.now() if val else None
                    )

                created_items.append(obj)

                if val:
                    flag_str = f" [{flag}]" if flag and flag != 'NORMAL' else ""
                    ref_str = f" (Ref: {ref_display})" if ref_display else ""
                    unit_str = f" {unit}" if unit else ""
                    by_str = f" — Signed by {obj.entered_by_name}" if obj.entered_by_name else ""
                    summary_lines.append(f"• {obj.parameter_name}: {val}{unit_str}{ref_str}{flag_str}{by_str}")

            if comments:
                summary_lines.append(f"\nScientist Remarks:\n{comments}")

            # Legacy LabResult for backward compatibility with Doctor consultation / nurse chart
            header_prefix = "[VERIFIED FINAL LAB REPORT]\n" if is_completed else f"[PARTIAL PROGRESS REPORT — {len(non_empty_items)} of {len(items_data)} Parameters Ready]\n"
            full_summary = header_prefix + "\n".join(summary_lines)

            lab_res = LabResult.objects.filter(order=order).first()
            if lab_res:
                lab_res.results = full_summary
                lab_res.waiting_status = 1 if is_completed else 0
                lab_res.staff = user
                if file_obj:
                    lab_res.file_upload = file_obj
                lab_res.save()
            else:
                LabResult.objects.create(
                    order=order,
                    investigation=order.item,
                    results=full_summary,
                    file_upload=file_obj,
                    waiting_status=1 if is_completed else 0,
                    patient=order.patient,
                    staff=user
                )

            # Update order completed status
            order.completed = 1 if is_completed else 0
            order.radiolab_waiting_status = 1 if is_completed else 0
            order.save(update_fields=['completed', 'radiolab_waiting_status'])

        msg = 'Lab results verified and completed successfully.' if is_completed else f'Partial lab results saved successfully ({len(non_empty_items)} of {len(items_data)} parameters ready).'

        return Response({
            'message': msg,
            'order_id': order.id,
            'is_completed': is_completed,
            'filled_count': len(non_empty_items),
            'total_count': len(items_data),
            'count': len(created_items),
            'results': LabOrderResultItemSerializer(created_items, many=True).data
        }, status=status.HTTP_201_CREATED)

class RadiologyProcedureViewSet(viewsets.ModelViewSet):
    """
    CRUD viewset for Radiology & Diagnostic Imaging procedures catalog.
    Maintains the master list of scans (X-Ray, Ultrasound, CT, MRI, etc.).
    Automatically syncs or creates a General baseline tariff in RadioLabInventory.
    """
    queryset = RadiologyProcedure.objects.all().order_by('category', 'code', 'name')
    serializer_class = RadiologyProcedureSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    filter_backends = [filters.SearchFilter]
    search_fields = ['name', 'code', 'category', 'body_part']

    def get_queryset(self):
        qs = super().get_queryset()
        category = self.request.query_params.get('category')
        if category:
            qs = qs.filter(category__iexact=category)
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            qs = qs.filter(is_active=(is_active.lower() in ['true', '1']))
        return qs

    def perform_create(self, serializer):
        instance = serializer.save()
        from radio_lab.models import RadioLabInventory
        from users.models import User
        staff = self.request.user if self.request.user.is_authenticated else User.objects.first()

        gen_tariff = RadioLabInventory.objects.filter(
            type='R',
            sponsor__isnull=True,
            plan__isnull=True,
            item_id=instance.code
        ).first()

        if not gen_tariff:
            gen_tariff = RadioLabInventory.objects.filter(
                type='R',
                sponsor__isnull=True,
                plan__isnull=True,
                item__iexact=instance.name
            ).first()

        if gen_tariff:
            gen_tariff.item = instance.name
            gen_tariff.item_id = instance.code
            gen_tariff.rate = instance.base_price
            gen_tariff.save()
        else:
            RadioLabInventory.objects.create(
                item=instance.name,
                item_id=instance.code,
                rate=instance.base_price,
                type='R',
                sponsor=None,
                plan=None,
                staff=staff
            )

    def perform_update(self, serializer):
        instance = serializer.save()
        from radio_lab.models import RadioLabInventory
        gen_tariffs = RadioLabInventory.objects.filter(
            type='R',
            sponsor__isnull=True,
            plan__isnull=True
        ).filter(Q(item_id=instance.code) | Q(item__iexact=instance.name))
        for t in gen_tariffs:
            t.item = instance.name
            t.item_id = instance.code
            if instance.base_price > 0:
                t.rate = instance.base_price
            t.save()
