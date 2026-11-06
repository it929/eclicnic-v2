from rest_framework import status, permissions
from rest_framework.response import Response
from rest_framework.views import APIView
from decimal import Decimal
from django.db.models import Q

from queue_operations.models import RegFee
from patients.models import PatientPlan, Sponsor, PatientProfile
from IPD.models import Ward
from radio_lab.models import RadioLabInventory, RadiologyProcedure, LabInvestigation, LabParameter, LabInvestigationParameter
from inventory.models import Product, PharmacyTariff
from myAdmins.models import OtherService2, Packages, PackagesData
from users.models import User


# ==========================================================
# 1. SERVICE TARIFFS
# ==========================================================

# 1.1 Registration Fees
class RegistrationFeeView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        plans = RegFee.objects.all().order_by('plan_name')
        data = [{'id': p.id, 'plan_name': p.plan_name, 'price': p.price} for p in plans]
        return Response({'total': len(data), 'plans': data})

    def post(self, request):
        plan_name = request.data.get('plan_name', '').strip()
        price = request.data.get('price', 0)

        if not plan_name:
            return Response({'detail': 'Plan name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            price = int(price)
            if price < 0:
                return Response({'detail': 'Price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        if RegFee.objects.filter(plan_name__iexact=plan_name).exists():
            return Response({'detail': f'Plan "{plan_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        obj = RegFee.objects.create(plan_name=plan_name, price=price)
        return Response({'detail': f'Plan "{obj.plan_name}" created successfully.', 'id': obj.id, 'plan_name': obj.plan_name, 'price': obj.price})

    def put(self, request, pk=None):
        try:
            plan = RegFee.objects.get(id=pk)
        except RegFee.DoesNotExist:
            return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

        plan_name = request.data.get('plan_name', plan.plan_name).strip()
        price = request.data.get('price', plan.price)

        if RegFee.objects.filter(plan_name__iexact=plan_name).exclude(id=pk).exists():
            return Response({'detail': f'Another plan with name "{plan_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            plan.price = int(price)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        plan.plan_name = plan_name
        plan.save()
        return Response({'detail': 'Plan updated successfully.', 'id': plan.id, 'plan_name': plan.plan_name, 'price': plan.price})

    def delete(self, request, pk=None):
        try:
            plan = RegFee.objects.get(id=pk)
            plan.delete()
            return Response({'detail': 'Plan deleted successfully.'})
        except RegFee.DoesNotExist:
            return Response({'detail': 'Plan not found.'}, status=status.HTTP_404_NOT_FOUND)


# 1.2 Laboratory Charges
class LabChargesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = RadioLabInventory.objects.filter(type='L').select_related('sponsor', 'plan', 'plan__sponsor').order_by('item')

        tariff_type = request.query_params.get('tariff_type', '').strip().lower()
        patient_id = request.query_params.get('patient')
        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')
        test_type = request.query_params.get('test_type', '').strip().lower()
        search = request.query_params.get('search', '').strip()

        # If explicitly requesting general out-of-pocket tariffs
        if tariff_type == 'general' or (sponsor_id and str(sponsor_id).lower() in ('general', 'self', 'cash')):
            qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
        # If filtering for a specific patient
        elif patient_id or tariff_type == 'covered':
            if patient_id:
                try:
                    patient = PatientProfile.objects.select_related('sponsor', 'plan', 'category', 'sponsor__category').get(id=patient_id)
                    patient_sponsor = patient.sponsor
                    patient_plan = patient.plan

                    if not patient_sponsor and sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'self', 'cash'):
                        try:
                            patient_sponsor = Sponsor.objects.get(id=sponsor_id)
                        except Sponsor.DoesNotExist:
                            pass
                    if not patient_plan and plan_id and str(plan_id).lower() not in ('all', 'general', 'self', 'cash'):
                        try:
                            patient_plan = PatientPlan.objects.get(id=plan_id)
                        except PatientPlan.DoesNotExist:
                            pass

                    if tariff_type == 'general':
                        qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                    elif patient_sponsor and patient_plan:
                        qs = qs.filter(
                            (Q(sponsor=patient_sponsor) & Q(plan=patient_plan)) |
                            Q(plan=patient_plan) |
                            (Q(sponsor=patient_sponsor) & Q(plan__isnull=True))
                        )
                    elif patient_plan:
                        qs = qs.filter(plan=patient_plan)
                    elif patient_sponsor:
                        qs = qs.filter(Q(sponsor=patient_sponsor) | Q(plan__sponsor=patient_sponsor))
                    else:
                        qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                except PatientProfile.DoesNotExist:
                    if sponsor_id and str(sponsor_id).lower() != 'all':
                        qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
                    if plan_id and str(plan_id).lower() != 'all':
                        qs = qs.filter(plan_id=plan_id)
            else:
                if sponsor_id and str(sponsor_id).lower() != 'all':
                    qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
                if plan_id and str(plan_id).lower() != 'all':
                    qs = qs.filter(plan_id=plan_id)
        else:
            if sponsor_id and str(sponsor_id).lower() != 'all':
                qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
            if plan_id and str(plan_id).lower() != 'all':
                qs = qs.filter(plan_id=plan_id)

        # Filter by test type (investigations vs parameters)
        if test_type in ('investigation', 'investigations', 'panel', 'panels'):
            qs = qs.filter(test_type='investigation')
        elif test_type in ('parameter', 'parameters', 'single', 'singles'):
            qs = qs.filter(test_type='parameter')

        if search:
            qs = qs.filter(
                Q(item__icontains=search) |
                Q(item_id__icontains=search)
            )

        # Pre-cache code/name to category maps and investigations with parameter mappings
        inv_objs = list(LabInvestigation.objects.prefetch_related('parameter_mappings__parameter').all())
        inv_map = {inv.code.strip().upper(): (inv.category or 'General', inv.name) for inv in inv_objs if inv.code}
        inv_name_map = {inv.name.strip().lower(): (inv.category or 'General', inv.code) for inv in inv_objs if inv.name}
        inv_by_code = {inv.code.strip().upper(): inv for inv in inv_objs if inv.code}
        inv_by_name = {inv.name.strip().lower(): inv for inv in inv_objs if inv.name}

        param_objs = list(LabParameter.objects.all())
        param_by_id = {p.id: p for p in param_objs}
        param_map = {p.code.strip().upper(): (p.category or 'General', p.name) for p in param_objs if p.code}
        param_name_map = {p.name.strip().lower(): (p.category or 'General', p.code) for p in param_objs if p.name}

        # Pre-cache all parameter tariffs to quickly resolve sponsor/plan specific rates
        param_tariff_rows = list(RadioLabInventory.objects.filter(type='L', test_type='parameter').select_related('sponsor', 'plan'))
        # Index by: (code_or_name_upper, sponsor_id, plan_id) -> float(rate)
        plan_param_rate_map = {}
        for ptr in param_tariff_rows:
            p_code = (ptr.item_id or '').strip().upper()
            p_name = ptr.item.strip().upper()
            s_id = ptr.sponsor_id
            pl_id = ptr.plan_id
            r_val = float(ptr.rate)
            if p_code:
                plan_param_rate_map[(p_code, s_id, pl_id)] = r_val
            if p_name:
                plan_param_rate_map[(p_name, s_id, pl_id)] = r_val

        data = []
        for item in qs:
            eff_sponsor = item.sponsor or (item.plan.sponsor if item.plan else None)
            is_gen = bool(not eff_sponsor and not item.plan)
            code_upper = (item.item_id or '').strip().upper()
            name_lower = (item.item or '').strip().lower()

            # Resolve effective test_type
            t_type = item.test_type
            if not t_type or t_type == '':
                if code_upper in param_map or name_lower in param_name_map:
                    t_type = 'parameter'
                else:
                    t_type = 'investigation'

            # Resolve category
            category = 'General'
            if code_upper in inv_map:
                category = inv_map[code_upper][0]
            elif name_lower in inv_name_map:
                category = inv_name_map[name_lower][0]
            elif code_upper in param_map:
                category = param_map[code_upper][0]
            elif name_lower in param_name_map:
                category = param_name_map[name_lower][0]

            # Resolve investigation parameter mappings for this specific sponsor and plan
            mapped_params = []
            mapped_param_ids = []
            accumulated_price = 0.0

            # 1. Use sponsor/plan specific parameter_ids if saved on RadioLabInventory row
            target_pids = []
            if item.parameter_ids and isinstance(item.parameter_ids, list) and len(item.parameter_ids) > 0:
                target_pids = item.parameter_ids
            else:
                matched_inv = inv_by_code.get(code_upper) or inv_by_name.get(name_lower)
                if matched_inv:
                    target_pids = [m.parameter.id for m in matched_inv.parameter_mappings.all()]

            s_id = eff_sponsor.id if eff_sponsor else None
            pl_id = item.plan_id if item.plan else None

            for pid in target_pids:
                param = param_by_id.get(pid)
                if not param:
                    continue
                mapped_param_ids.append(param.id)

                p_code = (param.code or '').strip().upper()
                p_name = param.name.strip().upper()

                # Find exact rate for this sponsor and plan
                p_rate = None
                p_source = 'base'
                p_source_label = 'Base Rate'

                if s_id and pl_id and (p_code, s_id, pl_id) in plan_param_rate_map:
                    p_rate = plan_param_rate_map[(p_code, s_id, pl_id)]
                    p_source = 'plan'
                    p_source_label = f"{item.plan.plan} Tariff"
                elif s_id and pl_id and (p_name, s_id, pl_id) in plan_param_rate_map:
                    p_rate = plan_param_rate_map[(p_name, s_id, pl_id)]
                    p_source = 'plan'
                    p_source_label = f"{item.plan.plan} Tariff"
                elif s_id and (p_code, s_id, None) in plan_param_rate_map:
                    p_rate = plan_param_rate_map[(p_code, s_id, None)]
                    p_source = 'sponsor'
                    p_source_label = f"{eff_sponsor.name} Tariff"
                elif s_id and (p_name, s_id, None) in plan_param_rate_map:
                    p_rate = plan_param_rate_map[(p_name, s_id, None)]
                    p_source = 'sponsor'
                    p_source_label = f"{eff_sponsor.name} Tariff"
                elif (p_code, None, None) in plan_param_rate_map:
                    p_rate = plan_param_rate_map[(p_code, None, None)]
                    p_source = 'general'
                    p_source_label = 'General Tariff'
                elif (p_name, None, None) in plan_param_rate_map:
                    p_rate = plan_param_rate_map[(p_name, None, None)]
                    p_source = 'general'
                    p_source_label = 'General Tariff'
                else:
                    p_rate = float(param.base_price or 0)
                    p_source = 'base'
                    p_source_label = 'Base Rate'

                accumulated_price += p_rate
                mapped_params.append({
                    'id': param.id,
                    'code': param.code,
                    'name': param.name,
                    'rate': p_rate,
                    'tariff_rate': p_rate,
                    'source': p_source,
                    'source_label': p_source_label,
                    'base_price': float(param.base_price or 0),
                    'category': param.category or 'General',
                })

            data.append({
                'id': item.id,
                'item': item.item,
                'item_id': item.item_id or '',
                'rate': float(item.rate),
                'test_type': t_type,
                'test_type_label': 'Investigation (Panel)' if t_type == 'investigation' else 'Parameter (Test)',
                'category': category,
                'mapped_parameters': mapped_params,
                'mapped_parameter_ids': mapped_param_ids,
                'parameter_count': len(mapped_param_ids),
                'accumulated_price': accumulated_price,
                'sponsor_id': eff_sponsor.id if eff_sponsor else None,
                'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
                'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
                'plan_id': item.plan.id if item.plan else None,
                'plan_name': item.plan.plan if item.plan else ('General Price' if is_gen else 'All Plans'),
                'plan_code': item.plan.code if item.plan else ('GENERAL' if is_gen else ''),
                'is_general': is_gen,
                'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
            })
        return Response({'total': len(data), 'charges': data, 'results': data})

    def post(self, request):
        item_name = request.data.get('item', '').strip() or request.data.get('item_name', '').strip()
        item_id = request.data.get('item_id', '').strip()
        rate = request.data.get('rate', 0)
        test_type = request.data.get('test_type', '').strip().lower()
        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        plan_id = request.data.get('plan_id') or request.data.get('plan')

        if not item_name:
            return Response({'detail': 'Test item name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        # Auto-detect test_type if not provided
        if not test_type or test_type not in ('investigation', 'parameter'):
            if LabParameter.objects.filter(Q(code__iexact=item_id) | Q(name__iexact=item_name)).exists():
                test_type = 'parameter'
            else:
                test_type = 'investigation'

        is_general = (
            not sponsor_id or
            str(sponsor_id).lower() in ('', 'general', 'self', 'cash', 'none', 'null')
        )

        plan = None
        sponsor = None

        if not is_general:
            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none'):
                try:
                    plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                except PatientPlan.DoesNotExist:
                    return Response({'detail': 'Selected Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'none'):
                try:
                    sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    return Response({'detail': 'Selected Sponsor not found.'}, status=status.HTTP_404_NOT_FOUND)
            elif plan and plan.sponsor:
                sponsor = plan.sponsor

        staff = request.user if request.user.is_authenticated else User.objects.first()

        # Check if record already exists for this (item_id, sponsor, plan)
        existing = None
        if item_id:
            existing = RadioLabInventory.objects.filter(
                type='L',
                item_id=item_id,
                sponsor=sponsor,
                plan=plan
            ).first()
        if not existing:
            existing = RadioLabInventory.objects.filter(
                type='L',
                item__iexact=item_name,
                sponsor=sponsor,
                plan=plan
            ).first()

        if existing:
            existing.rate = Decimal(str(rate))
            existing.item = item_name
            if item_id:
                existing.item_id = item_id
            existing.test_type = test_type
            existing.save()
            obj = existing
            msg = f'Tariff price for "{obj.item}" updated successfully.'
        else:
            obj = RadioLabInventory.objects.create(
                item=item_name,
                item_id=item_id or f"LAB-{RadioLabInventory.objects.count()+1:03d}",
                rate=Decimal(str(rate)),
                type='L',
                test_type=test_type,
                sponsor=sponsor,
                plan=plan,
                staff=staff
            )
            msg = f'Tariff price for "{obj.item}" created successfully.'

        # If parameter_ids provided, save on RadioLabInventory row and sync
        if 'parameter_ids' in request.data:
            p_ids = request.data.get('parameter_ids')
            if isinstance(p_ids, list):
                obj.parameter_ids = p_ids
                obj.save(update_fields=['parameter_ids', 'updated_date'])
                code = (obj.item_id or '').strip()
                name = obj.item.strip()
                inv = None
                if code:
                    inv = LabInvestigation.objects.filter(code__iexact=code).first()
                if not inv and name:
                    inv = LabInvestigation.objects.filter(name__iexact=name).first()
                if not inv:
                    inv = LabInvestigation.objects.create(
                        code=code or f"INV-{obj.id:03d}",
                        name=name,
                        base_price=obj.rate,
                        is_panel=True,
                        use_accumulated_price=True
                    )
                LabInvestigationParameter.objects.filter(investigation=inv).delete()
                for idx, pid in enumerate(p_ids):
                    try:
                        param = LabParameter.objects.get(id=pid)
                        LabInvestigationParameter.objects.create(
                            investigation=inv,
                            parameter=param,
                            order=idx + 1
                        )
                    except LabParameter.DoesNotExist:
                        pass
                inv.base_price = obj.rate
                inv.save()

        eff_sponsor = obj.sponsor or (obj.plan.sponsor if obj.plan else None)
        is_gen = bool(not eff_sponsor and not obj.plan)
        return Response({
            'detail': msg,
            'id': obj.id,
            'item': obj.item,
            'item_id': obj.item_id,
            'rate': float(obj.rate),
            'test_type': obj.test_type,
            'test_type_label': 'Investigation (Panel)' if obj.test_type == 'investigation' else 'Parameter (Test)',
            'sponsor_id': eff_sponsor.id if eff_sponsor else None,
            'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
            'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else ('General Price' if is_gen else 'All Plans'),
            'plan_code': obj.plan.code if obj.plan else ('GENERAL' if is_gen else ''),
            'is_general': is_gen,
            'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
        }, status=status.HTTP_201_CREATED if not existing else status.HTTP_200_OK)

    def put(self, request, pk=None):
        try:
            obj = RadioLabInventory.objects.select_related('sponsor', 'plan').get(id=pk, type='L')
        except RadioLabInventory.DoesNotExist:
            return Response({'detail': 'Lab charge not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'item' in request.data:
            obj.item = request.data['item'].strip()
        if 'rate' in request.data:
            obj.rate = Decimal(str(request.data['rate']))
        if 'item_id' in request.data:
            obj.item_id = request.data['item_id'].strip()
        if 'test_type' in request.data:
            tt = request.data['test_type'].strip().lower()
            if tt in ('investigation', 'parameter'):
                obj.test_type = tt

        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        if sponsor_id is not None:
            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'self', 'cash', 'none', 'null'):
                try:
                    obj.sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    pass
            else:
                obj.sponsor = None

        plan_id = request.data.get('plan_id') or request.data.get('plan')
        if plan_id is not None:
            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none'):
                try:
                    obj.plan = PatientPlan.objects.get(id=plan_id)
                    if obj.plan.sponsor and not obj.sponsor:
                        obj.sponsor = obj.plan.sponsor
                except PatientPlan.DoesNotExist:
                    pass
            else:
                obj.plan = None

        obj.save()

        # If parameter_ids provided, save on RadioLabInventory row and sync
        if 'parameter_ids' in request.data:
            p_ids = request.data.get('parameter_ids')
            if isinstance(p_ids, list):
                obj.parameter_ids = p_ids
                obj.save(update_fields=['parameter_ids', 'updated_date'])
                code = (obj.item_id or '').strip()
                name = obj.item.strip()
                inv = None
                if code:
                    inv = LabInvestigation.objects.filter(code__iexact=code).first()
                if not inv and name:
                    inv = LabInvestigation.objects.filter(name__iexact=name).first()
                if not inv:
                    inv = LabInvestigation.objects.create(
                        code=code or f"INV-{obj.id:03d}",
                        name=name,
                        base_price=obj.rate,
                        is_panel=True,
                        use_accumulated_price=True
                    )
                LabInvestigationParameter.objects.filter(investigation=inv).delete()
                for idx, pid in enumerate(p_ids):
                    try:
                        param = LabParameter.objects.get(id=pid)
                        LabInvestigationParameter.objects.create(
                            investigation=inv,
                            parameter=param,
                            order=idx + 1
                        )
                    except LabParameter.DoesNotExist:
                        pass
                inv.base_price = obj.rate
                inv.save()

        eff_sponsor = obj.sponsor or (obj.plan.sponsor if obj.plan else None)
        is_gen = bool(not eff_sponsor and not obj.plan)
        return Response({
            'detail': f'Tariff for "{obj.item}" updated successfully.',
            'id': obj.id,
            'item': obj.item,
            'item_id': obj.item_id,
            'rate': float(obj.rate),
            'test_type': obj.test_type,
            'test_type_label': 'Investigation (Panel)' if obj.test_type == 'investigation' else 'Parameter (Test)',
            'sponsor_id': eff_sponsor.id if eff_sponsor else None,
            'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else 'All Plans',
        })

    def delete(self, request, pk=None):
        try:
            RadioLabInventory.objects.filter(id=pk, type='L').delete()
            return Response({'detail': 'Lab charge deleted.'})
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# 1.2.1 Download Laboratory Tariff Template Pre-Filled from Database
class DownloadLabTariffTemplateView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.http import HttpResponse
        import io, csv

        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')
        template_type = (request.query_params.get('template_type') or request.query_params.get('type') or 'all').strip().lower()

        is_general = not sponsor_id or str(sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none', 'null')

        sponsor = None
        plan = None
        sponsor_code = "GENERAL"
        plan_code = "GENERAL"
        sponsor_name = "General / Out-of-Pocket"
        plan_name = "General Price (Pay from your purse)"

        if not is_general:
            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'none'):
                try:
                    sponsor = Sponsor.objects.get(id=sponsor_id)
                    sponsor_code = sponsor.code or sponsor.name
                    sponsor_name = sponsor.name
                except Sponsor.DoesNotExist:
                    pass

            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none'):
                try:
                    plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                    plan_code = plan.code or plan.plan
                    plan_name = plan.plan
                    if not sponsor and plan.sponsor:
                        sponsor = plan.sponsor
                        sponsor_code = sponsor.code or sponsor.name
                        sponsor_name = sponsor.name
                except PatientPlan.DoesNotExist:
                    pass

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['item_name', 'test_code', 'test_type', 'category', 'tariff_rate', 'sponsor_code', 'plan_code', 'notes'])

        notes_text = "General Tariff" if is_general else f"Covered under {plan_name}"

        # 1. Investigations from Database
        if template_type in ('all', 'investigations', 'panels'):
            invs = LabInvestigation.objects.filter(is_active=True).prefetch_related('parameter_mappings__parameter').order_by('category', 'name')
            for inv in invs:
                existing = RadioLabInventory.objects.filter(
                    type='L',
                    item_id=inv.code,
                    sponsor=sponsor,
                    plan=plan
                ).first()
                rate = f"{existing.rate:.2f}" if existing else f"{inv.effective_price():.2f}"
                writer.writerow([
                    inv.name,
                    inv.code,
                    'Investigation',
                    inv.category or 'General',
                    rate,
                    sponsor_code,
                    plan_code,
                    notes_text
                ])

        # 2. Parameters from Database
        if template_type in ('all', 'parameters', 'singles'):
            params = LabParameter.objects.filter(is_active=True).order_by('category', 'display_order', 'name')
            for param in params:
                existing = RadioLabInventory.objects.filter(
                    type='L',
                    item_id=param.code,
                    sponsor=sponsor,
                    plan=plan
                ).first()
                rate = f"{existing.rate:.2f}" if existing else f"{param.base_price:.2f}"
                writer.writerow([
                    param.name,
                    param.code,
                    'Parameter',
                    param.category or 'General',
                    rate,
                    sponsor_code,
                    plan_code,
                    notes_text
                ])

        filename = f"lab_tariffs_{template_type}_{sponsor_code}_{plan_code}.csv".replace(' ', '_').replace('/', '_')
        response = HttpResponse(output.getvalue(), content_type='text/csv; charset=utf-8')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# 1.2.2 Bulk Upload Laboratory Tariffs (CSV / Excel)
class BulkUploadLabTariffView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import io, csv
        default_sponsor_id = request.data.get('sponsor_id') or request.data.get('default_sponsor_id') or request.data.get('sponsor')
        default_plan_id = request.data.get('plan_id') or request.data.get('default_plan_id') or request.data.get('plan')
        default_target_type = str(request.data.get('target_type') or request.data.get('test_type') or '').strip().lower()

        is_general_default = str(default_sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none')

        default_sponsor = None
        if not is_general_default and default_sponsor_id and str(default_sponsor_id).lower() not in ('', 'all', 'null', 'none'):
            try:
                default_sponsor = Sponsor.objects.get(id=default_sponsor_id)
            except Sponsor.DoesNotExist:
                pass

        default_plan = None
        if not is_general_default and default_plan_id and str(default_plan_id).lower() not in ('', 'all', 'null', 'none'):
            try:
                default_plan = PatientPlan.objects.select_related('sponsor').get(id=default_plan_id)
                if not default_sponsor and default_plan.sponsor:
                    default_sponsor = default_plan.sponsor
            except PatientPlan.DoesNotExist:
                pass

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
                        {'detail': 'Unsupported file format. Please upload a CSV (.csv) or Excel (.xlsx, .xls) file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response(
                    {'detail': f'Error reading uploaded file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response(
                {'detail': 'No file or items array provided for bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not raw_rows:
            return Response(
                {'detail': 'The uploaded file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        all_sponsors = list(Sponsor.objects.all())
        all_plans = list(PatientPlan.objects.select_related('sponsor').all())

        sponsor_by_code = {s.code.strip().upper(): s for s in all_sponsors if s.code}
        sponsor_by_name = {s.name.strip().upper(): s for s in all_sponsors if s.name}
        sponsor_by_id = {str(s.id): s for s in all_sponsors}

        plan_by_code = {p.code.strip().upper(): p for p in all_plans if p.code}
        plan_by_name = {p.plan.strip().upper(): p for p in all_plans if p.plan}
        plan_by_id = {str(p.id): p for p in all_plans}

        param_codes = set(c.upper() for c in LabParameter.objects.values_list('code', flat=True) if c)
        param_names = set(p.strip().lower() for p in LabParameter.objects.values_list('name', flat=True) if p)
        inv_codes = set(c.upper() for c in LabInvestigation.objects.values_list('code', flat=True) if c)
        inv_names = set(p.strip().lower() for p in LabInvestigation.objects.values_list('name', flat=True) if p)

        staff = request.user if request.user.is_authenticated else User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []

        for idx, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                continue

            clean_row = {str(k).strip().lower(): v for k, v in row.items() if k is not None}

            item_name = (
                clean_row.get('item_name')
                or clean_row.get('test_name')
                or clean_row.get('item')
                or clean_row.get('name')
            )
            if not item_name or not str(item_name).strip():
                skipped.append(f"Row {idx}: Missing test item name")
                continue

            item_name = str(item_name).strip()

            rate_raw = (
                clean_row.get('tariff_rate')
                or clean_row.get('rate')
                or clean_row.get('price')
                or clean_row.get('amount')
            )
            try:
                rate_val = Decimal(str(rate_raw).replace(',', '').replace('$', '').strip())
                if rate_val < 0:
                    rate_val = Decimal('0.00')
            except Exception:
                skipped.append(f"Row {idx} ({item_name}): Invalid rate '{rate_raw}'")
                continue

            test_code = (
                clean_row.get('test_code')
                or clean_row.get('item_id')
                or clean_row.get('code')
            )
            test_code = str(test_code).strip() if test_code else ''

            # Detect test_type (Investigation/Panel vs Parameter/Single)
            test_type_raw = str(clean_row.get('test_type') or clean_row.get('type') or '').lower()
            if 'param' in test_type_raw or 'single' in test_type_raw:
                t_type = 'parameter'
            elif 'inv' in test_type_raw or 'panel' in test_type_raw:
                t_type = 'investigation'
            elif test_code and test_code.upper() in inv_codes:
                t_type = 'investigation'
            elif item_name.lower() in inv_names:
                t_type = 'investigation'
            elif test_code and test_code.upper() in param_codes:
                t_type = 'parameter'
            elif item_name.lower() in param_names:
                t_type = 'parameter'
            elif default_target_type in ('investigations', 'investigation', 'panels'):
                t_type = 'investigation'
            elif default_target_type in ('parameters', 'parameter', 'singles'):
                t_type = 'parameter'
            else:
                t_type = 'investigation'

            # Auto-fill test_code from catalog if missing in file
            if not test_code:
                if t_type == 'investigation':
                    matched_inv = LabInvestigation.objects.filter(name__iexact=item_name).first()
                    if matched_inv and matched_inv.code:
                        test_code = matched_inv.code
                else:
                    matched_param = LabParameter.objects.filter(name__iexact=item_name).first()
                    if matched_param and matched_param.code:
                        test_code = matched_param.code

            # Resolve Sponsor
            row_sponsor_code = str(clean_row.get('sponsor_code') or clean_row.get('sponsor') or '').strip().upper()
            row_plan_code = str(clean_row.get('plan_code') or clean_row.get('plan') or '').strip().upper()

            # If user explicitly selected sponsor/plan in modal, respect modal choices!
            sponsor = default_sponsor if default_sponsor else None
            plan = default_plan if default_plan else None

            if not default_sponsor and row_sponsor_code:
                if row_sponsor_code in ('GENERAL', 'SELF', 'CASH', 'NONE', '0'):
                    sponsor = None
                    plan = None
                elif row_sponsor_code in sponsor_by_code:
                    sponsor = sponsor_by_code[row_sponsor_code]
                elif row_sponsor_code in sponsor_by_name:
                    sponsor = sponsor_by_name[row_sponsor_code]
                elif row_sponsor_code in sponsor_by_id:
                    sponsor = sponsor_by_id[row_sponsor_code]

            if not default_plan and row_plan_code and sponsor is not None:
                # Find plan scoped within sponsor
                for p in all_plans:
                    if p.sponsor_id == sponsor.id and ((p.code and p.code.strip().upper() == row_plan_code) or (p.plan and p.plan.strip().upper() == row_plan_code)):
                        plan = p
                        break
                if not plan:
                    if row_plan_code in plan_by_code:
                        plan = plan_by_code[row_plan_code]
                    elif row_plan_code in plan_by_name:
                        plan = plan_by_name[row_plan_code]
                    elif row_plan_code in plan_by_id:
                        plan = plan_by_id[row_plan_code]

            # Upsert into RadioLabInventory
            existing = None
            if test_code:
                existing = RadioLabInventory.objects.filter(
                    type='L',
                    item_id=test_code,
                    sponsor=sponsor,
                    plan=plan
                ).first()
            if not existing:
                existing = RadioLabInventory.objects.filter(
                    type='L',
                    item__iexact=item_name,
                    sponsor=sponsor,
                    plan=plan
                ).first()

            if existing:
                existing.rate = rate_val
                existing.item = item_name
                if test_code:
                    existing.item_id = test_code
                existing.test_type = t_type
                existing.save()
                updated_count += 1
            else:
                RadioLabInventory.objects.create(
                    item=item_name,
                    item_id=test_code or f"LAB-{RadioLabInventory.objects.count()+1:03d}",
                    rate=rate_val,
                    type='L',
                    test_type=t_type,
                    sponsor=sponsor,
                    plan=plan,
                    staff=staff
                )
                created_count += 1

        total_processed = created_count + updated_count
        sponsor_lbl = default_sponsor.name if default_sponsor else "General Patients"
        plan_lbl = f" ({default_plan.plan})" if default_plan else ""
        msg = f"Bulk upload completed: {total_processed} tariffs processed for {sponsor_lbl}{plan_lbl} ({created_count} created, {updated_count} updated)."
        if skipped:
            msg += f" {len(skipped)} row(s) skipped due to errors."

        return Response({
            'detail': msg,
            'created': created_count,
            'updated': updated_count,
            'total_processed': total_processed,
            'skipped_count': len(skipped),
            'skipped_reasons': skipped[:10],
        })


class RadiologyChargesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = RadioLabInventory.objects.filter(type='R').select_related('sponsor', 'plan', 'plan__sponsor').order_by('item')

        tariff_type = request.query_params.get('tariff_type', '').strip().lower()
        patient_id = request.query_params.get('patient')
        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')
        search = request.query_params.get('search', '').strip()

        # If explicitly requesting general out-of-pocket tariffs
        if tariff_type == 'general' or (sponsor_id and str(sponsor_id).lower() in ('general', 'self', 'cash')):
            qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
        # If filtering for a specific patient
        elif patient_id or tariff_type == 'covered':
            if patient_id:
                try:
                    patient = PatientProfile.objects.select_related('sponsor', 'plan', 'category', 'sponsor__category').get(id=patient_id)
                    patient_sponsor = patient.sponsor
                    patient_plan = patient.plan

                    if not patient_sponsor and sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'self', 'cash'):
                        try:
                            patient_sponsor = Sponsor.objects.get(id=sponsor_id)
                        except Sponsor.DoesNotExist:
                            pass
                    if not patient_plan and plan_id and str(plan_id).lower() not in ('all', 'general', 'self', 'cash'):
                        try:
                            patient_plan = PatientPlan.objects.get(id=plan_id)
                        except PatientPlan.DoesNotExist:
                            pass

                    if tariff_type == 'general':
                        qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                    elif patient_sponsor and patient_plan:
                        qs = qs.filter(
                            (Q(sponsor=patient_sponsor) & Q(plan=patient_plan)) |
                            Q(plan=patient_plan) |
                            (Q(sponsor=patient_sponsor) & Q(plan__isnull=True))
                        )
                    elif patient_plan:
                        qs = qs.filter(plan=patient_plan)
                    elif patient_sponsor:
                        qs = qs.filter(Q(sponsor=patient_sponsor) | Q(plan__sponsor=patient_sponsor))
                    else:
                        qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                except PatientProfile.DoesNotExist:
                    if sponsor_id and str(sponsor_id).lower() != 'all':
                        qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
                    if plan_id and str(plan_id).lower() != 'all':
                        qs = qs.filter(plan_id=plan_id)
            else:
                if sponsor_id and str(sponsor_id).lower() != 'all':
                    qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
                if plan_id and str(plan_id).lower() != 'all':
                    qs = qs.filter(plan_id=plan_id)
        else:
            if sponsor_id and str(sponsor_id).lower() != 'all':
                qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
            if plan_id and str(plan_id).lower() != 'all':
                qs = qs.filter(plan_id=plan_id)

        if search:
            qs = qs.filter(
                Q(item__icontains=search) |
                Q(item_id__icontains=search)
            )

        data = []
        for item in qs:
            eff_sponsor = item.sponsor or (item.plan.sponsor if item.plan else None)
            is_gen = bool(not eff_sponsor and not item.plan)
            data.append({
                'id': item.id,
                'item': item.item,
                'item_id': item.item_id or '',
                'rate': float(item.rate),
                'sponsor_id': eff_sponsor.id if eff_sponsor else None,
                'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
                'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
                'plan_id': item.plan.id if item.plan else None,
                'plan_name': item.plan.plan if item.plan else ('General Price' if is_gen else 'All Plans'),
                'plan_code': item.plan.code if item.plan else ('GENERAL' if is_gen else ''),
                'is_general': is_gen,
                'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
            })
        return Response({'total': len(data), 'charges': data, 'results': data})

    def post(self, request):
        item_name = request.data.get('item', '').strip() or request.data.get('item_name', '').strip()
        item_id = request.data.get('item_id', '').strip()
        rate = request.data.get('rate', 0)
        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        plan_id = request.data.get('plan_id') or request.data.get('plan')

        if not item_name:
            return Response({'detail': 'Scan item name required.'}, status=status.HTTP_400_BAD_REQUEST)

        is_general = (
            not sponsor_id or
            str(sponsor_id).lower() in ('', 'general', 'self', 'cash', 'none', 'null')
        )

        plan = None
        sponsor = None

        if not is_general:
            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none'):
                try:
                    plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                except PatientPlan.DoesNotExist:
                    return Response({'detail': 'Selected Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'none'):
                try:
                    sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    return Response({'detail': 'Selected Sponsor not found.'}, status=status.HTTP_404_NOT_FOUND)
            elif plan and plan.sponsor:
                sponsor = plan.sponsor

        staff = request.user if request.user.is_authenticated else User.objects.first()

        try:
            rate_decimal = Decimal(str(rate))
            if rate_decimal < 0:
                rate_decimal = Decimal('0.00')
        except Exception:
            return Response({'detail': 'Invalid rate value.'}, status=status.HTTP_400_BAD_REQUEST)

        obj = RadioLabInventory.objects.create(
            item=item_name,
            item_id=item_id or f"RAD-{RadioLabInventory.objects.count()+1:03d}",
            rate=rate_decimal,
            type='R',
            sponsor=sponsor,
            plan=plan,
            staff=staff
        )
        eff_sponsor = obj.sponsor or (obj.plan.sponsor if obj.plan else None)
        is_gen = bool(not eff_sponsor and not obj.plan)
        return Response({
            'detail': f'Radiology charge "{obj.item}" created successfully.',
            'id': obj.id,
            'item': obj.item,
            'item_id': obj.item_id,
            'rate': float(obj.rate),
            'sponsor_id': eff_sponsor.id if eff_sponsor else None,
            'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
            'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else ('General Price' if is_gen else 'All Plans'),
            'plan_code': obj.plan.code if obj.plan else ('GENERAL' if is_gen else ''),
            'is_general': is_gen,
            'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
        }, status=status.HTTP_201_CREATED)

    def put(self, request, pk=None):
        try:
            obj = RadioLabInventory.objects.select_related('sponsor', 'plan').get(id=pk, type='R')
        except RadioLabInventory.DoesNotExist:
            return Response({'detail': 'Radiology charge not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'item' in request.data:
            obj.item = request.data['item'].strip()
        if 'rate' in request.data:
            try:
                obj.rate = Decimal(str(request.data['rate']))
            except Exception:
                return Response({'detail': 'Invalid rate format.'}, status=status.HTTP_400_BAD_REQUEST)
        if 'item_id' in request.data:
            obj.item_id = request.data['item_id'].strip()

        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        if sponsor_id is not None:
            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'none', 'null', ''):
                try:
                    obj.sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    return Response({'detail': 'Sponsor not found.'}, status=status.HTTP_404_NOT_FOUND)
            else:
                obj.sponsor = None

        plan_id = request.data.get('plan_id') or request.data.get('plan')
        if plan_id is not None:
            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none', 'null', ''):
                try:
                    obj.plan = PatientPlan.objects.get(id=plan_id)
                    if obj.plan.sponsor and not obj.sponsor:
                        obj.sponsor = obj.plan.sponsor
                except PatientPlan.DoesNotExist:
                    pass
            else:
                obj.plan = None

        obj.save()
        eff_sponsor = obj.sponsor or (obj.plan.sponsor if obj.plan else None)
        is_gen = bool(not eff_sponsor and not obj.plan)
        return Response({
            'detail': 'Radiology charge updated successfully.',
            'id': obj.id,
            'item': obj.item,
            'item_id': obj.item_id,
            'rate': float(obj.rate),
            'sponsor_id': eff_sponsor.id if eff_sponsor else None,
            'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
            'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else ('General Price' if is_gen else 'All Plans'),
            'plan_code': obj.plan.code if obj.plan else ('GENERAL' if is_gen else ''),
            'is_general': is_gen,
            'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
        })

    def delete(self, request, pk=None):
        try:
            RadioLabInventory.objects.filter(id=pk, type='R').delete()
            return Response({'detail': 'Radiology charge deleted.'})
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)



# 1.3.1 Download Radiology Tariff Template
class DownloadRadiologyTariffTemplateView(APIView):
    """
    Downloads a comprehensive CSV tariff template containing ALL active Radiology & Scan
    procedures currently registered in our database.
    If a specific sponsor and plan are requested, existing rates are prefilled; otherwise base prices apply.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.http import HttpResponse
        import io, csv
        from radio_lab.models import RadiologyProcedure, RadioLabInventory

        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')

        is_general = str(sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none')

        resolved_sponsor = None
        resolved_plan = None

        if is_general:
            sponsor_code = "GENERAL"
            plan_code = "GENERAL"
            sponsor_name = "General / Out-of-Pocket"
            plan_name = "General Tariff"
        else:
            sponsor_code = ""
            plan_code = ""
            sponsor_name = ""
            plan_name = ""

            if sponsor_id and str(sponsor_id).lower() not in ('all', 'none', ''):
                try:
                    resolved_sponsor = Sponsor.objects.get(id=sponsor_id)
                except Exception:
                    resolved_sponsor = Sponsor.objects.filter(
                        Q(code__iexact=str(sponsor_id).strip()) | Q(name__iexact=str(sponsor_id).strip())
                    ).first()
                if resolved_sponsor:
                    sponsor_code = resolved_sponsor.code or resolved_sponsor.name
                    sponsor_name = resolved_sponsor.name

            if plan_id and str(plan_id).lower() not in ('all', 'none', ''):
                try:
                    resolved_plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                except Exception:
                    resolved_plan = PatientPlan.objects.filter(
                        Q(code__iexact=str(plan_id).strip()) | Q(plan__iexact=str(plan_id).strip())
                    ).first()
                if resolved_plan:
                    plan_code = resolved_plan.code or resolved_plan.plan
                    plan_name = resolved_plan.plan
                    if not resolved_sponsor and resolved_plan.sponsor:
                        resolved_sponsor = resolved_plan.sponsor
                        sponsor_code = resolved_sponsor.code or resolved_sponsor.name
                        sponsor_name = resolved_sponsor.name
            elif resolved_sponsor:
                # If sponsor was selected but no specific plan was passed, select first plan of this sponsor
                first_plan = PatientPlan.objects.filter(sponsor=resolved_sponsor).first()
                if first_plan:
                    resolved_plan = first_plan
                    plan_code = first_plan.code or first_plan.plan
                    plan_name = first_plan.plan

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Scan Name', 'Scan Code', 'Price', 'Sponsor Code', 'Plan Code', 'Notes'])

        notes_text = "General Tariff - Pay from your purse" if is_general else f"Covered under {plan_name}"

        # Fetch existing tariffs for this sponsor/plan to pre-populate current prices if already configured
        existing_tariffs = {}
        if is_general:
            for t in RadioLabInventory.objects.filter(type='R', sponsor__isnull=True, plan__isnull=True):
                existing_tariffs[t.item.strip().lower()] = float(t.rate)
                if t.item_id:
                    existing_tariffs[t.item_id.strip().upper()] = float(t.rate)
        elif resolved_sponsor or resolved_plan:
            qs_t = RadioLabInventory.objects.filter(type='R')
            if resolved_plan:
                qs_t = qs_t.filter(plan=resolved_plan)
            elif resolved_sponsor:
                qs_t = qs_t.filter(Q(sponsor=resolved_sponsor) | Q(plan__sponsor=resolved_sponsor))
            for t in qs_t:
                existing_tariffs[t.item.strip().lower()] = float(t.rate)
                if t.item_id:
                    existing_tariffs[t.item_id.strip().upper()] = float(t.rate)

        # Retrieve ALL radiology scan procedures in database
        procedures = list(RadiologyProcedure.objects.filter(is_active=True).order_by('category', 'code', 'name'))

        # Fallback to distinct RadioLabInventory items if catalog table has no records
        if not procedures:
            distinct_inv = list(RadioLabInventory.objects.filter(type='R').values('item', 'item_id').distinct())
            for idx, inv in enumerate(distinct_inv, 1):
                p_code = inv.get('item_id') or f"RAD-{idx:03d}"
                p_name = (inv.get('item') or '').strip()
                if not p_name:
                    continue
                r_val = existing_tariffs.get(p_code.upper())
                if r_val is None:
                    r_val = existing_tariffs.get(p_name.lower(), 5000.0)
                writer.writerow([p_name, p_code, f"{r_val:.2f}", sponsor_code, plan_code, notes_text])
        else:
            for proc in procedures:
                # Pre-populate existing rate for sponsor/plan, else use procedure base price
                r_val = existing_tariffs.get(proc.code.strip().upper())
                if r_val is None:
                    r_val = existing_tariffs.get(proc.name.strip().lower())
                if r_val is None:
                    r_val = float(proc.base_price or 0.0)

                cat_note = f"[{proc.category}] {notes_text}"
                writer.writerow([proc.name, proc.code, f"{r_val:.2f}", sponsor_code, plan_code, cat_note])

        csv_content = output.getvalue()
        response = HttpResponse(csv_content, content_type='text/csv; charset=utf-8')
        safe_sponsor = str(sponsor_code).replace(' ', '_').replace('/', '_')
        safe_plan = str(plan_code).replace(' ', '_').replace('/', '_')
        filename = "radiology_tariffs_template_general.csv" if is_general else f"radiology_tariffs_template_{safe_sponsor}_{safe_plan}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


# 1.3.2 Bulk Upload Radiology Tariffs
class BulkUploadRadiologyTariffView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import csv, io, re
        from decimal import Decimal
        from django.db.models import Q
        from radio_lab.models import RadioLabInventory, RadiologyProcedure
        from patients.models import Sponsor, PatientPlan
        from users.models import User

        uploaded_file = request.FILES.get('file')
        default_sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor') or request.data.get('default_sponsor_id')
        default_plan_id = request.data.get('plan_id') or request.data.get('plan') or request.data.get('default_plan_id')

        is_general_default = str(default_sponsor_id or '').strip().lower() in ('general', 'self', 'cash', 'none')

        default_sponsor = None
        if not is_general_default and default_sponsor_id and str(default_sponsor_id).lower() not in ('', 'all', 'null', 'none'):
            try:
                default_sponsor = Sponsor.objects.get(id=default_sponsor_id)
            except Exception:
                default_sponsor = Sponsor.objects.filter(
                    Q(code__iexact=str(default_sponsor_id).strip()) | Q(name__iexact=str(default_sponsor_id).strip())
                ).first()

        default_plan = None
        if not is_general_default and default_plan_id and str(default_plan_id).lower() not in ('', 'all', 'null', 'none'):
            try:
                default_plan = PatientPlan.objects.select_related('sponsor').get(id=default_plan_id)
                if not default_sponsor and default_plan.sponsor:
                    default_sponsor = default_plan.sponsor
            except Exception:
                # If default_sponsor is known, find plan within that sponsor first!
                if default_sponsor:
                    default_plan = PatientPlan.objects.filter(sponsor=default_sponsor).filter(
                        Q(code__iexact=str(default_plan_id).strip()) | Q(plan__iexact=str(default_plan_id).strip())
                    ).first()
                if not default_plan:
                    default_plan = PatientPlan.objects.filter(
                        Q(code__iexact=str(default_plan_id).strip()) | Q(plan__iexact=str(default_plan_id).strip())
                    ).first()
                if default_plan and not default_sponsor and default_plan.sponsor:
                    default_sponsor = default_plan.sponsor

        raw_rows = []

        if uploaded_file:
            fname = uploaded_file.name.lower()
            try:
                if fname.endswith('.csv'):
                    file_bytes = uploaded_file.read()
                    text_data = None
                    for enc in ['utf-8-sig', 'utf-8', 'latin1']:
                        try:
                            text_data = file_bytes.decode(enc)
                            break
                        except Exception:
                            continue
                    if text_data is None:
                        text_data = file_bytes.decode('utf-8', errors='ignore')

                    first_line = text_data.strip().split('\n')[0] if text_data else ''
                    delimiter = ';' if (';' in first_line and first_line.count(';') > first_line.count(',')) else (
                        '\t' if ('\t' in first_line and first_line.count('\t') > first_line.count(',')) else ','
                    )
                    reader = csv.DictReader(io.StringIO(text_data), delimiter=delimiter)
                    for row in reader:
                        raw_rows.append(row)

                elif fname.endswith(('.xls', '.xlsx')):
                    import pandas as pd
                    file_bytes = uploaded_file.read()
                    df = pd.read_excel(io.BytesIO(file_bytes))

                    has_known_col = any(
                        any(c in re.sub(r'[^a-z0-9]', '', str(col).lower()) for c in ['name', 'scan', 'procedure', 'price', 'code', 'rate', 'item'])
                        for col in df.columns
                    )
                    if not has_known_col and len(df) > 0:
                        row0 = df.iloc[0]
                        has_row0_header = any(
                            any(c in re.sub(r'[^a-z0-9]', '', str(v).lower()) for c in ['name', 'scan', 'procedure', 'price', 'code', 'rate', 'item'])
                            for v in row0.values
                        )
                        if has_row0_header:
                            df.columns = [str(v).strip() for v in row0.values]
                            df = df.iloc[1:].reset_index(drop=True)

                    df = df.where(pd.notnull(df), None)
                    raw_rows = df.to_dict(orient='records')
                else:
                    return Response(
                        {'detail': 'Unsupported file format. Please upload a CSV (.csv) or Excel (.xlsx, .xls) file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response({'detail': f'Error reading uploaded file: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        elif hasattr(request, 'data') and 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response(
                {'detail': 'No file or items array provided for bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not raw_rows:
            return Response(
                {'detail': 'The uploaded file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        all_sponsors = list(Sponsor.objects.all())
        all_plans = list(PatientPlan.objects.select_related('sponsor').all())

        sponsor_by_code = {s.code.strip().upper(): s for s in all_sponsors if s.code}
        sponsor_by_name = {s.name.strip().upper(): s for s in all_sponsors if s.name}
        sponsor_by_id = {str(s.id): s for s in all_sponsors}

        plan_by_code = {p.code.strip().upper(): p for p in all_plans if p.code}
        plan_by_name = {p.plan.strip().upper(): p for p in all_plans if p.plan}
        plan_by_id = {str(p.id): p for p in all_plans}

        staff = request.user if request.user.is_authenticated else User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []

        counter = RadioLabInventory.objects.count()

        def find_field(norm_dict, candidate_keys):
            for cand in candidate_keys:
                if cand in norm_dict:
                    val = norm_dict[cand]
                    if val is not None and str(val).strip() not in ('', 'nan', 'none', 'null'):
                        return val
            for cand in candidate_keys:
                for k, val in norm_dict.items():
                    if cand in k or k in cand:
                        if val is not None and str(val).strip() not in ('', 'nan', 'none', 'null'):
                            return val
            return None

        for idx, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                continue

            non_empty_values = [v for v in row.values() if v is not None and str(v).strip() not in ('', 'nan', 'none', 'null')]
            if not non_empty_values:
                continue

            norm_row = {}
            clean_row = {}
            for k, v in row.items():
                if k is not None:
                    sk = str(k).strip().lower()
                    clean_row[sk] = v
                    clean_k = re.sub(r'[^a-z0-9]', '', sk)
                    if clean_k:
                        norm_row[clean_k] = v

            # 1. SCAN PROCEDURE / ITEM NAME
            item_name = find_field(norm_row, [
                'scanname', 'procedurename', 'name', 'itemname', 'item', 'procedure',
                'scan', 'description', 'testname', 'investigationname', 'investigation',
                'scanprocedurename', 'procedurescanname', 'title', 'service', 'servicename'
            ])

            if not item_name:
                for v in non_empty_values:
                    sv = str(v).strip()
                    if len(sv) > 2 and not re.match(r'^\d+(\.\d+)?$', sv) and not re.match(r'^[A-Z0-9]{2,6}-\d+$', sv, re.I):
                        item_name = sv
                        break

            if not item_name or not str(item_name).strip():
                skipped.append(f"Row {idx}: Missing scan procedure name")
                continue

            item_name = str(item_name).strip()

            # 2. RATE / PRICE
            rate_raw = find_field(norm_row, [
                'rate', 'tariffrate', 'price', 'amount', 'fee', 'cost',
                'charge', 'baseprice', 'basepricengn', 'pricengn'
            ])
            try:
                clean_r_str = re.sub(r'[^\d.]', '', str(rate_raw)) if rate_raw is not None else ''
                rate_val = Decimal(clean_r_str) if clean_r_str else Decimal('0.00')
                if rate_val < 0:
                    rate_val = Decimal('0.00')
            except Exception:
                skipped.append(f"Row {idx} ({item_name}): Invalid rate '{rate_raw}'")
                continue

            # 3. PROCEDURE CODE
            raw_code = find_field(norm_row, [
                'procedurecode', 'scancode', 'code', 'testcode', 'itemid',
                'scanid', 'id', 'scanprocedurecode', 'procedurescanname', 'serialnumber', 'no'
            ])
            if raw_code and str(raw_code).strip() not in ('', 'nan', 'none', 'null'):
                proc_code = str(raw_code).strip().upper()
            else:
                counter += 1
                proc_code = f"RAD-{counter:03d}"

            # 4. RESOLVE SPONSOR & PLAN
            row_sponsor_val = find_field(norm_row, [
                'sponsorcode', 'sponsor', 'sponsorname', 'hmo', 'hmocode', 'hmoname'
            ])
            is_general_row = (
                is_general_default or
                (row_sponsor_val and str(row_sponsor_val).strip().upper() in ('GENERAL', 'SELF', 'CASH', 'NONE'))
            )

            row_sponsor = None
            if not is_general_row and row_sponsor_val and str(row_sponsor_val).strip():
                raw_s = str(row_sponsor_val).strip()
                row_sponsor = (
                    sponsor_by_code.get(raw_s.upper())
                    or sponsor_by_name.get(raw_s.upper())
                    or sponsor_by_id.get(raw_s)
                )

            # Priority: Modal dropdown selection ALWAYS takes precedence when explicitly chosen!
            target_sponsor = None if is_general_row else (default_sponsor if default_sponsor else row_sponsor)

            # Similarly for Coverage Plan:
            # If the user chose a specific plan in the modal (e.g. Plan B), target_plan MUST be Plan B!
            # Never let an old plan name from the CSV file override the user's explicit modal selection.
            if is_general_row:
                target_plan = None
            elif default_plan:
                target_plan = default_plan
            else:
                row_plan_val = find_field(norm_row, [
                    'plancode', 'plan', 'planname', 'coverageplan', 'package'
                ])
                row_plan = None
                if row_plan_val and str(row_plan_val).strip():
                    raw_p = str(row_plan_val).strip().upper()
                    # Resolve within target_sponsor first if sponsor is known
                    if target_sponsor:
                        for p in all_plans:
                            if p.sponsor_id == target_sponsor.id:
                                if (p.code and p.code.strip().upper() == raw_p) or (p.plan and p.plan.strip().upper() == raw_p) or str(p.id) == raw_p:
                                    row_plan = p
                                    break
                    if not row_plan:
                        row_plan = (
                            plan_by_code.get(raw_p)
                            or plan_by_name.get(raw_p)
                            or plan_by_id.get(raw_p)
                        )
                target_plan = row_plan

            if target_plan and target_plan.sponsor and not target_sponsor:
                target_sponsor = target_plan.sponsor

            if not is_general_row and not target_sponsor and not target_plan:
                # If no sponsor or plan is specified in file or dropdown, default to General Out-of-Pocket tariff
                is_general_row = True

            # 5. STRICT DUPLICATE PREVENTION & UPDATE
            has_explicit_code = raw_code and str(raw_code).strip() not in ('', 'nan', 'none', 'null')
            if is_general_row:
                # General Tariff: sponsor=None, plan=None
                existing = None
                if has_explicit_code:
                    existing = RadioLabInventory.objects.filter(
                        type='R', sponsor__isnull=True, plan__isnull=True, item_id__iexact=proc_code
                    ).first()
                if not existing:
                    existing = RadioLabInventory.objects.filter(
                        type='R', sponsor__isnull=True, plan__isnull=True, item__iexact=item_name
                    ).first()

                if existing:
                    existing.rate = rate_val
                    existing.item = item_name
                    if has_explicit_code:
                        existing.item_id = proc_code
                    existing.sponsor = None
                    existing.plan = None
                    existing.staff = staff
                    existing.save()
                    updated_count += 1
                else:
                    RadioLabInventory.objects.create(
                        item=item_name,
                        item_id=proc_code,
                        rate=rate_val,
                        type='R',
                        sponsor=None,
                        plan=None,
                        staff=staff
                    )
                    created_count += 1
            else:
                # HMO Tariff: linked to specific Sponsor and/or Plan
                existing = None
                if has_explicit_code:
                    existing = RadioLabInventory.objects.filter(
                        type='R', sponsor=target_sponsor, plan=target_plan, item_id__iexact=proc_code
                    ).first()
                if not existing:
                    existing = RadioLabInventory.objects.filter(
                        type='R', sponsor=target_sponsor, plan=target_plan, item__iexact=item_name
                    ).first()

                if existing:
                    existing.rate = rate_val
                    existing.item = item_name
                    if has_explicit_code:
                        existing.item_id = proc_code
                    existing.staff = staff
                    existing.save()
                    updated_count += 1
                else:
                    RadioLabInventory.objects.create(
                        item=item_name,
                        item_id=proc_code,
                        rate=rate_val,
                        type='R',
                        sponsor=target_sponsor,
                        plan=target_plan,
                        staff=staff
                    )
                    created_count += 1

                # Safe sync with master RadiologyProcedure catalog (without throwing IntegrityError on unique code)
                proc_master = RadiologyProcedure.objects.filter(
                    Q(code__iexact=proc_code) | Q(name__iexact=item_name)
                ).first()
                if not proc_master:
                    unique_c = proc_code
                    if RadiologyProcedure.objects.filter(code__iexact=unique_c).exists():
                        rad_c = RadiologyProcedure.objects.count() + 1
                        unique_c = f"RAD-{rad_c:03d}"
                        while RadiologyProcedure.objects.filter(code__iexact=unique_c).exists():
                            rad_c += 1
                            unique_c = f"RAD-{rad_c:03d}"
                    RadiologyProcedure.objects.create(
                        code=unique_c,
                        name=item_name,
                        base_price=rate_val,
                        is_active=True
                    )
                elif proc_master.base_price <= 0 and rate_val > 0:
                    proc_master.base_price = rate_val
                    proc_master.save(update_fields=['base_price'])

        detail_msg = f"Bulk upload completed: {created_count} tariff(s) created, {updated_count} updated."
        if skipped:
            detail_msg += f" ({len(skipped)} row(s) skipped)."

        return Response({
            'detail': detail_msg,
            'created': created_count,
            'updated': updated_count,
            'skipped_count': len(skipped),
            'skipped': skipped[:10],
            'total_processed': created_count + updated_count
        }, status=status.HTTP_200_OK)

class AdmissionFeesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        wards = Ward.objects.all().order_by('ward_name')
        data = [{'id': w.id, 'ward_name': w.ward_name, 'price': w.price} for w in wards]
        return Response({'total': len(data), 'wards': data})

    def post(self, request):
        ward_name = request.data.get('ward_name', '').strip()
        price = request.data.get('price', 0)

        if not ward_name:
            return Response({'detail': 'Ward name required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            price = int(price)
            if price < 0:
                return Response({'detail': 'Price cannot be negative.'}, status=status.HTTP_400_BAD_REQUEST)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        if Ward.objects.filter(ward_name__iexact=ward_name).exists():
            return Response({'detail': f'Ward "{ward_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        w = Ward.objects.create(ward_name=ward_name, price=price)
        return Response({'detail': f'Ward "{w.ward_name}" created.', 'id': w.id, 'ward_name': w.ward_name, 'price': w.price})

    def put(self, request, pk=None):
        try:
            w = Ward.objects.get(id=pk)
        except Ward.DoesNotExist:
            return Response({'detail': 'Ward not found.'}, status=status.HTTP_404_NOT_FOUND)

        ward_name = request.data.get('ward_name', w.ward_name).strip()
        price = request.data.get('price', w.price)

        if Ward.objects.filter(ward_name__iexact=ward_name).exclude(id=pk).exists():
            return Response({'detail': f'Ward with name "{ward_name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            w.price = int(price)
        except (ValueError, TypeError):
            return Response({'detail': 'Invalid price format.'}, status=status.HTTP_400_BAD_REQUEST)

        w.ward_name = ward_name
        w.save()
        return Response({'detail': 'Ward updated.', 'id': w.id, 'ward_name': w.ward_name, 'price': w.price})

    def delete(self, request, pk=None):
        try:
            Ward.objects.filter(id=pk).delete()
            return Response({'detail': 'Ward deleted.'})
        except Exception as e:
            return Response({'detail': str(e)}, status=status.HTTP_400_BAD_REQUEST)


# 1.5 Other Services Fees
class OtherServicesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = OtherService2.objects.all().select_related('plan', 'plan__sponsor').order_by('service')
        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')
        patient_id = request.query_params.get('patient')
        search = request.query_params.get('search', '').strip()

        if patient_id:
            try:
                patient = PatientProfile.objects.select_related('plan').get(id=patient_id)
                if patient.plan:
                    qs = qs.filter(Q(plan=patient.plan) | Q(plan__isnull=True))
                else:
                    qs = qs.filter(plan__isnull=True)
            except PatientProfile.DoesNotExist:
                pass
        else:
            if sponsor_id and str(sponsor_id).lower() != 'all':
                if str(sponsor_id).lower() == 'general':
                    qs = qs.filter(plan__isnull=True)
                else:
                    qs = qs.filter(plan__sponsor_id=sponsor_id)
            if plan_id and str(plan_id).lower() != 'all':
                if str(plan_id).lower() == 'general':
                    qs = qs.filter(plan__isnull=True)
                else:
                    qs = qs.filter(plan_id=plan_id)

        if search:
            qs = qs.filter(Q(service__icontains=search) | Q(service_id__icontains=search))

        data = []
        for s in qs:
            sponsor = s.plan.sponsor if s.plan and s.plan.sponsor else None
            data.append({
                'id': s.id,
                'service': s.service,
                'service_id': s.service_id or '',
                'rate': float(s.rate),
                'plan_id': s.plan.id if s.plan else None,
                'plan_name': s.plan.plan if s.plan else 'All Plans / Self-Pay',
                'sponsor_id': sponsor.id if sponsor else None,
                'sponsor_name': sponsor.name if sponsor else 'General (Self-Pay)',
                'sponsor_code': sponsor.code if sponsor and sponsor.code else '',
            })
        return Response({'total': len(data), 'services': data, 'results': data})

    def post(self, request):
        service = str(request.data.get('service') or '').strip()
        service_id = str(request.data.get('service_id') or '').strip()
        rate = request.data.get('rate', 0)
        plan_id = request.data.get('plan_id')
        sponsor_id = request.data.get('sponsor_id')

        if not service:
            return Response({'detail': 'Service / Procedure description is required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            rate_val = Decimal(str(rate)) if rate not in (None, '') else Decimal('0.00')
        except Exception:
            return Response({'detail': 'Please enter a valid rate amount.'}, status=status.HTTP_400_BAD_REQUEST)

        plan = None
        if plan_id and str(plan_id).lower() not in ('general', 'null', 'none', ''):
            try:
                plan = PatientPlan.objects.get(id=plan_id)
            except PatientPlan.DoesNotExist:
                pass

        # Generate unique service_id if not provided, or check for conflict
        if not service_id:
            cand_count = OtherService2.objects.count() + 1
            cand_id = f"SRV-{cand_count:03d}"
            while OtherService2.objects.filter(service_id=cand_id, plan=plan).exists():
                cand_count += 1
                cand_id = f"SRV-{cand_count:03d}"
            service_id = cand_id
        else:
            if OtherService2.objects.filter(service_id=service_id, plan=plan).exists():
                return Response({'detail': f'Service code "{service_id}" already exists for this plan.'}, status=status.HTTP_400_BAD_REQUEST)

        staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        if not staff:
            staff = User.objects.first()

        obj = OtherService2.objects.create(
            service=service,
            service_id=service_id,
            rate=rate_val,
            plan=plan,
            staff=staff
        )
        sponsor = obj.plan.sponsor if obj.plan and obj.plan.sponsor else None
        return Response({
            'detail': f'Service "{obj.service}" created successfully.',
            'id': obj.id,
            'service': obj.service,
            'service_id': obj.service_id,
            'rate': float(obj.rate),
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else 'All Plans / Self-Pay',
            'sponsor_id': sponsor.id if sponsor else None,
            'sponsor_name': sponsor.name if sponsor else 'General (Self-Pay)',
            'sponsor_code': sponsor.code if sponsor and sponsor.code else '',
        })

    def put(self, request, pk=None):
        try:
            obj = OtherService2.objects.get(id=pk)
        except OtherService2.DoesNotExist:
            return Response({'detail': 'Service not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'service' in request.data:
            s = str(request.data['service']).strip()
            if not s:
                return Response({'detail': 'Service / Procedure description cannot be empty.'}, status=status.HTTP_400_BAD_REQUEST)
            obj.service = s

        if 'rate' in request.data:
            r = request.data['rate']
            try:
                obj.rate = Decimal(str(r)) if r not in (None, '') else Decimal('0.00')
            except Exception:
                return Response({'detail': 'Please enter a valid rate amount.'}, status=status.HTTP_400_BAD_REQUEST)

        if 'plan_id' in request.data:
            p_id = request.data['plan_id']
            if p_id and str(p_id).lower() not in ('general', 'null', 'none', ''):
                try:
                    obj.plan = PatientPlan.objects.get(id=p_id)
                except PatientPlan.DoesNotExist:
                    obj.plan = None
            else:
                obj.plan = None

        if 'service_id' in request.data:
            sid = str(request.data['service_id']).strip()
            if sid and sid != obj.service_id:
                if OtherService2.objects.filter(service_id=sid, plan=obj.plan).exclude(id=obj.id).exists():
                    return Response({'detail': f'Service code "{sid}" already exists for this plan.'}, status=status.HTTP_400_BAD_REQUEST)
                obj.service_id = sid

        obj.save()
        sponsor = obj.plan.sponsor if obj.plan and obj.plan.sponsor else None
        return Response({
            'detail': f'Service "{obj.service}" updated successfully.',
            'id': obj.id,
            'service': obj.service,
            'service_id': obj.service_id,
            'rate': float(obj.rate),
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else 'All Plans / Self-Pay',
            'sponsor_id': sponsor.id if sponsor else None,
            'sponsor_name': sponsor.name if sponsor else 'General (Self-Pay)',
            'sponsor_code': sponsor.code if sponsor and sponsor.code else '',
        })

    def delete(self, request, pk=None):
        OtherService2.objects.filter(id=pk).delete()
        return Response({'detail': 'Service deleted.'})


class DownloadOtherServiceTariffTemplateView(APIView):
    """
    Downloads a CSV tariff template for Other Hospital Services & Procedures.
    - If template_type='master' or sponsor is General: outputs master catalog template with sample or existing master procedures.
    - If sponsor and plan are provided: outputs pre-filled template with ALL existing hospital services in database,
      prefilled with existing plan rates (or baseline rates) so user only edits prices and uploads.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.http import HttpResponse
        import io, csv

        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')
        template_type = request.query_params.get('template_type', '').strip().lower()

        is_general = str(sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none') or template_type == 'master'

        resolved_sponsor = None
        resolved_plan = None

        if is_general:
            sponsor_code = "GENERAL"
            plan_code = "GENERAL"
            sponsor_name = "General / Out-of-Pocket"
            plan_name = "General Tariff"
        else:
            sponsor_code = "AMH"
            plan_code = "AIICO SILVER"
            sponsor_name = "AIICO MULTISHIELD (AMH)"
            plan_name = "AIICO SILVER"

            if sponsor_id and str(sponsor_id).lower() not in ('all', '', 'none', 'null'):
                try:
                    resolved_sponsor = Sponsor.objects.get(id=sponsor_id)
                    sponsor_code = resolved_sponsor.code or resolved_sponsor.name
                    sponsor_name = resolved_sponsor.name
                except Sponsor.DoesNotExist:
                    pass

            if plan_id and str(plan_id).lower() not in ('all', '', 'none', 'null'):
                try:
                    resolved_plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                    plan_code = resolved_plan.code or resolved_plan.plan
                    plan_name = resolved_plan.plan
                    if resolved_plan.sponsor:
                        sponsor_code = resolved_plan.sponsor.code or resolved_plan.sponsor.name
                        sponsor_name = resolved_plan.sponsor.name
                except PatientPlan.DoesNotExist:
                    pass

        output = io.StringIO()
        writer = csv.writer(output)

        # Existing distinct services from database
        existing_services = list(OtherService2.objects.values('service', 'service_id', 'rate', 'plan_id').order_by('service'))
        master_dict = {}
        for s in existing_services:
            name = (s['service'] or '').strip()
            if name and name.lower() not in master_dict:
                master_dict[name.lower()] = {
                    'service': name,
                    'service_id': s['service_id'] or '',
                    'rate': s['rate'] or '0.00',
                }

        # If specific plan requested, get existing tariff rates for that plan
        plan_rates = {}
        if resolved_plan:
            for s in existing_services:
                if s['plan_id'] == resolved_plan.id:
                    plan_rates[(s['service'] or '').strip().lower()] = s['rate']

        if is_general and len(master_dict) == 0:
            writer.writerow(['service_name', 'service_code', 'rate', 'notes'])
            samples = [
                ['Wound Dressing (Major)', 'SRV-001', '5000.00', 'Clinical Procedure'],
                ['Wound Dressing (Minor)', 'SRV-002', '2500.00', 'Clinical Procedure'],
                ['Intravenous (IV) Cannulation', 'SRV-003', '2000.00', 'Nursing Procedure'],
                ['Urethral Catheterization (Male/Female)', 'SRV-004', '3500.00', 'Clinical Procedure'],
                ['Nebulization Therapy', 'SRV-005', '3000.00', 'Respiratory Care'],
                ['Suture Removal', 'SRV-006', '2000.00', 'Minor Procedure'],
                ['Ear Syringing (Unilateral/Bilateral)', 'SRV-007', '4500.00', 'ENT Procedure'],
                ['Incision and Drainage (I&D)', 'SRV-008', '12000.00', 'Surgical Procedure'],
                ['Stomach Wash / Gastric Lavage', 'SRV-009', '8000.00', 'Emergency Procedure'],
                ['Foreign Body Removal (Ear/Nose/Eye)', 'SRV-010', '5000.00', 'Clinical Procedure'],
                ['Burn Dressing (Minor)', 'SRV-011', '4000.00', 'Clinical Procedure'],
                ['Episiotomy Repair', 'SRV-012', '15000.00', 'Obstetric Procedure'],
            ]
            for row in samples:
                writer.writerow(row)
            filename = 'hospital_services_master_template.csv'
        elif is_general:
            writer.writerow(['service_name', 'service_code', 'rate', 'notes'])
            for item in master_dict.values():
                writer.writerow([item['service'], item['service_id'], item['rate'], 'General Master Procedure'])
            filename = 'hospital_services_master_template.csv'
        else:
            writer.writerow(['service_name', 'service_code', 'rate', 'sponsor_code', 'plan_code', 'notes'])
            for item in master_dict.values():
                rate = plan_rates.get(item['service'].lower(), item['rate'])
                writer.writerow([item['service'], item['service_id'], rate, sponsor_code, plan_code, f'Tariff for {plan_name}'])
            filename = f"other_services_tariffs_{sponsor_code}_{plan_code}.csv"

        response = HttpResponse(output.getvalue(), content_type='text/csv')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response


class BulkUploadOtherServiceTariffView(APIView):
    """
    Bulk imports hospital services & procedure tariffs from CSV or Excel files.
    - If sponsor and plan provided (or mapped from file), assigns negotiated tariffs to that sponsor & plan.
    - If general / no sponsor, creates or updates master catalog services.
    - Matches existing services by code or name to update rates, or inserts new services.
    """
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import csv, io
        uploaded_file = request.FILES.get('file')
        default_sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor') or request.data.get('default_sponsor_id')
        default_plan_id = request.data.get('plan_id') or request.data.get('plan') or request.data.get('default_plan_id')

        is_general_default = str(default_sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none')

        default_sponsor = None
        if not is_general_default and default_sponsor_id and str(default_sponsor_id).lower() not in ('', 'all', 'null', 'none'):
            try:
                default_sponsor = Sponsor.objects.get(id=default_sponsor_id)
            except (Sponsor.DoesNotExist, ValueError):
                pass

        default_plan = None
        if not is_general_default and default_plan_id and str(default_plan_id).lower() not in ('', 'all', 'null', 'none', 'general'):
            try:
                default_plan = PatientPlan.objects.select_related('sponsor').get(id=default_plan_id)
                if not default_sponsor and default_plan.sponsor:
                    default_sponsor = default_plan.sponsor
            except (PatientPlan.DoesNotExist, ValueError):
                pass

        raw_rows = []

        if uploaded_file:
            fname = uploaded_file.name.lower()
            try:
                if fname.endswith('.csv'):
                    file_data = uploaded_file.read().decode('utf-8-sig', errors='ignore')
                    reader = csv.DictReader(io.StringIO(file_data))
                    for row in reader:
                        raw_rows.append(row)
                elif fname.endswith(('.xls', '.xlsx')):
                    import pandas as pd
                    df = pd.read_excel(io.BytesIO(uploaded_file.read()))
                    df = df.where(pd.notnull(df), None)
                    raw_rows = df.to_dict(orient='records')
                else:
                    return Response(
                        {'detail': 'Unsupported file format. Please upload a CSV (.csv) or Excel (.xlsx, .xls) file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response({'detail': f'Error reading uploaded file: {str(e)}'}, status=status.HTTP_400_BAD_REQUEST)
        elif 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response({'detail': 'No file or items data provided for bulk upload.'}, status=status.HTTP_400_BAD_REQUEST)

        if not raw_rows:
            return Response({'detail': 'The uploaded file contains no data rows.'}, status=status.HTTP_400_BAD_REQUEST)

        # In-memory caches for fast lookup
        all_sponsors = list(Sponsor.objects.all())
        all_plans = list(PatientPlan.objects.select_related('sponsor').all())

        sponsor_by_code = {s.code.strip().upper(): s for s in all_sponsors if s.code}
        sponsor_by_name = {s.name.strip().upper(): s for s in all_sponsors if s.name}
        sponsor_by_id = {str(s.id): s for s in all_sponsors}

        plan_by_code = {p.code.strip().upper(): p for p in all_plans if p.code}
        plan_by_name = {p.plan.strip().upper(): p for p in all_plans if p.plan}
        plan_by_id = {str(p.id): p for p in all_plans}

        staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        if not staff:
            staff = User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []

        counter = OtherService2.objects.count()

        for idx, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                continue

            clean_row = {str(k).strip().lower(): v for k, v in row.items() if k is not None}

            service_name = (
                clean_row.get('service_name')
                or clean_row.get('service')
                or clean_row.get('procedure_name')
                or clean_row.get('procedure')
                or clean_row.get('name')
                or clean_row.get('item_name')
                or clean_row.get('item')
            )
            if not service_name or not str(service_name).strip():
                skipped.append(f"Row {idx}: missing service name")
                continue

            service_name = str(service_name).strip()

            raw_code = clean_row.get('service_code') or clean_row.get('service_id') or clean_row.get('code') or clean_row.get('sku') or clean_row.get('item_id')
            service_code = str(raw_code).strip() if raw_code else ""

            raw_rate = clean_row.get('rate') or clean_row.get('tariff_rate') or clean_row.get('price') or clean_row.get('tariff') or clean_row.get('fee') or clean_row.get('cost')
            try:
                rate_val = Decimal(str(raw_rate)) if raw_rate not in (None, '') else Decimal('0.00')
            except Exception:
                rate_val = Decimal('0.00')

            # Determine sponsor & plan for this row
            target_plan = default_plan
            target_sponsor = default_sponsor

            row_sponsor_val = str(clean_row.get('sponsor_code') or clean_row.get('sponsor_name') or clean_row.get('sponsor') or '').strip().upper()
            row_plan_val = str(clean_row.get('plan_code') or clean_row.get('plan_name') or clean_row.get('plan') or '').strip().upper()

            if row_sponsor_val in ('GENERAL', 'SELF', 'CASH', 'NONE') or row_plan_val in ('GENERAL', 'SELF', 'CASH', 'NONE'):
                target_plan = None
                target_sponsor = None
            else:
                if row_plan_val:
                    target_plan = (
                        plan_by_code.get(row_plan_val)
                        or plan_by_name.get(row_plan_val)
                        or plan_by_id.get(row_plan_val)
                        or target_plan
                    )
                if row_sponsor_val:
                    target_sponsor = (
                        sponsor_by_code.get(row_sponsor_val)
                        or sponsor_by_name.get(row_sponsor_val)
                        or sponsor_by_id.get(row_sponsor_val)
                        or (target_plan.sponsor if target_plan else target_sponsor)
                    )

            if target_sponsor and not target_plan:
                sponsor_plans = [p for p in all_plans if p.sponsor_id == target_sponsor.id]
                if sponsor_plans:
                    target_plan = sponsor_plans[0]

            # Look up existing record
            existing = None
            if service_code:
                existing = OtherService2.objects.filter(service_id=service_code, plan=target_plan).first()
            if not existing:
                existing = OtherService2.objects.filter(service__iexact=service_name, plan=target_plan).first()

            if existing:
                existing.rate = rate_val
                if service_code and not existing.service_id:
                    existing.service_id = service_code
                existing.save()
                updated_count += 1
            else:
                if not service_code:
                    counter += 1
                    cand_id = f"SRV-{counter:03d}"
                    while OtherService2.objects.filter(service_id=cand_id, plan=target_plan).exists():
                        counter += 1
                        cand_id = f"SRV-{counter:03d}"
                    service_code = cand_id

                OtherService2.objects.create(
                    service=service_name,
                    service_id=service_code,
                    rate=rate_val,
                    plan=target_plan,
                    staff=staff
                )
                created_count += 1

        target_label = f" for {default_plan.plan}" if default_plan else (" (General Self-Pay)" if is_general_default else "")
        return Response({
            'detail': f'Bulk upload completed{target_label}: {created_count} service(s) created, {updated_count} tariff(s) updated.',
            'created': created_count,
            'updated': updated_count,
            'skipped_count': len(skipped),
            'skipped': skipped[:10],
        })


# ==========================================================
# 2. PRODUCT TARIFFS
# ==========================================================

# 2.1 Medication Fees (Pharmacy Tariff)
class MedicationFeesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        qs = PharmacyTariff.objects.all().select_related('sponsor', 'plan', 'plan__sponsor').order_by('product_name')

        tariff_type = request.query_params.get('tariff_type', '').strip().lower()
        patient_id = request.query_params.get('patient')
        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')
        search = request.query_params.get('search', '').strip()

        # If explicitly requesting general out-of-pocket tariffs
        if tariff_type == 'general' or (sponsor_id and str(sponsor_id).lower() in ('general', 'self', 'cash')):
            qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
        # If filtering for a specific patient
        elif patient_id or tariff_type == 'covered':
            if patient_id:
                try:
                    patient = PatientProfile.objects.select_related('sponsor', 'plan', 'category', 'sponsor__category').get(id=patient_id)
                    patient_sponsor = patient.sponsor
                    patient_plan = patient.plan

                    if not patient_sponsor and sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'self', 'cash'):
                        try:
                            patient_sponsor = Sponsor.objects.get(id=sponsor_id)
                        except Sponsor.DoesNotExist:
                            pass
                    if not patient_plan and plan_id and str(plan_id).lower() not in ('all', 'general', 'self', 'cash'):
                        try:
                            patient_plan = PatientPlan.objects.get(id=plan_id)
                        except PatientPlan.DoesNotExist:
                            pass

                    if tariff_type == 'general':
                        qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                    elif patient_sponsor and patient_plan:
                        qs = qs.filter(
                            (Q(sponsor=patient_sponsor) & Q(plan=patient_plan)) |
                            Q(plan=patient_plan) |
                            (Q(sponsor=patient_sponsor) & Q(plan__isnull=True))
                        )
                    elif patient_plan:
                        qs = qs.filter(plan=patient_plan)
                    elif patient_sponsor:
                        qs = qs.filter(Q(sponsor=patient_sponsor) | Q(plan__sponsor=patient_sponsor))
                    else:
                        qs = qs.filter(sponsor__isnull=True, plan__isnull=True)
                except PatientProfile.DoesNotExist:
                    if sponsor_id and str(sponsor_id).lower() != 'all':
                        qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
                    if plan_id and str(plan_id).lower() != 'all':
                        qs = qs.filter(plan_id=plan_id)
            else:
                if sponsor_id and str(sponsor_id).lower() != 'all':
                    qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
                if plan_id and str(plan_id).lower() != 'all':
                    qs = qs.filter(plan_id=plan_id)
        else:
            if sponsor_id and str(sponsor_id).lower() != 'all':
                qs = qs.filter(Q(sponsor_id=sponsor_id) | Q(plan__sponsor_id=sponsor_id))
            if plan_id and str(plan_id).lower() != 'all':
                qs = qs.filter(plan_id=plan_id)

        if search:
            qs = qs.filter(
                Q(product_name__icontains=search) |
                Q(product_id__icontains=search)
            )

        data = []
        for p in qs:
            eff_sponsor = p.sponsor or (p.plan.sponsor if p.plan else None)
            is_gen = bool(not eff_sponsor and not p.plan)
            data.append({
                'id': p.id,
                'product_name': p.product_name,
                'product_id': p.product_id,
                'sku': p.product_id,
                'rate': float(p.rate),
                'sponsor_id': eff_sponsor.id if eff_sponsor else None,
                'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
                'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
                'plan_id': p.plan.id if p.plan else None,
                'plan_name': p.plan.plan if p.plan else ('General Price' if is_gen else 'All Plans'),
                'plan_code': p.plan.code if p.plan else ('GENERAL' if is_gen else ''),
                'is_general': is_gen,
                'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
            })
        return Response({'total': len(data), 'medications': data, 'results': data})

    def post(self, request):
        product_name = request.data.get('product_name', '').strip()
        product_id = request.data.get('product_id', '').strip()
        rate = request.data.get('rate', 0)
        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        plan_id = request.data.get('plan_id') or request.data.get('plan')

        if not product_name:
            return Response({'detail': 'Product name required.'}, status=status.HTTP_400_BAD_REQUEST)

        is_general = (
            not sponsor_id or
            str(sponsor_id).lower() in ('', 'general', 'self', 'cash', 'none', 'null')
        )

        plan = None
        sponsor = None

        if not is_general:
            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none'):
                try:
                    plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                except PatientPlan.DoesNotExist:
                    return Response({'detail': 'Selected Plan not found.'}, status=status.HTTP_404_NOT_FOUND)

            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'none'):
                try:
                    sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    return Response({'detail': 'Selected Sponsor not found.'}, status=status.HTTP_404_NOT_FOUND)
            elif plan and plan.sponsor:
                sponsor = plan.sponsor

        staff = request.user if request.user.is_authenticated else User.objects.first()

        if not product_id or not str(product_id).strip():
            existing_prod = Product.objects.filter(product_name__iexact=product_name).first()
            if existing_prod and existing_prod.product_id:
                product_id = existing_prod.product_id
            else:
                existing_t = PharmacyTariff.objects.filter(product_name__iexact=product_name).exclude(product_id__isnull=True).exclude(product_id='').first()
                if existing_t and existing_t.product_id:
                    product_id = existing_t.product_id
                else:
                    from inventory.utils import get_next_isl_sku
                    product_id = get_next_isl_sku()

        obj = PharmacyTariff.objects.create(
            product_name=product_name,
            product_id=product_id,
            rate=Decimal(str(rate)),
            sponsor=sponsor,
            plan=plan,
            staff=staff
        )

        Product.objects.get_or_create(
            product_name=product_name,
            defaults={
                'product_id': product_id,
                'price': Decimal(str(rate)),
                'stock': 0,
                'staff': staff,
            }
        )

        eff_sponsor = obj.sponsor or (obj.plan.sponsor if obj.plan else None)
        is_gen = bool(not eff_sponsor and not obj.plan)
        return Response({
            'detail': f'Medication tariff "{obj.product_name}" created successfully.',
            'id': obj.id,
            'product_name': obj.product_name,
            'product_id': obj.product_id,
            'rate': float(obj.rate),
            'sponsor_id': eff_sponsor.id if eff_sponsor else None,
            'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
            'sponsor_code': eff_sponsor.code if eff_sponsor else 'GENERAL',
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else ('General Price' if is_gen else 'All Plans'),
            'is_general': is_gen,
            'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
        }, status=status.HTTP_201_CREATED)

    def put(self, request, pk=None):
        try:
            obj = PharmacyTariff.objects.select_related('sponsor', 'plan').get(id=pk)
        except PharmacyTariff.DoesNotExist:
            return Response({'detail': 'Medication tariff not found.'}, status=status.HTTP_404_NOT_FOUND)

        pin = request.data.get('pin') or request.data.get('security_pin')
        staff_user = None
        if pin and str(pin).strip():
            raw_pin = str(pin).strip()
            if request.user and request.user.is_authenticated and hasattr(request.user, 'check_pin') and getattr(request.user, 'has_pin', False) and request.user.check_pin(raw_pin):
                staff_user = request.user
            else:
                for u in User.objects.filter(is_active=True):
                    if hasattr(u, 'check_pin') and getattr(u, 'has_pin', False) and u.check_pin(raw_pin):
                        staff_user = u
                        break
            if not staff_user:
                return Response({'detail': 'Incorrect Security PIN. Authorization denied.'}, status=status.HTTP_400_BAD_REQUEST)
        elif request.user and request.user.is_authenticated:
            staff_user = request.user

        if staff_user:
            obj.staff = staff_user

        if 'product_name' in request.data:
            obj.product_name = request.data['product_name'].strip()
        if 'rate' in request.data:
            obj.rate = Decimal(str(request.data['rate']))
        if 'product_id' in request.data:
            obj.product_id = request.data['product_id'].strip()

        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        if sponsor_id is not None:
            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'self', 'none', 'null'):
                try:
                    obj.sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    pass
            else:
                obj.sponsor = None

        plan_id = request.data.get('plan_id') or request.data.get('plan')
        if plan_id is not None:
            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none', 'null'):
                try:
                    obj.plan = PatientPlan.objects.get(id=plan_id)
                    if obj.plan.sponsor and not obj.sponsor:
                        obj.sponsor = obj.plan.sponsor
                except PatientPlan.DoesNotExist:
                    pass
            else:
                obj.plan = None

        obj.save()
        eff_sponsor = obj.sponsor or (obj.plan.sponsor if obj.plan else None)
        is_gen = bool(not eff_sponsor and not obj.plan)
        return Response({
            'detail': 'Medication tariff updated successfully.',
            'id': obj.id,
            'product_name': obj.product_name,
            'product_id': obj.product_id,
            'rate': float(obj.rate),
            'sponsor_id': eff_sponsor.id if eff_sponsor else None,
            'sponsor_name': eff_sponsor.name if eff_sponsor else 'General / Self-Pay',
            'plan_id': obj.plan.id if obj.plan else None,
            'plan_name': obj.plan.plan if obj.plan else ('General Price' if is_gen else 'All Plans'),
            'is_general': is_gen,
            'payment_label': 'Pay from your purse' if is_gen else 'Covered by Plan',
        })

    def delete(self, request, pk=None):
        PharmacyTariff.objects.filter(id=pk).delete()
        return Response({'detail': 'Medication tariff deleted.'})


# 2.1b Load / Sync General Medication Prices (Hospital Formulary / Inventory Standard Prices)
class LoadGeneralMedicationPricesView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from inventory.models import Product, PharmacyTariff
        from django.db.models import Max

        staff = request.user if request.user.is_authenticated else User.objects.first()
        created_count = 0
        updated_count = 0

        # Baseline clinical formulary prices for general self-pay patients
        BASELINE_MED_PRICES = {
            'Paracetamol 500mg Tablet': ('ISL-001', Decimal('500.00')),
            'Amoxicillin 500mg Capsule': ('ISL-002', Decimal('1200.00')),
            'Artemether/Lumefantrine 20/120mg (Coartem)': ('ISL-003', Decimal('2500.00')),
            'Ciprofloxacin 500mg Tablet': ('ISL-004', Decimal('1800.00')),
            'Metformin 500mg Tablet': ('ISL-005', Decimal('950.00')),
            'Amlodipine 5mg Tablet': ('ISL-006', Decimal('1400.00')),
            'Ibuprofen 400mg Tablet': ('ISL-007', Decimal('600.00')),
            'Omeprazole 20mg Capsule': ('ISL-008', Decimal('1100.00')),
            'Ceftriaxone 1g Injection': ('ISL-009', Decimal('3500.00')),
            'Oral Rehydration Salts (ORS) Sachet': ('ISL-010', Decimal('300.00')),
            'Dextromethorphan Syrup': ('ISL-011', Decimal('1500.00')),
        }

        # 0. Migrate any legacy MED- SKUs to ISL-
        for p in Product.objects.filter(product_id__icontains='MED-'):
            p.product_id = p.product_id.replace('MED-', 'ISL-').replace('med-', 'ISL-')[:13]
            p.save(update_fields=['product_id'])
        for t in PharmacyTariff.objects.filter(product_id__icontains='MED-'):
            t.product_id = t.product_id.replace('MED-', 'ISL-').replace('med-', 'ISL-')[:13]
            t.save(update_fields=['product_id'])

        # 1. Sync from inventory Product model if any exist
        inv_products = Product.objects.filter(price__gt=0)
        for prod in inv_products:
            sku = prod.product_id or f"SKU-{prod.id:04d}"
            tariff, created = PharmacyTariff.objects.get_or_create(
                product_name=prod.product_name,
                sponsor__isnull=True,
                plan__isnull=True,
                defaults={
                    'product_id': sku,
                    'rate': prod.price,
                    'staff': staff,
                    'sponsor': None,
                    'plan': None,
                }
            )
            if created:
                created_count += 1
            else:
                tariff.rate = prod.price
                tariff.product_id = sku
                tariff.save()
                updated_count += 1

        # 2. Sync all distinct products from PharmacyTariff that don't have general rate yet
        existing_names = list(PharmacyTariff.objects.values_list('product_name', flat=True).distinct())
        all_drug_names = set(existing_names).union(BASELINE_MED_PRICES.keys())

        for name in all_drug_names:
            if not name:
                continue
            gen_tariff = PharmacyTariff.objects.filter(
                product_name__iexact=name.strip(),
                sponsor__isnull=True,
                plan__isnull=True
            ).first()

            if not gen_tariff:
                baseline = BASELINE_MED_PRICES.get(name.strip())
                if baseline:
                    sku, rate = baseline
                else:
                    existing_t = PharmacyTariff.objects.filter(product_name__iexact=name.strip()).first()
                    sku = (existing_t.product_id if existing_t else None) or f"GEN-{PharmacyTariff.objects.count()+1:03d}"
                    max_rate = PharmacyTariff.objects.filter(product_name__iexact=name.strip()).aggregate(Max('rate'))['rate__max']
                    rate = max_rate or Decimal('1000.00')

                PharmacyTariff.objects.create(
                    product_name=name.strip(),
                    product_id=sku,
                    rate=rate,
                    sponsor=None,
                    plan=None,
                    staff=staff
                )
                created_count += 1

                # Keep Product inventory table in sync
                Product.objects.get_or_create(
                    product_name=name.strip(),
                    defaults={
                        'product_id': sku,
                        'price': rate,
                        'stock': 100,
                        'staff': staff,
                    }
                )

        total_general = PharmacyTariff.objects.filter(sponsor__isnull=True, plan__isnull=True).count()
        return Response({
            'detail': f'Loaded {created_count} new general medication tariffs ({total_general} total active general rates).',
            'created': created_count,
            'updated': updated_count,
            'total_general': total_general,
        })


class LoadGeneralLabPricesView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        staff = request.user if request.user.is_authenticated else User.objects.first()

        sponsor_id = request.data.get('sponsor_id') or request.data.get('sponsor')
        plan_id = request.data.get('plan_id') or request.data.get('plan')
        target_type = (request.data.get('target_type') or request.data.get('type') or 'all').strip().lower()
        overwrite = bool(request.data.get('overwrite', False))

        is_general = not sponsor_id or str(sponsor_id).lower() in ('', 'general', 'self', 'cash', 'none', 'null')

        sponsor = None
        plan = None

        if not is_general:
            if sponsor_id and str(sponsor_id).lower() not in ('all', 'general', 'none'):
                try:
                    sponsor = Sponsor.objects.get(id=sponsor_id)
                except Sponsor.DoesNotExist:
                    pass

            if plan_id and str(plan_id).lower() not in ('all', 'general', 'none'):
                try:
                    plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                    if not sponsor and plan.sponsor:
                        sponsor = plan.sponsor
                except PatientPlan.DoesNotExist:
                    pass

        created_count = 0
        updated_count = 0
        existing_count = 0

        # 1. Load Investigations (Panels) from Database
        if target_type in ('all', 'investigations', 'panels'):
            invs = LabInvestigation.objects.filter(is_active=True).prefetch_related('parameter_mappings__parameter')
            for inv in invs:
                tariff = RadioLabInventory.objects.filter(
                    type='L',
                    item_id=inv.code,
                    sponsor=sponsor,
                    plan=plan
                ).first()
                if not tariff:
                    tariff = RadioLabInventory.objects.filter(
                        type='L',
                        item__iexact=inv.name.strip(),
                        sponsor=sponsor,
                        plan=plan
                    ).first()

                base_price = inv.effective_price()
                if not tariff:
                    RadioLabInventory.objects.create(
                        item=inv.name.strip(),
                        item_id=inv.code.strip(),
                        rate=base_price,
                        type='L',
                        test_type='investigation',
                        sponsor=sponsor,
                        plan=plan,
                        staff=staff
                    )
                    created_count += 1
                else:
                    if overwrite:
                        tariff.rate = base_price
                        tariff.test_type = 'investigation'
                        tariff.save()
                        updated_count += 1
                    else:
                        if tariff.test_type != 'investigation':
                            tariff.test_type = 'investigation'
                            tariff.save()
                        existing_count += 1

        # 2. Load Parameters (Individual Tests) from Database
        if target_type in ('all', 'parameters', 'singles'):
            params = LabParameter.objects.filter(is_active=True)
            for param in params:
                tariff = RadioLabInventory.objects.filter(
                    type='L',
                    item_id=param.code,
                    sponsor=sponsor,
                    plan=plan
                ).first()
                if not tariff:
                    tariff = RadioLabInventory.objects.filter(
                        type='L',
                        item__iexact=param.name.strip(),
                        sponsor=sponsor,
                        plan=plan
                    ).first()

                base_price = param.base_price
                if not tariff:
                    RadioLabInventory.objects.create(
                        item=param.name.strip(),
                        item_id=param.code.strip(),
                        rate=base_price,
                        type='L',
                        test_type='parameter',
                        sponsor=sponsor,
                        plan=plan,
                        staff=staff
                    )
                    created_count += 1
                else:
                    if overwrite:
                        tariff.rate = base_price
                        tariff.test_type = 'parameter'
                        tariff.save()
                        updated_count += 1
                    else:
                        if tariff.test_type != 'parameter':
                            tariff.test_type = 'parameter'
                            tariff.save()
                        existing_count += 1

        target_name = (
            "General / Out-of-Pocket"
            if is_general
            else f"{sponsor.name if sponsor else 'Selected Sponsor'} - {plan.plan if plan else 'All Plans'}"
        )
        return Response({
            'detail': f"Successfully loaded {created_count} new tariffs for {target_name} ({existing_count} already active). You can now edit the prices for this sponsor/plan.",
            'created': created_count,
            'updated': updated_count,
            'existing': existing_count,
            'target_name': target_name,
        })


class LoadGeneralRadiologyPricesView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from radio_lab.models import RadioLabInventory, RadiologyProcedure, LabInvestigation, LabParameter
        from django.db.models import Max

        staff = request.user if request.user.is_authenticated else User.objects.first()
        created_count = 0
        updated_count = 0

        # Baseline clinical radiology & imaging scan investigation prices for general self-pay patients
        BASELINE_RADIOLOGY_PRICES = {
            'Chest X-Ray (PA View)': ('RAD-001', Decimal('5000.00')),
            'Abdominal Ultrasound Scan': ('RAD-002', Decimal('6000.00')),
            'Pelvic Ultrasound Scan': ('RAD-003', Decimal('5500.00')),
            'Obstetric Ultrasound (Pregnancy Scan)': ('RAD-004', Decimal('4500.00')),
            'Lumbosacral Spine X-Ray (AP & Lateral)': ('RAD-005', Decimal('7500.00')),
            'Brain CT Scan (Non-Contrast)': ('RAD-006', Decimal('35000.00')),
            'Echocardiography (ECHO)': ('RAD-007', Decimal('20000.00')),
            'Electrocardiogram (ECG / EKG)': ('RAD-008', Decimal('4000.00')),
            'Mammography (Bilateral)': ('RAD-009', Decimal('15000.00')),
            'Knee Joint X-Ray (AP & Lateral)': ('RAD-010', Decimal('6000.00')),
        }

        # Sync all distinct radiology scans from existing RadioLabInventory (type='R')
        existing_items = list(RadioLabInventory.objects.filter(type='R').values_list('item', flat=True).distinct())
        all_rad_names = set(existing_items).union(BASELINE_RADIOLOGY_PRICES.keys())

        for name in all_rad_names:
            if not name:
                continue
            gen_tariff = RadioLabInventory.objects.filter(
                item__iexact=name.strip(),
                type='R',
                sponsor__isnull=True,
                plan__isnull=True
            ).first()

            if not gen_tariff:
                baseline = BASELINE_RADIOLOGY_PRICES.get(name.strip())
                if baseline:
                    code, rate = baseline
                else:
                    existing_t = RadioLabInventory.objects.filter(item__iexact=name.strip(), type='R').first()
                    code = (existing_t.item_id if existing_t else None) or f"RAD-{RadioLabInventory.objects.filter(type='R').count()+1:03d}"
                    max_rate = RadioLabInventory.objects.filter(item__iexact=name.strip(), type='R').aggregate(Max('rate'))['rate__max']
                    rate = max_rate or Decimal('5000.00')

                RadioLabInventory.objects.create(
                    item=name.strip(),
                    item_id=code,
                    rate=rate,
                    type='R',
                    sponsor=None,
                    plan=None,
                    staff=staff
                )
                created_count += 1
            else:
                updated_count += 1

        
        # Ensure all registered RadiologyProcedure records have baseline general prices
        for proc in RadiologyProcedure.objects.filter(is_active=True):
            gen = RadioLabInventory.objects.filter(
                type='R',
                sponsor__isnull=True,
                plan__isnull=True
            ).filter(Q(item_id=proc.code) | Q(item__iexact=proc.name)).first()

            if not gen:
                RadioLabInventory.objects.create(
                    item=proc.name,
                    item_id=proc.code,
                    rate=proc.base_price or Decimal('5000.00'),
                    type='R',
                    sponsor=None,
                    plan=None,
                    staff=staff
                )
                created_count += 1

        total_general = RadioLabInventory.objects.filter(type='R', sponsor__isnull=True, plan__isnull=True).count()
        return Response({
            'detail': f'Loaded {created_count} general radiology tariffs ({total_general} total active general rates).',
            'created': created_count,
            'updated': updated_count,
            'total_general': total_general,
        })


# 2.2 Download Medication Tariff Template
class DownloadMedicationTariffTemplateView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        from django.http import HttpResponse
        import io, csv
        from inventory.models import Product, PharmacyTariff, PharmacyStore, StoreStock
        from django.db.models import Q

        sponsor_id = request.query_params.get('sponsor')
        plan_id = request.query_params.get('plan')

        is_general = str(sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none')

        sponsor = None
        plan = None

        if is_general:
            sponsor_code = "GENERAL"
            plan_code = "GENERAL"
            sponsor_name = "General / Out-of-Pocket (Self-Pay)"
            plan_name = "General Baseline Tariff"
        else:
            sponsor_code = ""
            plan_code = ""
            sponsor_name = ""
            plan_name = ""

            if sponsor_id and str(sponsor_id).lower() not in ('all', '', 'none', 'null'):
                try:
                    sponsor = Sponsor.objects.get(id=sponsor_id)
                    sponsor_code = sponsor.code or sponsor.name
                    sponsor_name = sponsor.name
                except (Sponsor.DoesNotExist, ValueError):
                    pass

            if plan_id and str(plan_id).lower() not in ('all', '', 'none', 'null'):
                try:
                    plan = PatientPlan.objects.select_related('sponsor').get(id=plan_id)
                    plan_code = plan.code or plan.plan
                    plan_name = plan.plan
                    if plan.sponsor and not sponsor:
                        sponsor = plan.sponsor
                        sponsor_code = sponsor.code or sponsor.name
                        sponsor_name = sponsor.name
                except (PatientPlan.DoesNotExist, ValueError):
                    pass

            if not sponsor_code:
                sponsor_code = "AMH"
                sponsor_name = "AIICO MULTISHIELD (AMH)"
            if not plan_code:
                plan_code = "AIICO SLIVER"
                plan_name = "AIICO SLIVER"

        # 1. Locate Central Medical Store
        central_store = PharmacyStore.objects.filter(
            Q(is_central=True) | Q(store_type='central_store') | Q(name__icontains='central')
        ).first() or PharmacyStore.objects.first()

        # Map central store stock items
        stock_map = {}
        if central_store:
            for ss in StoreStock.objects.filter(store=central_store).select_related('product'):
                if ss.product_id:
                    stock_map[ss.product_id] = ss

        # Map existing negotiated tariffs for this sponsor & plan
        tariff_map = {}
        if not is_general and sponsor and plan:
            for t in PharmacyTariff.objects.filter(sponsor=sponsor, plan=plan):
                if t.product_name:
                    tariff_map[t.product_name.strip().lower()] = t.rate
        elif is_general:
            for t in PharmacyTariff.objects.filter(sponsor__isnull=True, plan__isnull=True):
                if t.product_name:
                    tariff_map[t.product_name.strip().lower()] = t.rate

        # 2. Query all medical items in database (ordered alphabetically)
        products = Product.objects.all().order_by('product_name')

        rows_data = []
        for p in products:
            p_name = (p.product_name or getattr(p, 'name', '') or '').strip()
            if not p_name:
                continue

            # Resolve price/rate:
            # 1. Existing negotiated tariff rate for sponsor & plan
            # 2. Product catalog default selling price
            # 3. Fallback 0.00
            p_name_lower = p_name.lower()
            if p_name_lower in tariff_map and tariff_map[p_name_lower] is not None:
                rate = tariff_map[p_name_lower]
            elif p.price is not None:
                rate = p.price
            else:
                rate = 0.00

            try:
                rate_str = f"{float(rate):.2f}"
            except (ValueError, TypeError):
                rate_str = "0.00"

            uom = p.minimum_UoM or p.unit or ''
            notes = f"Tariff for {plan_name}"
            if uom:
                notes += f" ({uom})"

            rows_data.append([
                p_name,
                rate_str,
                sponsor_code,
                plan_code,
                notes,
            ])

        # Fallback if no products exist in database
        if not rows_data:
            rows_data = [
                ['Paracetamol 500mg Tablet', '500.00', sponsor_code, plan_code, f'Tariff for {plan_name}'],
                ['Amoxicillin 500mg Capsule', '1200.00', sponsor_code, plan_code, f'Tariff for {plan_name}'],
            ]

        # 3. Output CSV with UTF-8 BOM so Excel opens it with clean columns
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['product_name', 'rate', 'sponsor_code', 'plan_code', 'notes'])
        for r in rows_data:
            writer.writerow(r)

        csv_content = output.getvalue()
        response = HttpResponse('﻿' + csv_content, content_type='text/csv; charset=utf-8')
        safe_sponsor = str(sponsor_code).replace(' ', '_').replace('/', '_')
        safe_plan = str(plan_code).replace(' ', '_').replace('/', '_')
        filename = f"medication_tariffs_template_{safe_sponsor}_{safe_plan}.csv"
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        response['Access-Control-Expose-Headers'] = 'Content-Disposition'
        return response


# 2.3 Bulk Upload Medication Tariffs
class BulkUploadMedicationTariffView(APIView):
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        import io, csv, re
        from decimal import Decimal
        from django.db.models import Q
        from inventory.models import Product, PharmacyTariff
        from patients.models import Sponsor, PatientPlan
        from users.models import User

        default_sponsor_id = request.data.get('sponsor_id') or request.data.get('default_sponsor_id')
        default_plan_id = request.data.get('plan_id') or request.data.get('default_plan_id')

        is_general_default = str(default_sponsor_id).strip().lower() in ('general', 'self', 'cash', 'none')

        default_sponsor = None
        if not is_general_default and default_sponsor_id and str(default_sponsor_id).lower() not in ('', 'all', 'null', 'none'):
            try:
                default_sponsor = Sponsor.objects.get(id=default_sponsor_id)
            except (Sponsor.DoesNotExist, ValueError):
                pass

        default_plan = None
        if not is_general_default and default_plan_id and str(default_plan_id).lower() not in ('', 'all', 'null', 'none', 'general'):
            try:
                default_plan = PatientPlan.objects.select_related('sponsor').get(id=default_plan_id)
                if not default_sponsor and default_plan.sponsor:
                    default_sponsor = default_plan.sponsor
            except (PatientPlan.DoesNotExist, ValueError):
                pass

        raw_rows = []
        uploaded_file = request.FILES.get('file')

        if uploaded_file:
            filename = uploaded_file.name.lower()
            try:
                file_bytes = uploaded_file.read()
                if filename.endswith('.csv'):
                    decoded_file = None
                    for enc in ('utf-8-sig', 'utf-8', 'cp1252', 'latin-1'):
                        try:
                            decoded_file = file_bytes.decode(enc)
                            break
                        except UnicodeDecodeError:
                            continue
                    if decoded_file is None:
                        decoded_file = file_bytes.decode('utf-8', errors='ignore')

                    reader = csv.DictReader(io.StringIO(decoded_file))
                    for row in reader:
                        if any(v and str(v).strip() for v in row.values() if v is not None):
                            raw_rows.append(row)
                elif filename.endswith(('.xlsx', '.xls')):
                    import pandas as pd
                    df = pd.read_excel(io.BytesIO(file_bytes))
                    df = df.where(pd.notnull(df), None)
                    for r in df.to_dict(orient='records'):
                        if any(v is not None and str(v).strip() != '' for v in r.values()):
                            raw_rows.append(r)
                else:
                    return Response(
                        {'detail': 'Unsupported file format. Please upload a CSV (.csv) or Excel (.xlsx, .xls) file.'},
                        status=status.HTTP_400_BAD_REQUEST
                    )
            except Exception as e:
                return Response(
                    {'detail': f'Error reading uploaded file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response(
                {'detail': 'No file or items array provided for bulk upload. Please select a CSV or Excel spreadsheet.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not raw_rows:
            return Response(
                {'detail': 'The uploaded file contains no data rows. Please ensure your file has valid medication entries.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        # Cache sponsors and plans in memory for fast lookup
        all_sponsors = list(Sponsor.objects.all())
        all_plans = list(PatientPlan.objects.select_related('sponsor').all())

        sponsor_by_code = {s.code.strip().upper(): s for s in all_sponsors if s.code}
        sponsor_by_name = {s.name.strip().upper(): s for s in all_sponsors if s.name}
        sponsor_by_id = {str(s.id): s for s in all_sponsors}

        plan_by_code = {p.code.strip().upper(): p for p in all_plans if p.code}
        plan_by_name = {p.plan.strip().upper(): p for p in all_plans if p.plan}
        plan_by_id = {str(p.id): p for p in all_plans}

        staff = request.user if request.user.is_authenticated else User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []

        for idx, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                continue

            # Multi-variant key normalizer: handles spaces, underscores, hyphens, and mixed casing
            norm = {}
            for k, v in row.items():
                if k is None:
                    continue
                k_raw = str(k).strip().lower()
                norm[k_raw] = v
                norm[k_raw.replace(' ', '_').replace('-', '_')] = v
                norm[k_raw.replace(' ', '').replace('_', '').replace('-', '')] = v

            product_name = (
                norm.get('product_name')
                or norm.get('productname')
                or norm.get('medication_name')
                or norm.get('medicationname')
                or norm.get('medication')
                or norm.get('drug_name')
                or norm.get('drugname')
                or norm.get('drug')
                or norm.get('item_name')
                or norm.get('itemname')
                or norm.get('item')
                or norm.get('name')
            )
            if not product_name or not str(product_name).strip():
                skipped.append(f"Row {idx}: Missing product/medication name")
                continue

            product_name = str(product_name).strip()

            rate_raw = (
                norm.get('rate')
                or norm.get('price')
                or norm.get('unit_cost')
                or norm.get('unitcost')
                or norm.get('selling_price')
                or norm.get('sellingprice')
                or norm.get('tariff_rate')
                or norm.get('tariffrate')
                or norm.get('tariff')
                or norm.get('amount')
                or norm.get('cost')
            )

            # Robust currency/rate parsing: handles '₦4,500', '4,500.00', 'NGN 4500', etc.
            rate_val = Decimal('0.00')
            if rate_raw is not None and str(rate_raw).strip() != '':
                try:
                    clean_str = ''.join(c for c in str(rate_raw).strip() if c.isdigit() or c == '.')
                    if clean_str:
                        rate_val = Decimal(clean_str)
                except Exception:
                    pass

            sku = (
                norm.get('sku')
                or norm.get('product_id')
                or norm.get('productid')
                or norm.get('code')
                or norm.get('item_code')
            )
            if sku and str(sku).strip():
                sku = str(sku).strip()[:13]
            else:
                existing_prod = Product.objects.filter(product_name__iexact=product_name).first()
                if existing_prod and existing_prod.product_id:
                    sku = existing_prod.product_id
                else:
                    existing_t = PharmacyTariff.objects.filter(product_name__iexact=product_name).exclude(product_id__isnull=True).exclude(product_id='').first()
                    if existing_t and existing_t.product_id:
                        sku = existing_t.product_id
                    else:
                        from inventory.utils import get_next_isl_sku
                        sku = get_next_isl_sku()

            # Resolve Sponsor & Plan:
            # 1. Use the explicitly selected default_sponsor and default_plan from modal if provided
            target_sponsor = default_sponsor
            target_plan = default_plan

            row_sponsor_val = norm.get('sponsor_code') or norm.get('sponsor') or norm.get('sponsor_name') or norm.get('hmo')
            row_plan_val = norm.get('plan_code') or norm.get('plan') or norm.get('plan_name') or norm.get('coverage_plan')

            if is_general_default or (row_sponsor_val and str(row_sponsor_val).strip().upper() in ('GENERAL', 'SELF', 'SELF-PAY', 'CASH', 'OUT-OF-POCKET', 'NO HMO', 'NONE')):
                target_sponsor = None
                target_plan = None
            else:
                # If row specifies a sponsor and no default was locked, lookup row sponsor
                if not target_sponsor and row_sponsor_val and str(row_sponsor_val).strip():
                    s_key = str(row_sponsor_val).strip().upper()
                    if s_key in sponsor_by_code:
                        target_sponsor = sponsor_by_code[s_key]
                    elif s_key in sponsor_by_name:
                        target_sponsor = sponsor_by_name[s_key]
                    elif str(row_sponsor_val).strip() in sponsor_by_id:
                        target_sponsor = sponsor_by_id[str(row_sponsor_val).strip()]

                # If row specifies a plan and no default was locked, lookup row plan
                if not target_plan and row_plan_val and str(row_plan_val).strip():
                    p_key = str(row_plan_val).strip().upper()
                    if p_key in plan_by_code:
                        target_plan = plan_by_code[p_key]
                    elif p_key in plan_by_name:
                        target_plan = plan_by_name[p_key]
                    elif str(row_plan_val).strip() in plan_by_id:
                        target_plan = plan_by_id[str(row_plan_val).strip()]
                    elif target_sponsor:
                        # Match within target sponsor's plans
                        clean_hint = p_key.replace(' ', '').replace('_', '')
                        for p in all_plans:
                            if p.sponsor_id == target_sponsor.id:
                                p_clean = (p.plan or '').upper().replace(' ', '').replace('_', '')
                                if clean_hint in p_clean or p_clean in clean_hint:
                                    target_plan = p
                                    break

                if not target_sponsor and target_plan and target_plan.sponsor:
                    target_sponsor = target_plan.sponsor

            # Look for existing tariff for this product, sponsor, and plan
            existing = PharmacyTariff.objects.filter(
                product_name__iexact=product_name,
                sponsor=target_sponsor,
                plan=target_plan
            ).first()

            if not existing and sku:
                existing = PharmacyTariff.objects.filter(
                    product_id__iexact=sku,
                    sponsor=target_sponsor,
                    plan=target_plan
                ).first()

            if existing:
                existing.rate = rate_val
                existing.product_name = product_name
                if sku:
                    existing.product_id = sku
                existing.staff = staff
                existing.save()
                updated_count += 1
            else:
                PharmacyTariff.objects.create(
                    product_name=product_name,
                    product_id=sku,
                    rate=rate_val,
                    sponsor=target_sponsor,
                    plan=target_plan,
                    staff=staff
                )
                created_count += 1

        total_processed = created_count + updated_count
        plan_desc = f" for {default_sponsor.name if default_sponsor else 'General'}"
        if default_plan:
            plan_desc += f" ({default_plan.plan})"

        return Response({
            'detail': f'Bulk import finished successfully{plan_desc}: {created_count} added, {updated_count} updated.',
            'created_count': created_count,
            'updated_count': updated_count,
            'skipped_count': len(skipped),
            'total_processed': total_processed,
            'skipped_details': skipped[:10],
        }, status=status.HTTP_200_OK if total_processed > 0 else status.HTTP_400_BAD_REQUEST)


class PackageServiceCatalogView(APIView):
    """
    Returns available database services across all hospital departments 
    (Laboratory, Radiology, Clinical Procedures, Wards, Pharmacy) with their standard baseline rates
    for bundling into care packages.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # 1. Laboratory tests
        lab_items = list(RadioLabInventory.objects.filter(type='L', sponsor__isnull=True, plan__isnull=True).values('id', 'item', 'item_id', 'rate').order_by('item'))
        labs = []
        seen_lab = set()
        for l in lab_items:
            name = (l['item'] or '').strip()
            if name and name.lower() not in seen_lab:
                seen_lab.add(name.lower())
                labs.append({
                    'id': l['id'],
                    'name': name,
                    'code': l['item_id'] or '',
                    'rate': float(l['rate'] or 0),
                    'type': 'LB',
                    'category': 'Laboratory Test',
                })

        # 2. Radiology scans
        rad_items = list(RadioLabInventory.objects.filter(type='R', sponsor__isnull=True, plan__isnull=True).values('id', 'item', 'item_id', 'rate').order_by('item'))
        rads = []
        seen_rad = set()
        for r in rad_items:
            name = (r['item'] or '').strip()
            if name and name.lower() not in seen_rad:
                seen_rad.add(name.lower())
                rads.append({
                    'id': r['id'],
                    'name': name,
                    'code': r['item_id'] or '',
                    'rate': float(r['rate'] or 0),
                    'type': 'RD',
                    'category': 'Radiology & Imaging',
                })

        # 3. Clinical services & procedures
        srv_items = list(OtherService2.objects.filter(plan__isnull=True).values('id', 'service', 'service_id', 'rate').order_by('service'))
        srvs = []
        seen_srv = set()
        for s in srv_items:
            name = (s['service'] or '').strip()
            if name and name.lower() not in seen_srv:
                seen_srv.add(name.lower())
                srvs.append({
                    'id': s['id'],
                    'name': name,
                    'code': s['service_id'] or '',
                    'rate': float(s['rate'] or 0),
                    'type': 'SR',
                    'category': 'Clinical Procedure / Service',
                })

        # 4. Wards & Admissions
        ward_items = list(Ward.objects.values('id', 'ward_name', 'price').order_by('ward_name'))
        wards = []
        for w in ward_items:
            name = (w['ward_name'] or '').strip()
            if name:
                wards.append({
                    'id': w['id'],
                    'name': f"{name} (Daily Bed Rate)",
                    'code': f"WARD-{w['id']}",
                    'rate': float(w['price'] or 0),
                    'type': 'WD',
                    'category': 'Ward Accommodation',
                })

        # 5. Pharmacy medications & consumables
        pharm_items = list(PharmacyTariff.objects.filter(sponsor__isnull=True, plan__isnull=True).values('id', 'product_name', 'product_id', 'rate').order_by('product_name')[:100])
        pharm = []
        seen_pharm = set()
        for p in pharm_items:
            name = (p['product_name'] or '').strip()
            if name and name.lower() not in seen_pharm:
                seen_pharm.add(name.lower())
                pharm.append({
                    'id': p['id'],
                    'name': name,
                    'code': p['product_id'] or '',
                    'rate': float(p['rate'] or 0),
                    'type': 'PH',
                    'category': 'Pharmacy & Medication',
                })

        return Response({
            'total_services': len(labs) + len(rads) + len(srvs) + len(wards) + len(pharm),
            'categories': {
                'lab_tests': labs,
                'radiology_scans': rads,
                'clinical_services': srvs,
                'wards': wards,
                'pharmacy': pharm,
            }
        })


class PackagesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        packages = Packages.objects.all().select_related('staff').order_by('-created_date')
        data = []
        for p in packages:
            items_qs = list(PackagesData.objects.filter(package=p).order_by('id'))
            items_list = [{
                'id': it.id,
                'item': it.item,
                'type': it.type,
                'rate': float(it.rate),
            } for it in items_qs]
            total_rate = sum([it['rate'] for it in items_list])
            
            # Count by type
            type_counts = {}
            for it in items_list:
                t = it['type']
                type_counts[t] = type_counts.get(t, 0) + 1

            data.append({
                'id': p.id,
                'name': p.name,
                'staff_name': p.staff.fullname if p.staff else 'Admin',
                'created_date': p.created_date.isoformat() if p.created_date else None,
                'items_count': len(items_list),
                'total_rate': total_rate,
                'type_counts': type_counts,
                'items': items_list
            })
        return Response({'total': len(data), 'packages': data})

    def post(self, request):
        name = request.data.get('name', '').strip()
        if not name:
            return Response({'detail': 'Package name is required.'}, status=status.HTTP_400_BAD_REQUEST)

        existing = Packages.objects.filter(name__iexact=name).first()
        if existing and not request.data.get('overwrite'):
            return Response({'detail': f'Package "{name}" already exists.'}, status=status.HTTP_400_BAD_REQUEST)

        staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else User.objects.first()
        pkg = existing or Packages.objects.create(name=name, staff=staff)
        if existing:
            pkg.staff = staff
            pkg.save()

        items = request.data.get('items', [])
        saved_items = []
        if isinstance(items, list):
            if request.data.get('replace_items', True) and existing:
                PackagesData.objects.filter(package=pkg).delete()
            for it in items:
                it_name = it.get('item') or it.get('name')
                if not it_name or not str(it_name).strip():
                    continue
                it_type = it.get('type') or 'SR'
                try:
                    it_rate = Decimal(str(it.get('rate') or 0))
                except Exception:
                    it_rate = Decimal('0.00')
                created_item = PackagesData.objects.create(
                    package=pkg,
                    item=str(it_name).strip(),
                    type=str(it_type).strip()[:10],
                    rate=it_rate,
                    staff=staff
                )
                saved_items.append({
                    'id': created_item.id,
                    'item': created_item.item,
                    'type': created_item.type,
                    'rate': float(created_item.rate),
                })

        return Response({
            'detail': f'Package "{pkg.name}" {"updated" if existing else "created"} successfully with {len(saved_items)} bundled service(s).',
            'id': pkg.id,
            'name': pkg.name,
            'items_count': len(saved_items),
            'items': saved_items,
        }, status=status.HTTP_201_CREATED if not existing else status.HTTP_200_OK)

    def put(self, request, pk=None):
        try:
            pkg = Packages.objects.get(id=pk)
        except Packages.DoesNotExist:
            return Response({'detail': 'Package not found.'}, status=status.HTTP_404_NOT_FOUND)

        name = request.data.get('name', '').strip()
        if name:
            pkg.name = name
            pkg.save()

        items = request.data.get('items')
        saved_items = []
        if items is not None and isinstance(items, list):
            staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else User.objects.first()
            PackagesData.objects.filter(package=pkg).delete()
            for it in items:
                it_name = it.get('item') or it.get('name')
                if not it_name or not str(it_name).strip():
                    continue
                it_type = it.get('type') or 'SR'
                try:
                    it_rate = Decimal(str(it.get('rate') or 0))
                except Exception:
                    it_rate = Decimal('0.00')
                created_item = PackagesData.objects.create(
                    package=pkg,
                    item=str(it_name).strip(),
                    type=str(it_type).strip()[:10],
                    rate=it_rate,
                    staff=staff
                )
                saved_items.append({
                    'id': created_item.id,
                    'item': created_item.item,
                    'type': created_item.type,
                    'rate': float(created_item.rate),
                })

        return Response({
            'detail': f'Package "{pkg.name}" updated successfully.',
            'id': pkg.id,
            'name': pkg.name,
            'items_count': len(saved_items) if items is not None else PackagesData.objects.filter(package=pkg).count(),
            'items': saved_items,
        })

    def delete(self, request, pk=None):
        Packages.objects.filter(id=pk).delete()
        return Response({'detail': 'Package deleted.'})


# 3.2 Package Data Items
class PackageDataView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        package_id = request.query_params.get('package_id')
        qs = PackagesData.objects.all().select_related('package').order_by('type')
        if package_id:
            qs = qs.filter(package_id=package_id)

        data = []
        for item in qs:
            data.append({
                'id': item.id,
                'package_id': item.package.id if item.package else None,
                'package_name': item.package.name if item.package else '',
                'item': item.item,
                'type': item.type,
                'rate': float(item.rate),
            })
        return Response({'total': len(data), 'items': data})

    def post(self, request):
        package_id = request.data.get('package_id')
        item_name = request.data.get('item', '').strip()
        item_type = request.data.get('type', 'SR').strip()
        rate = request.data.get('rate', 0)

        if not package_id or not item_name:
            return Response({'detail': 'Package ID and item name are required.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            pkg = Packages.objects.get(id=package_id)
        except Packages.DoesNotExist:
            return Response({'detail': 'Package not found.'}, status=status.HTTP_404_NOT_FOUND)

        staff = request.user if request.user.is_authenticated else User.objects.first()

        obj = PackagesData.objects.create(
            package=pkg,
            item=item_name,
            type=item_type,
            rate=Decimal(str(rate)),
            staff=staff
        )
        return Response({
            'detail': f'Item "{obj.item}" added to package "{pkg.name}".',
            'id': obj.id,
            'package_id': pkg.id,
            'item': obj.item,
            'type': obj.type,
            'rate': float(obj.rate)
        })

    def put(self, request, pk=None):
        try:
            item = PackagesData.objects.get(id=pk)
        except PackagesData.DoesNotExist:
            return Response({'detail': 'Package item not found.'}, status=status.HTTP_404_NOT_FOUND)

        if 'item' in request.data: item.item = request.data['item'].strip()
        if 'type' in request.data: item.type = request.data['type'].strip()
        if 'rate' in request.data: item.rate = Decimal(str(request.data['rate']))

        item.save()
        return Response({'detail': 'Package item updated.', 'id': item.id, 'item': item.item, 'rate': float(item.rate)})

    def delete(self, request, pk=None):
        PackagesData.objects.filter(id=pk).delete()
        return Response({'detail': 'Package item deleted.'})


# 3.3 Immunization Fees
class ImmunizationFeesView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        # Sample immunization catalog fees
        immunizations = [
            {'id': 1, 'vaccine_name': 'BCG (Bacille Calmette-Guérin)', 'target': 'Newborns', 'schedule': 'At Birth', 'fee': 3500},
            {'id': 2, 'vaccine_name': 'OPV (Oral Polio Vaccine)', 'target': 'Infants', 'schedule': 'Birth, 6, 10, 14 Weeks', 'fee': 2500},
            {'id': 3, 'vaccine_name': 'Pentavalent (DTP-HepB-Hib)', 'target': 'Infants', 'schedule': '6, 10, 14 Weeks', 'fee': 6000},
            {'id': 4, 'vaccine_name': 'Rotavirus Vaccine', 'target': 'Infants', 'schedule': '6, 10 Weeks', 'fee': 8500},
            {'id': 5, 'vaccine_name': 'Yellow Fever Vaccine', 'target': 'Infants / Adults', 'schedule': '9 Months / Booster', 'fee': 5000},
            {'id': 6, 'vaccine_name': 'Measles Vaccine', 'target': 'Infants', 'schedule': '9 Months', 'fee': 4000},
            {'id': 7, 'vaccine_name': 'Tetanus Toxoid (TT)', 'target': 'Maternal / Adults', 'schedule': 'Antenatal Schedule', 'fee': 2000},
            {'id': 8, 'vaccine_name': 'Hepatitis B Adult Booster', 'target': 'Adults / Staff', 'schedule': '0, 1, 6 Months', 'fee': 7500},
        ]
        return Response({'total': len(immunizations), 'immunizations': immunizations})
