from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('inventory', '0002_inventorylocation_view_settings'),
    ]

    operations = [
        migrations.AddField(
            model_name='inventoryfielddefinition',
            name='location',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name='custom_field_definitions',
                to='inventory.inventorylocation',
            ),
        ),
    ]