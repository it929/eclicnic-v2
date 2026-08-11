# from django.db.models.signals import post_save, post_delete
# from django.dispatch import receiver
# from haystack import connections
# from .models import PatientProfile

# @receiver(post_save, sender=PatientProfile)
# def update_patient_index(sender, instance, created, **kwargs):
#     """Update Whoosh index when patient is saved"""
#     try:
#         using = 'default'
#         backend = connections[using].get_backend()
        
#         # Pass as list, not single object
#         backend.update([instance])
        
#         print(f"✅ Index {'created' if created else 'updated'} for: {instance}")
#     except Exception as e:
#         print(f"❌ Error updating index: {e}")

# @receiver(post_delete, sender=PatientProfile)
# def delete_patient_index(sender, instance, **kwargs):
#     """Remove from Whoosh index when patient is deleted"""
#     try:
#         using = 'default'
#         backend = connections[using].get_backend()
        
#         #  Pass as list
#         backend.remove([instance])
        
#         print(f"✅ Index removed for: {instance}")
#     except Exception as e:
#         print(f"❌ Error removing from index: {e}")