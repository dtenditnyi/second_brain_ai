# B-14: a Fernet-encrypted token of 128+ characters exceeds 255 characters.
from django.db import migrations
import core.models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0006_usersettings_ai_strategy'),
    ]

    operations = [
        migrations.AlterField(
            model_name='usersettings',
            name='github_token',
            field=core.models.EncryptedCharField(blank=True, default='', max_length=500),
        ),
    ]
