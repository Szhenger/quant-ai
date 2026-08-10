from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"
    # Historical app label: preserves the migration history and the core_*
    # table names from before the functional-structure reorganization.
    label = "core"
