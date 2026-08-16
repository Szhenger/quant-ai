from django.apps import AppConfig


class EngineConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "engine"
    # Historical app label: preserves the migration history and the
    # strategies_* table names from before the functional-structure
    # reorganization.
    label = "strategies"
