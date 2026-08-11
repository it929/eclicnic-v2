from django.apps import AppConfig


class IpdConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'IPD'

    # def ready(self):
    #     import IPD.signals


