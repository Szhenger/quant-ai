"""State-only: the watchlist models (WatchedTicker, StockPage, QuantSnapshot)
now live in the ``watchlist`` app. Their tables keep their ``core_*`` names via
``db_table`` there, so nothing changes in the database — this migration only
removes the models from the ``core`` app's state, and ``watchlist/0001`` adds
them to the new app's state in the same shape.
"""
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_watchedticker_recompute_interval_hours_and_more'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
            migrations.RemoveField(
                model_name='stockpage',
                name='watched_ticker',
            ),
            migrations.AlterUniqueTogether(
                name='watchedticker',
                unique_together=None,
            ),
            migrations.RemoveField(
                model_name='watchedticker',
                name='workspace',
            ),
            migrations.DeleteModel(
                name='QuantSnapshot',
            ),
            migrations.DeleteModel(
                name='StockPage',
            ),
            migrations.DeleteModel(
                name='WatchedTicker',
            ),
            ],
        ),
    ]
