from django.db import migrations, models


def normalize_usernames(apps, schema_editor):
    CustomUser = apps.get_model('accounts', 'CustomUser')

    # Detect collisions before mutating data
    lower_map = {}
    duplicates = []
    for user in CustomUser.objects.all().only('id', 'username', 'display_username'):
        lower_name = (user.username or '').strip().lower()
        if lower_name in lower_map:
            duplicates.append(lower_name)
        else:
            lower_map[lower_name] = user.id

    if duplicates:
        dupes = ', '.join(sorted(set(duplicates)))
        raise RuntimeError(
            f'Cannot migrate due to username collisions after lowercasing: {dupes}'
        )

    for user in CustomUser.objects.all():
        current = (user.username or '').strip()
        if not user.display_username:
            user.display_username = current
        user.username = current.lower()
        user.save(update_fields=['display_username', 'username'])


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='customuser',
            name='display_username',
            field=models.CharField(blank=True, max_length=150),
        ),
        migrations.RunPython(normalize_usernames, migrations.RunPython.noop),
    ]