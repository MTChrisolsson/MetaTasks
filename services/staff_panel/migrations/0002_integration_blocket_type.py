from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('staff_panel', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='integration',
            name='integration_type',
            field=models.CharField(
                max_length=50,
                choices=[
                    ('slack', 'Slack'),
                    ('teams', 'Microsoft Teams'),
                    ('google', 'Google Workspace'),
                    ('github', 'GitHub'),
                    ('jira', 'Jira'),
                    ('zapier', 'Zapier'),
                    ('webhook', 'Custom Webhook'),
                    ('blocket', 'Blocket'),
                ],
            ),
        ),
    ]
