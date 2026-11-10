# Round 2: remember which AI model answered last (indicator on Home/Settings).
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_fill_display_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='usersettings',
            name='last_model_used',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
        migrations.AddField(
            model_name='usersettings',
            name='last_model_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
