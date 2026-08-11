from haystack import indexes
from .models import PatientProfile

class PatientProfileIndex(indexes.SearchIndex, indexes.Indexable):
    text = indexes.EdgeNgramField(
        document=True, 
        use_template=True,
        boost=1.5
    )

    # auto-complete field for better searching
    autocomplete = indexes.EdgeNgramField()

    # Primary identification fields (highest boost)
    surname = indexes.CharField(model_attr='surname', boost=3.0)
    hospital_number = indexes.CharField(model_attr='hospital_number', boost=2.5)
    
    # Personal details (medium boost)
    first_name = indexes.CharField(model_attr='first_name', boost=2.0)
    other_name = indexes.CharField(model_attr='other_name', boost=1.5)
    
    # Contact info (lower boost)
    phone_number = indexes.CharField(model_attr='phone_number', boost=1.0)
    
    # Foreign key relations
    category = indexes.CharField(model_attr='category__category', null=True, boost=0.8)

    active = indexes.IntegerField(model_attr='active')
    full_name = indexes.CharField()

    def prepare_autocomplete(self, obj):
        """Prepare autocomplete data"""
        return f"{obj.surname} {obj.first_name} {obj.other_name or ''} {obj.hospital_number or ''} {obj.phone_number}"

    def prepare_full_name(self, obj):
        return f"{obj.surname} {obj.first_name} {obj.other_name or ''}".strip()

    def get_model(self):
        return PatientProfile

    def index_queryset(self, using=None):
        
        return self.get_model().objects.select_related('category').only(
            'id', 'surname', 'first_name', 'other_name', 'hospital_number', 
            'phone_number', 'category', 'active'
        ).filter(active=1).order_by('id')  