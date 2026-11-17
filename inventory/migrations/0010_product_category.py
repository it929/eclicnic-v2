from django.db import migrations, models

from inventory.categories import PRODUCT_CATEGORIES, infer_product_category


def backfill_categories(apps, schema_editor):
    Product = apps.get_model('inventory', 'Product')
    to_update = []
    for p in Product.objects.filter(category='').only('id', 'product_name', 'minimum_UoM').iterator():
        p.category = infer_product_category(p.product_name, p.minimum_UoM)
        to_update.append(p)
        if len(to_update) >= 500:
            Product.objects.bulk_update(to_update, ['category'])
            to_update = []
    if to_update:
        Product.objects.bulk_update(to_update, ['category'])


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0009_storestockbatch'),
    ]

    operations = [
        migrations.AddField(
            model_name='product',
            name='category',
            field=models.CharField(blank=True, choices=PRODUCT_CATEGORIES, db_index=True, default='', max_length=20),
        ),
        migrations.RunPython(backfill_categories, migrations.RunPython.noop),
    ]
