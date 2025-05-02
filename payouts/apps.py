from django.apps import AppConfig

class PayoutsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'payouts'

    def ready(self):
        import payouts.signals  # noqa