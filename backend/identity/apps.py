from django.apps import AppConfig


class IdentityConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "identity"
    # Historical app label: preserves the migration history and the core_*
    # table names from before the by-feature reorganization (the watchlist
    # tables also keep their core_* names via db_table).
    label = "core"
