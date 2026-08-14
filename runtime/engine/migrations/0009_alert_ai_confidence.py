from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("strategies", "0008_merge_20260810_2059"),
    ]

    operations = [
        migrations.AddField(
            model_name="alert",
            name="ai_confidence",
            field=models.FloatField(blank=True, null=True),
        ),
    ]
