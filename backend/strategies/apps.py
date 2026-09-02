from django.apps import AppConfig


class StrategiesConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "strategies"
    # The label was "strategies" through the package's "engine" era, so the
    # migration history and the strategies_* table names carry straight over.
    label = "strategies"
