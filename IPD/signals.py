from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import DrugPrescription
from .utils.drug_schedule import create_administration_schedule


@receiver(post_save, sender=DrugPrescription)
def generate_schedule(sender, instance, created, **kwargs):

    if created:
        create_administration_schedule(instance)
