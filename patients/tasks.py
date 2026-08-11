# # tasks.py - UPDATED
# from celery import shared_task
# from django.db import connection
# from haystack.management.commands import update_index
# from .models import PatientProfile
# import logging

# logger = logging.getLogger(__name__)

# @shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=30, max_retries=3)
# def async_index_update(self, patient_id):
#     """
#     Async task to update search index with proper connection handling
#     """
#     try:
#         # Ensure database connection is open
#         from django.db import connection
#         if connection.connection is None:
#             connection.connect()
        
#         try:
#             patient = PatientProfile.objects.get(pk=patient_id)
            
#             # Update the search index
#             # Using Haystack's update_index command
#             update_index.Command().handle(
#                 using=['default'],
#                 remove=False,  # Don't remove, just update
#                 verbosity=0,
#                 batchsize=100,
#                 workers=1  # Reduce workers for safety
#             )
            
#             logger.info(f"Successfully updated search index for patient {patient_id}")
            
#         except PatientProfile.DoesNotExist:
#             # Handle deleted patients
#             update_index.Command().handle(
#                 using=['default'],
#                 remove=True,  # Remove deleted entries
#                 verbosity=0
#             )
#             logger.info(f"Cleaned up index for deleted patient {patient_id}")
            
#         except Exception as e:
#             logger.error(f"Error updating index for patient {patient_id}: {str(e)}")
#             raise  # Let Celery handle retry
            
#     finally:
#         # Always close connection when done
#         try:
#             connection.close()
#         except:
#             pass