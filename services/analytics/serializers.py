from rest_framework import serializers
from .models import StatistikJob, VehicleRecord, AnalyticsReport


class VehicleRecordSerializer(serializers.ModelSerializer):
    class Meta:
        model = VehicleRecord
        fields = [
            'id', 'registration', 'model', 'status', 'current_station',
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