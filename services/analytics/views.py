import logging
from io import BytesIO

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
import pandas as pd
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.models import UserProfile
from core.views import require_organization_access
from licensing.models import License, Service

from .forms import StatistikUploadForm
from .models import StatistikJob, VehicleRecord
from .serializers import StatistikJobSerializer

logger = logging.getLogger(__name__)


def _get_user_profile(user):
    """Return the user's profile or None."""
    try:
        return user.mediap_profile
    except (UserProfile.DoesNotExist, AttributeError):
        return None


def _get_analytics_service():
    return Service.objects.filter(slug='analytics', is_active=True).first()


def _get_valid_org_license(organization, service):
    licenses = License.objects.filter(
        organization=organization,
        license_type__service=service,
        status__in=['active', 'trial'],
    ).select_related('license_type', 'license_type__service')

    for license_obj in licenses:
        if license_obj.is_valid():
            return license_obj
    return None


def _to_bool(value):
    if isinstance(value, bool):
        return value
    if value in (1, '1', 'true', 'True', 'yes', 'YES', 'Y', 'y'):
        return True
    return False


def _to_int(value, fallback=0):
    try:
        if value is None or value == '':
            return fallback
        return int(value)
    except (TypeError, ValueError):
        return fallback


def _save_vehicle_records(job, rows):
    """Persist processed rows to VehicleRecord with tolerant parsing."""
    vehicle_records = []
    for row in rows:
        vehicle_records.append(
            VehicleRecord(
                job=job,
                registration=str(row.get('Reg', '') or ''),
                model=str(row.get('Model', '') or ''),
                status=_to_int(row.get('Status', 0), 0),
                current_station=str(row.get('CurrentStation', '') or ''),
                days_in_stock=_to_int(row.get('DaysInStock', None), None),
                is_published=_to_bool(row.get('Published', False)),
                is_photographed=_to_bool(row.get('Photographed', False)),
                photo_count=_to_int(row.get('PhotoCount', 0), 0),
                needs_photos=_to_bool(row.get('NeedsPhotos', False)),
                missing_citk=_to_bool(row.get('CITKMatched', False)) is False,
                is_sold=str(row.get('Status', '')).lower() == 'sold',
                notes=str(row.get('note', '') or ''),
            )
        )

    if vehicle_records:
        VehicleRecord.objects.bulk_create(vehicle_records, batch_size=500)


def _to_dataframe(rows):
    if not rows:
        return pd.DataFrame()
    normalized_rows = []
    for row in rows:
        if hasattr(row, 'to_dict'):
            normalized_rows.append(row.to_dict())
        elif isinstance(row, dict):
            normalized_rows.append(row)
        else:
            normalized_rows.append(vars(row))
    return pd.DataFrame(normalized_rows)


def _build_statistik_export_excel(job):
    result_kpis = job.kpis or {}
    station_data = job.station_stats or []

    records = VehicleRecord.objects.filter(job=job)
    inventory_24_records = records.filter(status=24)
    needs_photos_records = records.filter(is_published=True, photo_count__lt=job.photo_min_urls)
    not_published_records = records.filter(is_published=False)
    missing_citk_records = records.filter(missing_citk=True)
    sold_records = records.filter(status__in=[34, 35, 36])

    base_fields = [
        'registration',
        'status',
        'model',
        'current_station',
        'days_in_stock',
        'is_published',
        'is_photographed',
        'photo_count',
        'missing_citk',
        'notes',
    ]

    summary_df = pd.DataFrame([
        {'KPI': 'Inventory_24', 'Value': result_kpis.get('inventory_24', 0)},
        {'KPI': 'Published', 'Value': result_kpis.get('published', 0)},
        {'KPI': 'Published_%', 'Value': result_kpis.get('published_pct', 0)},
        {'KPI': 'Needs_Photos', 'Value': result_kpis.get('needs_photos', 0)},
        {'KPI': 'Missing_in_CITK', 'Value': result_kpis.get('missing_citk', 0)},
    ])
    station_df = _to_dataframe(station_data)
    inventory_df = pd.DataFrame(list(inventory_24_records.values(*base_fields)))
    needs_photos_df = pd.DataFrame(list(needs_photos_records.values(*base_fields)))
    not_published_df = pd.DataFrame(list(not_published_records.values(*base_fields)))
    missing_citk_df = pd.DataFrame(list(missing_citk_records.values(*base_fields)))
    sold_df = pd.DataFrame(list(sold_records.values(*base_fields)))

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Summary (KPI + station distribution)
        summary_df.to_excel(writer, index=False, sheet_name='Summary', startrow=0)
        start_row = len(summary_df) + 3
        station_df.to_excel(writer, index=False, sheet_name='Summary', startrow=start_row)

        # Sheet 2-7 requested detail sheets
        inventory_df.to_excel(writer, index=False, sheet_name='Inventory_24_detail')
        needs_photos_df.to_excel(writer, index=False, sheet_name='Needs_Photos')
        not_published_df.to_excel(writer, index=False, sheet_name='Not_Published')
        station_df.to_excel(writer, index=False, sheet_name='By_Station')
        missing_citk_df.to_excel(writer, index=False, sheet_name='Missing_in_CITK')
        sold_df.to_excel(writer, index=False, sheet_name='Sold')

    output.seek(0)
    return output.getvalue()


