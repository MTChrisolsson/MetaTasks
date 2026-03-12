from rest_framework import serializers
from .models import StatistikJob, VehicleRecord, AnalyticsReport, VehicleValuation


class VehicleRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleRecord
        fields = [
            'id', 'registration', 'make', 'model', 'year', 'mileage',
            'condition', 'transmission', 'fuel_type', 'published_price',
            'status', 'current_station',
            'days_in_stock', 'is_published', 'is_photographed', 'photo_count',
            'needs_photos', 'missing_citk', 'is_sold', 'notes', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class StatistikJobSerializer(serializers.ModelSerializer):
    vehicles = VehicleRecordSerializer(source='vehicle_records', many=True, read_only=True)
    
    class Meta:
        model = StatistikJob
        fields = [
            'id', 'organization', 'created_by', 'status', 'uploaded_at',
            'processed_at', 'kpis', 'station_stats', 'vehicles', 'error_message'
        ]
        read_only_fields = ['id', 'uploaded_at', 'processed_at', 'created_by']


class AnalyticsReportSerializer(serializers.ModelSerializer):
    class Meta:
        model = AnalyticsReport
        fields = ['id', 'organization', 'job', 'report_type', 'title', 'generated_at', 'excel_file', 'pdf_file']
        read_only_fields = ['id', 'generated_at']


class VehicleValuationSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleValuation
        fields = [
            'id', 'job', 'vehicle', 'registration',
            'make', 'model', 'year', 'mileage', 'condition',
            'transmission', 'fuel_type', 'published_price',
            'estimated_market_value', 'fairness_assessment',
            'suggested_price', 'ai_explanation', 'model_name',
            'created_at',
        ]
        read_only_fields = ['id', 'created_at']


class VehicleValuationRequestSerializer(serializers.Serializer):
    vehicle_id = serializers.IntegerField(required=False)
    job_id = serializers.IntegerField(required=False)
    batch = serializers.BooleanField(required=False, default=False)

    make = serializers.CharField(required=False, allow_blank=True)
    model = serializers.CharField(required=False, allow_blank=True)
    year = serializers.IntegerField(required=False)
    mileage = serializers.IntegerField(required=False, allow_null=True)
    condition = serializers.CharField(required=False, allow_blank=True)
    transmission = serializers.CharField(required=False, allow_blank=True)
    fuel_type = serializers.CharField(required=False, allow_blank=True)
    published_price = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)

    def validate(self, attrs):
        vehicle_id = attrs.get('vehicle_id')
        job_id = attrs.get('job_id')
        batch = attrs.get('batch', False)

        if not vehicle_id and not job_id:
            raise serializers.ValidationError('Either vehicle_id or job_id must be provided.')

        if batch and not job_id:
            raise serializers.ValidationError('job_id is required when batch=true.')

        if batch and vehicle_id:
            raise serializers.ValidationError('vehicle_id cannot be combined with batch=true.')

        if job_id and vehicle_id:
            raise serializers.ValidationError('Provide either vehicle_id or job_id, not both.')

        return attrs


class VehicleValuationBatchResponseSerializer(serializers.Serializer):
    job_id = serializers.IntegerField()
    total_vehicles = serializers.IntegerField()
    valued_vehicles = serializers.IntegerField()
    skipped_vehicles = serializers.IntegerField()
    valuations = VehicleValuationSerializer(many=True)