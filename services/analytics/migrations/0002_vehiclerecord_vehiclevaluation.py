from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('services_analytics', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='vehiclerecord',
            name='condition',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='vehiclerecord',
            name='fuel_type',
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name='vehiclerecord',
            name='make',
            field=models.CharField(blank=True, max_length=120),
        ),
        migrations.AddField(
            model_name='vehiclerecord',
            name='mileage',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='vehiclerecord',
            name='published_price',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='vehiclerecord',
            name='transmission',
            field=models.CharField(blank=True, max_length=60),
        ),
        migrations.AddField(
            model_name='vehiclerecord',
            name='year',
            field=models.IntegerField(blank=True, null=True),
        ),
        migrations.CreateModel(
            name='VehicleValuation',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('registration', models.CharField(blank=True, max_length=50)),
                ('make', models.CharField(max_length=120)),
                ('model', models.CharField(max_length=200)),
                ('year', models.IntegerField()),
                ('mileage', models.IntegerField(blank=True, null=True)),
                ('condition', models.CharField(blank=True, max_length=120)),
                ('transmission', models.CharField(blank=True, max_length=60)),
                ('fuel_type', models.CharField(blank=True, max_length=60)),
                ('published_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('estimated_market_value', models.DecimalField(decimal_places=2, max_digits=12)),
                ('fairness_assessment', models.CharField(choices=[('below_market', 'Below Market'), ('fair', 'Fair'), ('above_market', 'Above Market')], max_length=20)),
                ('suggested_price', models.DecimalField(decimal_places=2, max_digits=12)),
                ('ai_explanation', models.TextField()),
                ('raw_response', models.JSONField(blank=True, null=True)),
                ('model_name', models.CharField(default='llama-3.1-8b-instant', max_length=120)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='valuations', to='services_analytics.statistikjob')),
                ('vehicle', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='valuations', to='services_analytics.vehiclerecord')),
            ],
            options={
                'ordering': ['-created_at'],
                'indexes': [
                    models.Index(fields=['job', 'created_at'], name='services_an_job_id_c00fce_idx'),
                    models.Index(fields=['vehicle', 'created_at'], name='services_an_vehicle_11297d_idx'),
                    models.Index(fields=['fairness_assessment'], name='services_an_fairnes_c2b498_idx'),
                ],
            },
        ),
    ]