def _enforce_analytics_access_or_response(request):
    profile = _get_user_profile(request.user)
    if not profile:
        return render(request, 'analytics/no_profile.html')

    service = _get_analytics_service()
    if not service:
        messages.error(request, 'Analytics service is not configured yet.')
        return redirect('dashboard:dashboard')

    license_obj = _get_valid_org_license(profile.organization, service)
    if not license_obj:
        return render(
            request,
            'core/no_service_access.html',
            {
                'service': service,
                'organization': profile.organization,
            },
        )

    request.analytics_profile = profile
    request.analytics_license = license_obj
    request.analytics_service = service
    return None


def analytics_access_required(view_func):
    @login_required
    @require_organization_access
    def _wrapped(request, *args, **kwargs):
        response = _enforce_analytics_access_or_response(request)
        if response is not None:
            return response
        return view_func(request, *args, **kwargs)

    return _wrapped


@analytics_access_required
def index(request):
    profile = request.analytics_profile
    latest_completed = (
        StatistikJob.objects.filter(organization=profile.organization, status='completed')
        .order_by('-uploaded_at')
        .first()
    )

    recent_jobs = StatistikJob.objects.filter(organization=profile.organization).order_by('-uploaded_at')[:8]

    stats = {
        'total_jobs': StatistikJob.objects.filter(organization=profile.organization).count(),
        'completed_jobs': StatistikJob.objects.filter(
            organization=profile.organization,
            status='completed',
        ).count(),
        'failed_jobs': StatistikJob.objects.filter(
            organization=profile.organization,
            status='failed',
        ).count(),
        'latest_kpis': latest_completed.kpis if latest_completed else None,
    }

    return render(
        request,
        'analytics/dashboard.html',
        {
            'profile': profile,
            'recent_jobs': recent_jobs,
            'latest_job': latest_completed,
            'stats': stats,
        },
    )


@analytics_access_required
def upload(request):
    profile = request.analytics_profile

    if request.method == 'POST':
        form = StatistikUploadForm(request.POST, request.FILES)
        if form.is_valid():
            try:
                from .services.statistik_processor import StatistikProcessor
            except ImportError:
                messages.error(
                    request,
                    'Analytics processing dependency missing. Install pandas in the runtime environment.',
                )
                return render(request, 'analytics/upload.html', {'profile': profile, 'form': form})

            inventory = request.FILES.get('inventory')
            wayke = request.FILES.get('wayke')
            citk = request.FILES.get('citk')
            notes = request.FILES.get('notes')

            if not all([inventory, wayke, citk]):
                messages.error(request, 'Inventory, Wayke, and CITK files are required.')
                return render(request, 'analytics/upload.html', {'profile': profile, 'form': form})

            with transaction.atomic():
                job = StatistikJob.objects.create(
                    organization=profile.organization,
                    created_by=profile,
                    status='processing',
                    inventory_file=inventory,
                    wayke_file=wayke,
                    citk_file=citk,
                    notes_file=notes,
                    inventory_sheet=form.cleaned_data['inventory_sheet'],
                    citk_sheet=form.cleaned_data['citk_sheet'],
                    photo_min_urls=form.cleaned_data['photo_min_urls'],
                )

            try:
                processor = StatistikProcessor(
                    inventory_path=job.inventory_file.path,
                    wayke_path=job.wayke_file.path,
                    citk_path=job.citk_file.path,
                    notes_path=job.notes_file.path if notes else None,
                    inventory_sheet=job.inventory_sheet,
                    citk_sheet=job.citk_sheet,
                    photo_min_urls=job.photo_min_urls,
                )
                result = processor.process()

                with transaction.atomic():
                    job.kpis = result.get('kpis')
                    job.station_stats = result.get('by_station')
                    job.status = 'completed'
                    job.processed_at = timezone.now()
                    job.error_message = ''
                    job.save(
                        update_fields=['kpis', 'station_stats', 'status', 'processed_at', 'error_message']
                    )

                    _save_vehicle_records(job, result.get('inventory_24', []))

                messages.success(request, 'Analytics job completed successfully.')
                return redirect('analytics:job_detail', job_id=job.id)
            except Exception as exc:
                logger.exception('Error processing analytics job: %s', exc)
                job.status = 'failed'
                job.error_message = str(exc)
                job.processed_at = timezone.now()
                job.save(update_fields=['status', 'error_message', 'processed_at'])
                messages.error(request, f'Processing failed: {exc}')

    else:
        form = StatistikUploadForm()

    return render(request, 'analytics/upload.html', {'profile': profile, 'form': form})


