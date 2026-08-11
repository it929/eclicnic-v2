from django.apps import AppConfig
from django.db.models.signals import post_migrate

class BillingsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Billings'

    def ready(self):
        # Delay scheduler start until after migrations are complete
        import sys
        if 'migrate' not in sys.argv and 'makemigrations' not in sys.argv:
            # Using post_migrate signal to start scheduler after database is ready
            from django.db.models.signals import post_migrate
            post_migrate.connect(self.start_scheduler_after_migrate, sender=self)
    
    def start_scheduler_after_migrate(self, **kwargs):
        """Start scheduler after migrations are complete"""
        from .scheduler import start_scheduler
        start_scheduler()