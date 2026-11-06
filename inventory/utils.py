import re

def get_next_isl_sku():
    """
    Finds the highest ISL-xxx number across Product and PharmacyTariff models,
    and returns the next sequential SKU formatted as ISL-001, ISL-002, etc.
    """
    from inventory.models import Product, PharmacyTariff

    max_num = 0
    sku_pattern = re.compile(r'^ISL-(\d+)$', re.IGNORECASE)

    try:
        for sku in Product.objects.filter(product_id__istartswith='ISL-').values_list('product_id', flat=True):
            if sku:
                m = sku_pattern.match(sku.strip())
                if m:
                    try:
                        num = int(m.group(1))
                        if num > max_num:
                            max_num = num
                    except ValueError:
                        pass
    except Exception:
        pass

    try:
        for sku in PharmacyTariff.objects.filter(product_id__istartswith='ISL-').values_list('product_id', flat=True):
            if sku:
                m = sku_pattern.match(sku.strip())
                if m:
                    try:
                        num = int(m.group(1))
                        if num > max_num:
                            max_num = num
                    except ValueError:
                        pass
    except Exception:
        pass

    next_num = max_num + 1
    return f"ISL-{next_num:03d}"