@analytics_access_required
def jobs_list(request):
    profile = request.analytics_profile
    jobs = StatistikJob.objects.filter(organization=profile.organization).order_by('-uploaded_at')
    paginator = Paginator(jobs, 15)
    page_obj = paginator.get_page(request.GET.get('page'))
    return render(
        request,
        'analytics/jobs_list.html',
        {
            'profile': profile,
            'jobs': page_obj,
            'page_obj': page_obj,
        },
    )


@analytics_access_required
def job_detail(request, job_id):
    profile = request.analytics_profile
    job = get_object_or_404(StatistikJob, id=job_id, organization=profile.organization)
    vehicles = job.vehicle_records.all().order_by('registration')
    paginator = Paginator(vehicles, 50)
    page_obj = paginator.get_page(request.GET.get('page'))

    return render(
        request,
        'analytics/job_detail.html',
        {
            'profile': profile,
            'job': job,
            'vehicles': page_obj,
            'page_obj': page_obj,
            'kpis': job.kpis or {},
            'stations': job.station_stats or [],
        },
    )


@analytics_access_required
def export_excel(request, job_id):
    profile = request.analytics_profile
    job = get_object_or_404(StatistikJob, id=job_id, organization=profile.organization)

    try:
        content = _build_statistik_export_excel(job)
    except ImportError:
        messages.error(request, 'Excel export dependencies are missing in the runtime environment.')
        return redirect('analytics:job_detail', job_id=job.id)
    except Exception as exc:
        logger.exception('Failed generating export for analytics job %s: %s', job.id, exc)
        messages.error(request, f'Failed to generate export: {exc}')
        return redirect('analytics:job_detail', job_id=job.id)

    response = HttpResponse(
        content,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    )
    response['Content-Disposition'] = 'attachment; filename="statistik_export.xlsx"'
    return response


class AnalyticsViewSet(viewsets.ModelViewSet):
    """Analytics and Statistik endpoints"""
    serializer_class = StatistikJobSerializer
    permission_classes = [IsAuthenticated]

    def _ensure_access(self):
        profile = _get_user_profile(self.request.user)
        if not profile or not profile.organization:
            raise PermissionDenied('User profile or organization is missing.')

        service = _get_analytics_service()
        if not service:
            raise PermissionDenied('Analytics service is not configured.')

        license_obj = _get_valid_org_license(profile.organization, service)
        if not license_obj:
            raise PermissionDenied('A valid analytics license is required.')

        return profile
    
    def get_queryset(self):
        """Filter by organization"""
        profile = self._ensure_access()
        return StatistikJob.objects.filter(organization=profile.organization)
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        context['request'] = self.request
        return context
    
    @action(detail=False, methods=['post'])
    def upload_and_process(self, request):
        """Upload files and process statistik"""
        profile = self._ensure_access()
        org = profile.organization
        job = None
        
        # Get uploaded files
        inventory = request.FILES.get('inventory')
        wayke = request.FILES.get('wayke')
        citk = request.FILES.get('citk')
        notes = request.FILES.get('notes')
        
        if not all([inventory, wayke, citk]):
            return Response(
                {'error': 'inventory, wayke, and citk files are required'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            # Lazy import to avoid requiring pandas at startup
            from .services.statistik_processor import StatistikProcessor
            
            # Create job record
            job = StatistikJob.objects.create(
                organization=org,
                created_by=profile,
                inventory_file=inventory,
                wayke_file=wayke,
                citk_file=citk,
                notes_file=notes,
                status='processing'
            )
            
            # Process files
            processor = StatistikProcessor(
                inventory_path=job.inventory_file.path,
                wayke_path=job.wayke_file.path,
                citk_path=job.citk_file.path,
                notes_path=job.notes_file.path if notes else None,
            )
            
            result = processor.process()
            
            # Store results
            job.kpis = result['kpis']
            job.station_stats = result['by_station']
            job.status = 'completed'
            job.processed_at = timezone.now()
            job.save()
            
            _save_vehicle_records(job, result.get('inventory_24', []))
            
            serializer = self.get_serializer(job)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
            
        except Exception as e:
            logger.error(f"Error processing statistik: {e}")
            if job is not None:
                job.status = 'failed'
                job.error_message = str(e)
                job.save()
            
            return Response(
                {'error': str(e)},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
    
    @action(detail=True, methods=['get'])
    def export_excel(self, request, pk=None):
        """Export job data to Excel"""
        self._ensure_access()
        job = self.get_object()
        # TODO: Implement Excel export
        return Response({'message': 'Excel export coming soon'})