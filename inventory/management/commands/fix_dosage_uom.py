import json
from datetime import datetime
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand

from inventory.categories import infer_dosage_uom
from inventory.models import Product


class Command(BaseCommand):
    help = (
        "Set each product's dosage type / UoM (minimum_UoM) from its drug category and name. "
        "By default only products still on the import default ('tablets' or blank) are touched, "
        "and a JSON backup of the old values is written first. Use --all to re-derive every product."
    )

    def add_arguments(self, parser):
        parser.add_argument('--all', action='store_true', help='Re-derive every product, not just tablets/blank ones.')
        parser.add_argument('--dry-run', action='store_true', help='Show what would change without saving.')
        parser.add_argument('--restore', metavar='BACKUP_JSON', help='Put back the UoM values saved in a backup file.')

    def handle(self, *args, **opts):
        if opts['restore']:
            data = json.loads(Path(opts['restore']).read_text(encoding='utf-8'))
            products = list(Product.objects.filter(id__in=[int(k) for k in data]))
            for p in products:
                p.minimum_UoM = data[str(p.id)]
            Product.objects.bulk_update(products, ['minimum_UoM'], batch_size=500)
            self.stdout.write(self.style.SUCCESS(f"Restored {len(products)} product(s)."))
            return

        qs = Product.objects.all()
        if not opts['all']:
            qs = qs.filter(minimum_UoM__in=['', 'tablets']) | qs.filter(minimum_UoM__isnull=True)

        changed, backup, summary = [], {}, {}
        for p in qs.only('id', 'product_name', 'minimum_UoM', 'category').iterator():
            new_uom = infer_dosage_uom(p.category, p.product_name)
            if new_uom != (p.minimum_UoM or ''):
                backup[str(p.id)] = p.minimum_UoM or ''
                p.minimum_UoM = new_uom
                changed.append(p)
                summary[new_uom] = summary.get(new_uom, 0) + 1

        for uom, n in sorted(summary.items(), key=lambda kv: -kv[1]):
            self.stdout.write(f"  {uom:<18} {n}")

        if opts['dry_run']:
            self.stdout.write(self.style.SUCCESS(f"Would update {len(changed)} product(s)."))
            return
        if changed:
            backup_dir = Path(settings.BASE_DIR) / 'backups'
            backup_dir.mkdir(exist_ok=True)
            backup_file = backup_dir / f"uom_backup_{datetime.now():%Y%m%d_%H%M%S}.json"
            backup_file.write_text(json.dumps(backup, indent=0), encoding='utf-8')
            Product.objects.bulk_update(changed, ['minimum_UoM'], batch_size=500)
            self.stdout.write(f"Backup of previous values: {backup_file}")
        self.stdout.write(self.style.SUCCESS(f"Updated {len(changed)} product(s)."))
