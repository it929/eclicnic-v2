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


    @action(detail=False, methods=['get'])
    def download_template(self, request):
        """
        Download simplified Excel (.xlsx) template with 3 essential columns:
        - Parameter Name *
        - Parameter Code
        - Price (₦) *
        Additional fields (category, specimen, bottle, units, reference ranges) can be updated after upload.
        """
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lab Parameters Template"
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Parameter Name *",
            "Parameter Code",
            "Price (₦) *"
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="0284C7", end_color="0284C7", fill_type="solid")
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

        sample_rows = [
            ["White Blood Cell Count (WBC)", "WBC", 1500],
            ["Haemoglobin (Hb)", "HGB", 1500],
            ["Platelet Count", "PLT", 1500],
            ["Fasting Blood Glucose", "GLU_F", 2500],
            ["Total Bilirubin", "TBIL", 2000],
            ["Alanine Aminotransferase (ALT)", "ALT", 2000],
            ["Serum Creatinine", "CR", 2500],
            ["Serum Potassium (K+)", "K", 2000],
            ["Serum Sodium (Na+)", "NA", 2000],
            ["Blood Urea Nitrogen (Urea)", "UREA", 2000],
            ["Random Blood Sugar (RBS)", "RBS", 2000],
            ["Erythrocyte Sedimentation Rate (ESR)", "ESR", 2000]
        ]

        row_fill_alt = PatternFill(start_color="F0F9FF", end_color="F0F9FF", fill_type="solid")

        for r_idx, r_data in enumerate(sample_rows, start=2):
            ws.append(r_data)
            for c_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.border = thin_border
                cell.font = Font(name="Calibri", size=10)
                if r_idx % 2 == 1:
                    cell.fill = row_fill_alt
                if c_idx == 3:
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        col_widths = {1: 42, 2: 20, 3: 18}
        for col_idx, width in col_widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = 'attachment; filename="lab_parameters_bulk_template.xlsx"'
        return response

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        """
        Bulk upload individual lab parameters from CSV or Excel file.
        Accepts:
        - Parameter Name (required)
        - Parameter Code (optional, auto-generated if blank)
        - Price (required)
        Additional optional fields (Category, Specimen, Bottle, Units, Normal Description)
        are accepted if present, or filled with standard clinical defaults and can be updated after upload.
        Strict duplicate prevention: matches existing records by Code or Name and updates them.
        """
        import csv, io, re
        from decimal import Decimal
        from django.db.models import Q
        from radio_lab.models import RadioLabInventory, LabParameter
        from users.models import User

        uploaded_file = request.FILES.get('file')
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
                    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
                    has_known_col = any(
                        any(c in re.sub(r'[^a-z0-9]', '', str(col).lower()) for c in ['name', 'parameter', 'test', 'code', 'price', 'rate'])
                        for col in df.columns
                    )
                    if not has_known_col and len(df) > 0:
                        row0 = df.iloc[0]
                        has_row0_header = any(
                            any(c in re.sub(r'[^a-z0-9]', '', str(v).lower()) for c in ['name', 'parameter', 'test', 'code', 'price', 'rate'])
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
                return Response(
                    {'detail': f'Error reading uploaded file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif hasattr(request, 'data') and 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response(
                {'detail': 'No file or items data provided for bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not raw_rows:
            return Response(
                {'detail': 'The uploaded file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        req_data = getattr(request, 'data', None) or getattr(request, 'POST', {}) or {}
        default_category = (req_data.get('default_category') or '').strip()

        staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []
        param_counter = LabParameter.objects.count()

        def infer_category(p_name, fallback_cat=''):
            if fallback_cat and str(fallback_cat).strip():
                return fallback_cat
            n = str(p_name or '').lower()
            if any(k in n for k in ['wbc', 'rbc', 'hgb', 'hb', 'platelet', 'plt', 'esr', 'pcv', 'haem', 'hem', 'white blood', 'red blood', 'neutrophil', 'lymphocyte', 'eosinophil', 'basophil', 'monocyte']):
                return 'Haematology'
            if any(k in n for k in ['glucose', 'sugar', 'fbs', 'rbs', 'urea', 'creatinine', 'sodium', 'potassium', 'chloride', 'bicarbonate', 'bilirubin', 'alt', 'ast', 'alp', 'cholesterol', 'triglyceride', 'hdl', 'ldl', 'protein', 'albumin', 'calcium']):
                return 'Chemical Pathology'
            if any(k in n for k in ['malaria', 'mp', 'parasite']):
                return 'Parasitology'
            if any(k in n for k in ['urine', 'stool', 'culture', 'sensitivity', 'gram']):
                return 'Microbiology'
            if any(k in n for k in ['hiv', 'hepatitis', 'widal', 'vdrl', 'syphilis', 'crp', 'aso', 'hcg']):
                return 'Immunology / Serology'
            if any(k in n for k in ['tsh', 't3', 't4', 'psa', 'prolactin', 'fsh', 'lh']):
                return 'Endocrinology'
            return 'Haematology'

        def infer_specimen(p_name):
            n = str(p_name or '').lower()
            if any(k in n for k in ['glucose', 'sugar', 'fbs', 'rbs', 'gtt']):
                return 'Fluoride Plasma', 'Grey / Fluoride', '2 ml'
            if any(k in n for k in ['wbc', 'rbc', 'hgb', 'hb', 'platelet', 'plt', 'esr', 'pcv', 'haem', 'hem', 'blood film', 'mp', 'malaria', 'genotype', 'grouping']):
                return 'Whole Blood', 'Purple / EDTA', '2-5 ml'
            if any(k in n for k in ['urine']):
                return 'Urine', 'Universal Container', '10-20 ml'
            if any(k in n for k in ['stool']):
                return 'Stool', 'Stool Container', 'Pea sized'
            return 'Serum', 'Red / Plain', '3-5 ml'

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
            for k, v in row.items():
                if k is not None:
                    clean_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
                    if clean_k:
                        norm_row[clean_k] = v

            # 1. PARAMETER NAME
            name = find_field(norm_row, [
                'parametername', 'name', 'testname', 'itemname', 'parameter', 'title', 'description'
            ])

            if not name:
                for v in non_empty_values:
                    sv = str(v).strip()
                    if len(sv) > 2 and not re.match(r'^\d+(\.\d+)?$', sv) and not re.match(r'^[A-Z0-9]{2,6}-\d+$', sv, re.I):
                        name = sv
                        break

            if not name or not str(name).strip():
                skipped.append(f"Row {idx}: Missing parameter name")
                continue

            name = str(name).strip()

            # 2. PARAMETER CODE
            raw_code = find_field(norm_row, [
                'parametercode', 'code', 'testcode', 'paramcode', 'itemid', 'id', 'serialnumber', 'no'
            ])
            if raw_code and str(raw_code).strip() not in ('', 'nan', 'none', 'null'):
                code = str(raw_code).strip().upper()
            else:
                param_counter += 1
                code = f"PRM-{param_counter:03d}"

            # 3. BASE PRICE
            raw_price = find_field(norm_row, [
                'price', 'baseprice', 'rate', 'tariff', 'amount', 'fee', 'cost', 'charge', 'basepricengn', 'pricengn'
            ])
            try:
                clean_p_str = re.sub(r'[^\d.]', '', str(raw_price)) if raw_price is not None else ''
                base_price = Decimal(clean_p_str) if clean_p_str else Decimal('0.00')
                if base_price < 0:
                    base_price = Decimal('0.00')
            except Exception:
                base_price = Decimal('0.00')

            # 4. CATEGORY (inferred if absent)
            raw_cat = find_field(norm_row, ['category', 'dept', 'department', 'type', 'section'])
            category = str(raw_cat).strip() if raw_cat else infer_category(name, default_category)

            # 5. SPECIMEN & CONTAINER (inferred if absent)
            default_spec, default_bottle, default_qty = infer_specimen(name)
            specimen = str(find_field(norm_row, ['specimen', 'sample', 'sampletype']) or default_spec).strip()
            bottle_color = str(find_field(norm_row, ['samplebottlecolor', 'bottlecolor', 'bottle', 'color', 'container']) or default_bottle).strip()
            sample_qty = str(find_field(norm_row, ['samplequantity', 'quantity', 'volume', 'qty']) or default_qty).strip()

            # 6. MEASUREMENT UNIT & NORMAL DESCRIPTION
            unit = str(find_field(norm_row, ['measurementunit', 'unit', 'units', 'measure']) or '').strip()
            normal_desc = str(find_field(norm_row, ['normalresultdescription', 'normalrange', 'referencerange', 'normal', 'range']) or '').strip()

            # 7. CAN BE DONE ALONE
            raw_alone = find_field(norm_row, ['canbedonealone', 'alone', 'standalone'])
            can_alone = True
            if raw_alone is not None:
                can_alone = str(raw_alone).strip().lower() not in ('no', 'false', '0')

            # 8. IS ACTIVE
            raw_act = find_field(norm_row, ['isactive', 'active', 'status'])
            is_active = True
            if raw_act is not None:
                is_active = str(raw_act).strip().lower() not in ('no', 'false', '0', 'inactive', 'disabled')

            # STRICT DUPLICATE PREVENTION:
            param = LabParameter.objects.filter(code__iexact=code).first()
            if not param:
                param = LabParameter.objects.filter(name__iexact=name).first()

            if param:
                param.name = name
                if category:
                    param.category = category
                if specimen:
                    param.specimen = specimen
                if bottle_color:
                    param.sample_bottle_color = bottle_color
                if sample_qty:
                    param.sample_quantity = sample_qty
                if unit:
                    param.measurement_unit = unit
                if normal_desc:
                    param.normal_result_description = normal_desc
                param.base_price = base_price
                param.can_be_done_alone = can_alone
                param.is_active = is_active
                param.save()
                updated_count += 1
            else:
                unique_code = code
                if LabParameter.objects.filter(code__iexact=unique_code).exists():
                    param_counter += 1
                    unique_code = f"PRM-{param_counter:03d}"
                    while LabParameter.objects.filter(code__iexact=unique_code).exists():
                        param_counter += 1
                        unique_code = f"PRM-{param_counter:03d}"
                param = LabParameter.objects.create(
                    code=unique_code,
                    name=name,
                    category=category,
                    specimen=specimen,
                    sample_bottle_color=bottle_color,
                    sample_quantity=sample_qty,
                    measurement_unit=unit,
                    normal_result_description=normal_desc,
                    base_price=base_price,
                    can_be_done_alone=can_alone,
                    is_active=is_active
                )
                created_count += 1

            # 9. GENERAL TARIFF AUTO-SYNC in RadioLabInventory
            if can_alone:
                existing_tariff = RadioLabInventory.objects.filter(
                    type='L', sponsor__isnull=True, plan__isnull=True
                ).filter(Q(item_id__iexact=param.code) | Q(item__iexact=param.name)).first()

                if existing_tariff:
                    existing_tariff.item = param.name
                    existing_tariff.item_id = param.code
                    existing_tariff.rate = base_price
                    existing_tariff.test_type = 'parameter'
                    existing_tariff.staff = staff
                    existing_tariff.save()
                else:
                    RadioLabInventory.objects.create(
                        item=param.name,
                        item_id=param.code,
                        rate=base_price,
                        type='L',
                        test_type='parameter',
                        sponsor=None,
                        plan=None,
                        staff=staff
                    )

        detail_msg = f"Bulk upload completed: {created_count} parameter(s) created, {updated_count} updated."
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


    @action(detail=False, methods=['get'])
    def download_template(self, request):
        """
        Download simplified Excel (.xlsx) template with 3 essential columns:
        - Investigation Name *
        - Investigation Code
        - Price (₦) *
        Additional fields (category, specimen, bottle, mapped parameters) can be updated after upload.
        """
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from django.http import HttpResponse

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Lab Investigations Template"
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Investigation Name *",
            "Investigation Code",
            "Price (₦) *"
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="1D4ED8", end_color="1D4ED8", fill_type="solid")
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

        sample_rows = [
            ["Full Blood Count (FBC / CBC)", "FBC", 6500],
            ["Liver Function Tests (LFTs)", "LFT", 12500],
            ["Electrolytes, Urea & Creatinine (E/U/Cr)", "EUCR", 11000],
            ["Lipid Profile", "LIPID", 9500],
            ["Fasting Blood Sugar (FBS)", "FBS", 2500],
            ["Urinalysis Routine", "URIN", 2000],
            ["Malaria Parasite (MP) Microscopy", "MP", 3000],
            ["Widal Agglutination Test (Typhoid)", "WIDAL", 4000],
            ["Stool Microscopy, Culture & Sensitivity", "STOOL_MCS", 8500],
            ["Thyroid Function Tests (TFTs)", "TFT", 22000]
        ]

        row_fill_alt = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

        for r_idx, r_data in enumerate(sample_rows, start=2):
            ws.append(r_data)
            for c_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.border = thin_border
                cell.font = Font(name="Calibri", size=10)
                if r_idx % 2 == 1:
                    cell.fill = row_fill_alt
                if c_idx == 3:
                    cell.number_format = "#,##0.00"
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                else:
                    cell.alignment = Alignment(horizontal="left", vertical="center")

        col_widths = {1: 44, 2: 24, 3: 20}
        for col_idx, width in col_widths.items():
            ws.column_dimensions[get_column_letter(col_idx)].width = width

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = 'attachment; filename="lab_investigations_bulk_template.xlsx"'
        return response

    @action(detail=False, methods=['post'])
    def bulk_upload(self, request):
        """
        Bulk upload laboratory investigations and diagnostic panels from CSV or Excel file.
        Accepts:
        - Investigation Name (required)
        - Investigation Code (optional, auto-generated if blank)
        - Price (required)
        Additional optional fields (Category, Specimen, Bottle Color, Quantity, Mapped Parameters)
        are accepted if provided, or filled with standard clinical defaults and can be updated after upload.
        Strict duplicate prevention: matches existing records by Code or Name and updates them.
        """
        import csv, io, re
        from decimal import Decimal
        from django.db.models import Q
        from radio_lab.models import RadioLabInventory, LabInvestigation, LabParameter, LabInvestigationParameter
        from users.models import User

        uploaded_file = request.FILES.get('file')
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
                    df = pd.read_excel(io.BytesIO(file_bytes), sheet_name=0)
                    has_known_col = any(
                        any(c in re.sub(r'[^a-z0-9]', '', str(col).lower()) for c in ['name', 'investigation', 'panel', 'test', 'code', 'price', 'rate'])
                        for col in df.columns
                    )
                    if not has_known_col and len(df) > 0:
                        row0 = df.iloc[0]
                        has_row0_header = any(
                            any(c in re.sub(r'[^a-z0-9]', '', str(v).lower()) for c in ['name', 'investigation', 'panel', 'test', 'code', 'price', 'rate'])
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
                return Response(
                    {'detail': f'Error reading uploaded file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif hasattr(request, 'data') and 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response(
                {'detail': 'No file or items data provided for bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not raw_rows:
            return Response(
                {'detail': 'The uploaded file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        req_data = getattr(request, 'data', None) or getattr(request, 'POST', {}) or {}
        default_category = (req_data.get('default_category') or '').strip()
        default_pricing_mode = (req_data.get('default_pricing_mode') or 'fixed').strip().lower()

        staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []
        inv_counter = LabInvestigation.objects.count()

        all_params = list(LabParameter.objects.all())
        param_by_code = {p.code.strip().upper(): p for p in all_params if p.code}
        param_by_name = {p.name.strip().lower(): p for p in all_params if p.name}

        def infer_category(inv_name, fallback_cat=''):
            if fallback_cat and str(fallback_cat).strip():
                return fallback_cat
            n = str(inv_name or '').lower()
            if any(k in n for k in ['blood', 'fbc', 'cbc', 'hb', 'hgb', 'wbc', 'platelet', 'haem', 'hem', 'erythrocyte', 'esr', 'pbf', 'reticulocyte']):
                return 'Haematology'
            if any(k in n for k in ['liver', 'lft', 'renal', 'kidney', 'e/u', 'eucr', 'lipid', 'cholesterol', 'sugar', 'glucose', 'fbs', 'rbs', 'creatinine', 'urea', 'bilirubin', 'protein', 'albumin', 'calcium', 'amylase']):
                return 'Chemical Pathology'
            if any(k in n for k in ['urine', 'urinalysis', 'stool', 'culture', 'sensitivity', 'm/c/s', 'mcs', 'swab', 'sputum', 'pus', 'gram']):
                return 'Microbiology'
            if any(k in n for k in ['malaria', 'mp', 'parasite', 'blood film']):
                return 'Parasitology'
            if any(k in n for k in ['widal', 'typhoid', 'hiv', 'hepatitis', 'hcv', 'hbsag', 'vdrl', 'syphilis', 'crp', 'aso', 'pregnancy', 'pt', 'hcg']):
                return 'Immunology / Serology'
            if any(k in n for k in ['thyroid', 'tft', 'tsh', 't3', 't4', 'prolactin', 'fsh', 'lh', 'estrogen', 'progesterone', 'testosterone', 'psa']):
                return 'Endocrinology'
            return 'Haematology'

        def infer_specimen(inv_name):
            n = str(inv_name or '').lower()
            if any(k in n for k in ['urine', 'urinalysis']):
                return 'Urine', 'Universal Container', '10-20 ml'
            if any(k in n for k in ['stool', 'fecal']):
                return 'Stool', 'Stool Container', 'Pea sized'
            if any(k in n for k in ['swab', 'wound', 'throat', 'high vaginal', 'hvs', 'urethral']):
                return 'Swab', 'Swab Stick', '1 swab'
            if any(k in n for k in ['sputum']):
                return 'Sputum', 'Universal Container', '2-5 ml'
            if any(k in n for k in ['csf', 'cerebrospinal']):
                return 'CSF', 'Sterile Plain Bottle', '1-2 ml'
            if any(k in n for k in ['sugar', 'glucose', 'fbs', 'rbs', 'gtt']):
                return 'Fluoride Plasma', 'Grey / Fluoride', '2 ml'
            if any(k in n for k in ['fbc', 'cbc', 'haem', 'hem', 'esr', 'mp', 'malaria', 'genotype', 'grouping']):
                return 'Whole Blood', 'Purple / EDTA', '2-5 ml'
            return 'Serum', 'Red / Plain', '3-5 ml'

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
            for k, v in row.items():
                if k is not None:
                    clean_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
                    if clean_k:
                        norm_row[clean_k] = v

            # 1. INVESTIGATION / PANEL NAME
            name = find_field(norm_row, [
                'investigationname', 'name', 'panelname', 'testname', 'itemname',
                'investigation', 'panel', 'test', 'title', 'description'
            ])

            if not name:
                for v in non_empty_values:
                    sv = str(v).strip()
                    if len(sv) > 2 and not re.match(r'^\d+(\.\d+)?$', sv) and not re.match(r'^[A-Z0-9]{2,6}-\d+$', sv, re.I):
                        name = sv
                        break

            if not name or not str(name).strip():
                skipped.append(f"Row {idx}: Missing investigation name")
                continue

            name = str(name).strip()

            # 2. INVESTIGATION CODE
            raw_code = find_field(norm_row, [
                'investigationcode', 'code', 'panelcode', 'testcode', 'itemid', 'id', 'serialnumber', 'no'
            ])
            if raw_code and str(raw_code).strip() not in ('', 'nan', 'none', 'null'):
                code = str(raw_code).strip().upper()
            else:
                inv_counter += 1
                code = f"INV-{inv_counter:03d}"

            # 3. BASE PRICE
            raw_price = find_field(norm_row, [
                'price', 'baseprice', 'rate', 'tariff', 'amount', 'fee', 'cost', 'charge', 'basepricengn', 'pricengn'
            ])
            try:
                clean_p_str = re.sub(r'[^\d.]', '', str(raw_price)) if raw_price is not None else ''
                base_price = Decimal(clean_p_str) if clean_p_str else Decimal('0.00')
                if base_price < 0:
                    base_price = Decimal('0.00')
            except Exception:
                base_price = Decimal('0.00')

            # 4. CATEGORY (inferred if absent)
            raw_cat = find_field(norm_row, ['category', 'dept', 'department', 'type', 'section'])
            category = str(raw_cat).strip() if raw_cat else infer_category(name, default_category)

            # 5. SPECIMEN & CONTAINER (inferred if absent)
            default_spec, default_bottle, default_qty = infer_specimen(name)
            specimen = str(find_field(norm_row, ['specimen', 'sample', 'sampletype']) or default_spec).strip()
            bottle_color = str(find_field(norm_row, ['samplebottlecolor', 'bottlecolor', 'bottle', 'color', 'container']) or default_bottle).strip()
            sample_qty = str(find_field(norm_row, ['samplequantity', 'quantity', 'volume', 'qty']) or default_qty).strip()

            # 6. PRICING STRATEGY (default: use fixed price entered)
            raw_strat = find_field(norm_row, ['pricingstrategy', 'pricingmode', 'useaccumulatedprice', 'pricing'])
            if raw_strat:
                s_lower = str(raw_strat).strip().lower()
                use_accumulated = 'accum' in s_lower or s_lower in ('true', 'yes', '1')
            else:
                use_accumulated = default_pricing_mode == 'accumulated'

            # 7. IS ACTIVE
            raw_act = find_field(norm_row, ['isactive', 'active', 'status'])
            is_active = True
            if raw_act is not None:
                is_active = str(raw_act).strip().lower() not in ('no', 'false', '0', 'inactive', 'disabled')

            # STRICT DUPLICATE PREVENTION:
            # 1. Search by exact code
            # 2. Search by exact name (case-insensitive)
            inv = LabInvestigation.objects.filter(code__iexact=code).first()
            if not inv:
                inv = LabInvestigation.objects.filter(name__iexact=name).first()

            if inv:
                inv.name = name
                if category:
                    inv.category = category
                if specimen:
                    inv.specimen = specimen
                if bottle_color:
                    inv.sample_bottle_color = bottle_color
                if sample_qty:
                    inv.sample_quantity = sample_qty
                inv.base_price = base_price
                inv.use_accumulated_price = use_accumulated
                inv.is_active = is_active
                inv.save()
                updated_count += 1
            else:
                unique_code = code
                if LabInvestigation.objects.filter(code__iexact=unique_code).exists():
                    inv_counter += 1
                    unique_code = f"INV-{inv_counter:03d}"
                    while LabInvestigation.objects.filter(code__iexact=unique_code).exists():
                        inv_counter += 1
                        unique_code = f"INV-{inv_counter:03d}"
                inv = LabInvestigation.objects.create(
                    code=unique_code,
                    name=name,
                    category=category,
                    specimen=specimen,
                    sample_bottle_color=bottle_color,
                    sample_quantity=sample_qty,
                    base_price=base_price,
                    use_accumulated_price=use_accumulated,
                    is_panel=True,
                    is_active=is_active
                )
                created_count += 1

            # 8. MAPPED PARAMETERS (optional)
            raw_params = find_field(norm_row, [
                'mappedparametercodes', 'mappedparameters', 'parameters', 'paramcodes', 'subtests', 'tests'
            ])
            if raw_params and str(raw_params).strip() not in ('', 'nan', 'none', 'null'):
                param_items = [p.strip() for p in re.split(r'[,;]+', str(raw_params)) if p.strip()]
                order_idx = 1
                for p_item in param_items:
                    matched_param = param_by_code.get(p_item.upper())
                    if not matched_param:
                        matched_param = param_by_name.get(p_item.lower())
                    if matched_param:
                        LabInvestigationParameter.objects.get_or_create(
                            investigation=inv,
                            parameter=matched_param,
                            defaults={'order': order_idx, 'is_required': True}
                        )
                        order_idx += 1

            # 9. GENERAL TARIFF AUTO-SYNC in RadioLabInventory
            eff_rate = inv.effective_price() or base_price
            existing_tariff = RadioLabInventory.objects.filter(
                type='L', sponsor__isnull=True, plan__isnull=True
            ).filter(Q(item_id__iexact=inv.code) | Q(item__iexact=inv.name)).first()

            if existing_tariff:
                existing_tariff.item = inv.name
                existing_tariff.item_id = inv.code
                existing_tariff.rate = eff_rate
                existing_tariff.test_type = 'investigation'
                existing_tariff.staff = staff
                existing_tariff.save()
            else:
                RadioLabInventory.objects.create(
                    item=inv.name,
                    item_id=inv.code,
                    rate=eff_rate,
                    type='L',
                    test_type='investigation',
                    sponsor=None,
                    plan=None,
                    staff=staff
                )

        detail_msg = f"Bulk upload completed: {created_count} investigation(s) created, {updated_count} updated."
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

    @action(detail=False, methods=['post'], url_path='bulk-upload')
    def bulk_upload(self, request):
        """
        Bulk upload radiology and diagnostic imaging procedures catalog from CSV or Excel file.
        Accepts:
        - Scan Name (required)
        - Scan Code (optional, auto-generated if blank)
        - Price (required / baseline rate)
        - Additional optional fields (Category/Modality, Body Part, Instructions, Duration, Is Active)
        Strict duplicate prevention: matches existing records by Code or Name and updates them.
        """
        import csv, io, re
        from decimal import Decimal
        from django.http import HttpResponse
        uploaded_file = request.FILES.get('file')
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
                    delimiter = ','
                    if ';' in first_line and first_line.count(';') > first_line.count(','):
                        delimiter = ';'
                    elif '\t' in first_line and first_line.count('\t') > first_line.count(','):
                        delimiter = '\t'

                    reader = csv.DictReader(io.StringIO(text_data), delimiter=delimiter)
                    for row in reader:
                        raw_rows.append(row)

                elif fname.endswith(('.xls', '.xlsx')):
                    import pandas as pd
                    file_bytes = uploaded_file.read()
                    df = pd.read_excel(io.BytesIO(file_bytes))

                    has_known_col = any(
                        any(c in re.sub(r'[^a-z0-9]', '', str(col).lower()) for c in ['name', 'scan', 'procedure', 'price', 'code', 'rate'])
                        for col in df.columns
                    )
                    if not has_known_col and len(df) > 0:
                        row0 = df.iloc[0]
                        has_row0_header = any(
                            any(c in re.sub(r'[^a-z0-9]', '', str(v).lower()) for c in ['name', 'scan', 'procedure', 'price', 'code', 'rate'])
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
                return Response(
                    {'detail': f'Error reading uploaded file: {str(e)}'},
                    status=status.HTTP_400_BAD_REQUEST
                )
        elif hasattr(request, 'data') and 'items' in request.data:
            items = request.data.get('items', [])
            if isinstance(items, list):
                raw_rows = items
        else:
            return Response(
                {'detail': 'No file or items data provided for bulk upload.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        if not raw_rows:
            return Response(
                {'detail': 'The uploaded file contains no data rows.'},
                status=status.HTTP_400_BAD_REQUEST
            )

        req_data = getattr(request, 'data', None) or getattr(request, 'POST', {}) or {}
        default_category = (req_data.get('default_category') or req_data.get('category') or '').strip()

        from radio_lab.models import RadioLabInventory
        from users.models import User
        staff = request.user if getattr(request, 'user', None) and request.user.is_authenticated else None
        if not staff:
            staff = User.objects.first()

        created_count = 0
        updated_count = 0
        skipped = []
        rad_counter = RadiologyProcedure.objects.count()

        valid_categories = {
            'ultrasound': 'Ultrasound',
            'sonography': 'Ultrasound',
            'x-ray': 'X-Ray',
            'xray': 'X-Ray',
            'radiography': 'X-Ray',
            'ct scan': 'CT Scan',
            'ct': 'CT Scan',
            'cat scan': 'CT Scan',
            'mri': 'MRI',
            'magnetic resonance': 'MRI',
            'echocardiography': 'Echocardiography',
            'echo': 'Echocardiography',
            'ecg': 'ECG',
            'ekg': 'ECG',
            'electrocardiogram': 'ECG',
            'mammography': 'Mammography',
            'special procedures': 'Special Procedures',
            'general imaging': 'General Imaging'
        }

        def infer_category(proc_name, fallback_cat=''):
            if fallback_cat and str(fallback_cat).strip():
                fb = str(fallback_cat).strip().lower()
                return valid_categories.get(fb, fallback_cat)
            n = str(proc_name or '').lower()
            if any(k in n for k in ['x-ray', 'xray', 'plain radiograph', 'pa view', 'ap view', 'radiograph']):
                return 'X-Ray'
            if any(k in n for k in ['ct scan', 'ct ', 'computed tomograph', 'cat scan']) or n.startswith('ct '):
                return 'CT Scan'
            if any(k in n for k in ['mri', 'magnetic reson']):
                return 'MRI'
            if any(k in n for k in ['echocardiog', 'echo ']) or n.startswith('echo'):
                return 'Echocardiography'
            if any(k in n for k in ['ecg', 'ekg', 'electrocardiog']):
                return 'ECG'
            if any(k in n for k in ['mammo']):
                return 'Mammography'
            if any(k in n for k in ['fluoroscop', 'barium', 'hsg', 'ivu', 'ivp', 'contrast']):
                return 'Special Procedures'
            if any(k in n for k in ['ultra', 'sonog', 'scan', 'doppler', 'pelvic', 'obstetr', 'abdomin', 'transvagin', 'follicul']):
                return 'Ultrasound'
            return 'General Imaging'

        def find_field_value(norm_dict, candidate_keys):
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
            for k, v in row.items():
                if k is not None:
                    clean_k = re.sub(r'[^a-z0-9]', '', str(k).lower())
                    if clean_k:
                        norm_row[clean_k] = v

            # 1. SCAN / PROCEDURE NAME
            name = find_field_value(norm_row, [
                'scanname', 'procedurename', 'name', 'itemname', 'item', 'procedure',
                'scan', 'description', 'testname', 'investigationname', 'investigation',
                'scanprocedurename', 'procedurescanname', 'title', 'service', 'servicename',
                'scandescription', 'proceduredescription'
            ])

            # Positional fallback if name header wasn't recognized
            if not name:
                for v in non_empty_values:
                    sv = str(v).strip()
                    if len(sv) > 2 and not re.match(r'^\d+(\.\d+)?$', sv) and not re.match(r'^[A-Z0-9]{2,6}-\d+$', sv, re.I):
                        name = sv
                        break

            if not name or not str(name).strip():
                skipped.append(f"Row {idx}: Missing scan/procedure name")
                continue

            name = str(name).strip()

            # 2. SCAN / PROCEDURE CODE
            raw_code = find_field_value(norm_row, [
                'scancode', 'procedurecode', 'code', 'scanid', 'procedureid', 'id',
                'itemid', 'itemcode', 'scanprocedurecode', 'procedurescancode', 'radcode',
                'serialnumber', 'no'
            ])
            code = str(raw_code).strip().upper() if raw_code and str(raw_code).strip() not in ('', 'nan', 'none', 'null') else ""

            # 3. BASE PRICE
            raw_price = find_field_value(norm_row, [
                'price', 'baseprice', 'rate', 'tariff', 'amount', 'fee', 'cost',
                'charge', 'basepricengn', 'pricengn', 'generalprice', 'standardprice'
            ])
            if raw_price is not None:
                clean_p_str = re.sub(r'[^\d.]', '', str(raw_price))
                try:
                    base_price = Decimal(clean_p_str) if clean_p_str else Decimal('0.00')
                except Exception:
                    base_price = Decimal('0.00')
            else:
                base_price = Decimal('0.00')

            # 4. CATEGORY / MODALITY (auto-inferred if absent)
            raw_cat = find_field_value(norm_row, [
                'category', 'modality', 'dept', 'department', 'type', 'scantype',
                'categorymodality', 'modalitycategory'
            ])
            if raw_cat and str(raw_cat).strip() not in ('', 'nan', 'none', 'null'):
                cat_clean = str(raw_cat).strip()
                category = valid_categories.get(cat_clean.lower(), cat_clean)
            else:
                category = infer_category(name, default_category)

            # 5. TARGET BODY PART (optional)
            body_part = find_field_value(norm_row, [
                'targetbodypart', 'bodypart', 'region', 'organ', 'anatomicalregion', 'site'
            ])
            body_part = str(body_part).strip() if body_part else ""

            # 6. PREPARATION INSTRUCTIONS (optional)
            prep = find_field_value(norm_row, [
                'preparationinstructions', 'preparation', 'instructions', 'notes', 'prep'
            ])
            prep = str(prep).strip() if prep else ""

            # 7. ESTIMATED DURATION (optional, default 15 mins)
            raw_duration = find_field_value(norm_row, [
                'estimateddurationminutes', 'durationminutes', 'duration', 'estimatedduration', 'time'
            ])
            try:
                duration = int(re.sub(r'[^\d]', '', str(raw_duration))) if raw_duration else 15
            except Exception:
                duration = 15

            # 8. IS ACTIVE (optional, default True)
            raw_active = find_field_value(norm_row, ['isactive', 'active', 'status'])
            is_active = True
            if raw_active is not None:
                s_active = str(raw_active).strip().lower()
                is_active = s_active not in ('no', 'false', '0', 'inactive', 'disabled')

            # STRICT DUPLICATE PREVENTION:
            # 1. Search by exact code (if provided)
            # 2. Search by exact name (case-insensitive)
            proc = None
            if code:
                proc = RadiologyProcedure.objects.filter(code__iexact=code).first()
            if not proc:
                proc = RadiologyProcedure.objects.filter(name__iexact=name).first()

            if proc:
                # Update existing record — DO NOT CREATE DUPLICATE
                proc.name = name
                if code and not proc.code:
                    proc.code = code
                if category and category != 'General Imaging':
                    proc.category = category
                if body_part:
                    proc.body_part = body_part
                if base_price > 0 or not proc.base_price:
                    proc.base_price = base_price
                if prep:
                    proc.preparation_instructions = prep
                if duration and duration != 15:
                    proc.estimated_duration_minutes = duration
                proc.is_active = is_active
                proc.save()
                updated_count += 1
            else:
                if not code:
                    rad_counter += 1
                    cand_code = f"RAD-{rad_counter:03d}"
                    while RadiologyProcedure.objects.filter(code__iexact=cand_code).exists():
                        rad_counter += 1
                        cand_code = f"RAD-{rad_counter:03d}"
                    code = cand_code

                proc = RadiologyProcedure.objects.create(
                    code=code,
                    name=name,
                    category=category,
                    body_part=body_part,
                    base_price=base_price,
                    preparation_instructions=prep,
                    estimated_duration_minutes=duration,
                    is_active=is_active
                )
                created_count += 1

            # Sync General baseline tariff in RadioLabInventory (STRICT DUPLICATE PREVENTION)
            gen_tariff = RadioLabInventory.objects.filter(
                type='R',
                sponsor__isnull=True,
                plan__isnull=True
            ).filter(Q(item_id__iexact=proc.code) | Q(item__iexact=proc.name)).first()

            if gen_tariff:
                gen_tariff.item = proc.name
                gen_tariff.item_id = proc.code
                if proc.base_price > 0:
                    gen_tariff.rate = proc.base_price
                gen_tariff.save()
            else:
                RadioLabInventory.objects.create(
                    item=proc.name,
                    item_id=proc.code,
                    rate=proc.base_price,
                    type='R',
                    sponsor=None,
                    plan=None,
                    staff=staff
                )

        detail_msg = f"Bulk upload completed: {created_count} scan(s) created, {updated_count} updated."
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

    @action(detail=False, methods=['get'], url_path='download-template')
    def download_template(self, request):
        """
        Download simplified Excel (.xlsx) template with Scan Name, Scan Code, and Price.
        Users can update additional parameters (modality, body part, preparation) after upload.
        """
        import io
        import openpyxl
        from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from django.http import HttpResponse

        wb = openpyxl.Workbook()

        # Sheet 1: Template
        ws = wb.active
        ws.title = "Radiology Scans Template"
        ws.views.sheetView[0].showGridLines = True

        headers = [
            "Scan Name *",
            "Scan Code",
            "Price (₦) *"
        ]
        ws.append(headers)

        header_fill = PatternFill(start_color="6D28D9", end_color="6D28D9", fill_type="solid")
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

        sample_rows = [
            ["Pelvic Ultrasound Scan", "RAD-001", 12000],
            ["Obstetric Ultrasound Scan", "RAD-002", 15000],
            ["Abdominal Ultrasound Scan", "RAD-003", 15000],
            ["Chest X-Ray (PA View)", "RAD-004", 9500],
            ["Lumbosacral Spine X-Ray (AP/Lat)", "RAD-005", 16000],
            ["Computed Tomography (CT) Brain", "RAD-006", 85000],
            ["Magnetic Resonance Imaging (MRI) Lumbar Spine", "RAD-007", 120000],
            ["Echocardiography (2D with Doppler)", "RAD-008", 35000],
            ["12-Lead Electrocardiogram (ECG)", "RAD-009", 8000],
            ["Bilateral Screening Mammography", "RAD-010", 28000]
        ]

        row_fill_alt = PatternFill(start_color="F5F3FF", end_color="F5F3FF", fill_type="solid")

        for r_idx, r_data in enumerate(sample_rows, start=2):
            ws.append(r_data)
            for c_idx in range(1, len(headers) + 1):
                cell = ws.cell(row=r_idx, column=c_idx)
                cell.font = Font(name="Calibri", size=10)
                cell.border = thin_border
                cell.alignment = Alignment(vertical="center")
                if r_idx % 2 == 1:
                    cell.fill = row_fill_alt
                if c_idx == 3:
                    cell.number_format = '#,##0.00'
                    cell.alignment = Alignment(horizontal="right", vertical="center")
                elif c_idx == 2:
                    cell.alignment = Alignment(horizontal="center", vertical="center")
            ws.row_dimensions[r_idx].height = 20

        # Auto fit column widths
        col_widths = {1: 42, 2: 18, 3: 20}
        for col_idx, width in col_widths.items():
            col_letter = get_column_letter(col_idx)
            ws.column_dimensions[col_letter].width = width

        # Sheet 2: Reference & Instructions
        ws_ref = wb.create_sheet(title="Instructions & Guide")
        ws_ref.views.sheetView[0].showGridLines = True

        ws_ref.append(["Radiology Catalog Bulk Import Instructions"])
        ws_ref.cell(row=1, column=1).font = Font(name="Calibri", size=13, bold=True, color="6D28D9")
        ws_ref.merge_cells("A1:C1")

        guide_headers = ["Field Name", "Requirement", "Description & Usage"]
        ws_ref.append(guide_headers)
        for col_num in range(1, len(guide_headers) + 1):
            cell = ws_ref.cell(row=2, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.border = thin_border
            cell.alignment = Alignment(horizontal="center", vertical="center")

        guide_rows = [
            ["Scan Name *", "Required", "Full name of the scan or diagnostic procedure (e.g. Chest X-Ray PA View, Pelvic Ultrasound Scan)."],
            ["Scan Code", "Optional", "Unique procedure code (e.g. RAD-001, US-01). If left blank, sequential RAD codes are automatically generated."],
            ["Price (₦) *", "Required", "Standard out-of-pocket base price in Naira. Automatically syncs with the general hospital billing tariff."],
            ["Other Fields", "Edit After Upload", "Modality category (Ultrasound, X-Ray, CT, MRI, etc.), body regions, preparation notes, and duration can be updated anytime after upload."]
        ]

        for g_idx, g_data in enumerate(guide_rows, start=3):
            ws_ref.append(g_data)
            for c_idx in range(1, len(guide_headers) + 1):
                cell = ws_ref.cell(row=g_idx, column=c_idx)
                cell.font = Font(name="Calibri", size=10)
                cell.border = thin_border
                if c_idx == 2 and "Required" in g_data[1]:
                    cell.font = Font(name="Calibri", size=10, bold=True, color="DC2626")

        ws_ref.column_dimensions['A'].width = 24
        ws_ref.column_dimensions['B'].width = 20
        ws_ref.column_dimensions['C'].width = 70

        output = io.BytesIO()
        wb.save(output)
        output.seek(0)

        response = HttpResponse(
            output.getvalue(),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )
        response['Content-Disposition'] = 'attachment; filename="radiology_catalog_bulk_template.xlsx"'
        return response

