# Round 2 / Q6: the display name is separate from the login. Existing rows with
# an empty display_name get the username, so nothing changes visually.
from django.db import migrations
from django.db.models import Q


def fill_display_name(apps, schema_editor):
    UserSettings = apps.get_model('core', 'UserSettings')
    for row in UserSettings.objects.filter(Q(display_name='') | Q(display_name__isnull=True)).select_related('user'):
        row.display_name = row.user.username[:100]
        row.save(update_fields=['display_name'])


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_alter_usersettings_github_token_length'),
    ]

    operations = [
        migrations.RunPython(fill_display_name, migrations.RunPython.noop),
    ]
