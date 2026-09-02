"""State-only: adopt the watchlist tables from the ``core`` app.

The tables already exist (created by core/0001 and core/0002 under their
``core_*`` names, which ``db_table`` pins); this migration only tells Django
that the ``watchlist`` app owns those models now. Depends on core/0003, which
removed them from the old app's state first.
"""

import django.core.validators
import django.db.models.deletion
import uuid
import watchlist.models
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0003_move_watchlist_models'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
            migrations.CreateModel(
                name='WatchedTicker',
                fields=[
                    ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                    ('ticker', models.CharField(max_length=16)),
                    ('note', models.CharField(blank=True, default='', max_length=255)),
                    ('refresh_interval_hours', models.PositiveIntegerField(default=watchlist.models._default_refresh_hours, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(720)])),
                    ('recompute_interval_hours', models.PositiveIntegerField(default=watchlist.models._default_recompute_hours, validators=[django.core.validators.MinValueValidator(1), django.core.validators.MaxValueValidator(2160)])),
                    ('created_at', models.DateTimeField(auto_now_add=True)),
                    ('workspace', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='watchlist', to='core.workspace')),
                ],
                options={
                    'db_table': 'core_watchedticker',
                    'ordering': ['ticker'],
                    'unique_together': {('workspace', 'ticker')},
                },
            ),
            migrations.CreateModel(
                name='StockPage',
                fields=[
                    ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                    ('quantitative', models.JSONField(blank=True, default=dict)),
                    ('quantitative_summary', models.JSONField(blank=True, default=dict)),
                    ('qualitative', models.JSONField(blank=True, default=dict)),
                    ('qualitative_summary', models.JSONField(blank=True, default=dict)),
                    ('data_synthetic', models.BooleanField(default=False)),
                    ('refreshed_at', models.DateTimeField(blank=True, null=True)),
                    ('recomputed_at', models.DateTimeField(blank=True, null=True)),
                    ('updated_at', models.DateTimeField(auto_now=True)),
                    ('watched_ticker', models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name='page', to='watchlist.watchedticker')),
                ],
                options={
                    'db_table': 'core_stockpage',
                },
            ),
            migrations.CreateModel(
                name='QuantSnapshot',
                fields=[
                    ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                    ('taken_at', models.DateTimeField(auto_now_add=True)),
                    ('compressed', models.BinaryField()),
                    ('watched_ticker', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='snapshots', to='watchlist.watchedticker')),
                ],
                options={
                    'db_table': 'core_quantsnapshot',
                    'ordering': ['-taken_at'],
                    'indexes': [models.Index(fields=['watched_ticker', '-taken_at'], name='core_quants_watched_02cfad_idx')],
                },
            ),
            ],
        ),
    ]
