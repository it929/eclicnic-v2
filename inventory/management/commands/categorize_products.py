from django.core.management.base import BaseCommand

from inventory.categories import infer_product_category
from inventory.models import Product


class Command(BaseCommand):
    help = (
        "Auto-assign drug categories (vaccine, tablet, injection, ...) from item name / unit of measure. "
        "By default only items without a category are updated; use --all to re-classify everything "
        "(this overwrites categories staff set manually)."
    )

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Re-classify every product, not just uncategorised ones.')
        parser.add_argument('--dry-run', action='store_true', help='Show what would change without saving.')

    def handle(self, *args, **opts):
        qs = Product.objects.all() if opts['all'] else Product.objects.filter(category='')
        changed = []
        for p in qs.only('id', 'product_name', 'minimum_UoM', 'category').iterator():
            new_cat = infer_product_category(p.product_name, p.minimum_UoM)
            if new_cat != p.category:
                p.category = new_cat
                changed.append(p)
        if not opts['dry_run'] and changed:
            Product.objects.bulk_update(changed, ['category'], batch_size=500)
        verb = 'Would update' if opts['dry_run'] else 'Updated'
        self.stdout.write(self.style.SUCCESS(f"{verb} {len(changed)} product(s)."))
