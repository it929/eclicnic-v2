# management/commands/load_icd11.py
from django.core.management.base import BaseCommand
from django.apps import apps

class Command(BaseCommand):
    help = 'Load ICD-11 sample data'
    
    def handle(self, *args, **options):
        self.stdout.write("Starting ICD-11 data load...")
        
        # Get models
        try:
            ICD11Category = apps.get_model('queue_operations', 'ICD11Category')
            ICD11Code = apps.get_model('queue_operations', 'ICD11Code')
        except LookupError:
            self.stdout.write(self.style.ERROR("Models not found. Make sure your app is in INSTALLED_APPS"))
            return
        
        # Clear existing data
        ICD11Code.objects.all().delete()
        ICD11Category.objects.all().delete()
        
        # Create sample data
        categories = [
            {'code': '1', 'title': 'Certain infectious or parasitic diseases'},
            {'code': '2', 'title': 'Neoplasms'},
            {'code': '3', 'title': 'Diseases of the blood'},
            {'code': '4', 'title': 'Diseases of the immune system'},
            {'code': '5', 'title': 'Endocrine, nutritional or metabolic diseases'},
        ]
        
        codes_data = [
            # Infectious diseases
            ('1A00', 'Cholera', '1'),
            ('1B00', 'Tuberculosis', '1'),
            ('1C00', 'HIV disease', '1'),
            
            # Neoplasms
            ('2A00', 'Malignant neoplasms', '2'),
            ('2B00', 'Benign neoplasms', '2'),
            
            # Blood diseases
            ('3A00', 'Anaemia', '3'),
            
            # Immune system
            ('4A00', 'Autoimmune diseases', '4'),
            
            # Endocrine
            ('5A00', 'Diabetes mellitus', '5'),
            ('5B00', 'Obesity', '5'),
        ]
        
        # Create categories
        category_objs = {}
        for cat in categories:
            obj = ICD11Category.objects.create(
                code=cat['code'],
                title=cat['title'],
                level=0
            )
            category_objs[cat['code']] = obj
            self.stdout.write(f"Created category: {cat['code']} - {cat['title']}")
        
        # Create codes
        for code, title, cat_code in codes_data:
            ICD11Code.objects.create(
                code=code,
                title=title,
                category=category_objs[cat_code],
                is_leaf=True
            )
            self.stdout.write(f"Created code: {code} - {title}")
        
        self.stdout.write(self.style.SUCCESS("Successfully loaded ICD-11 sample data!"))