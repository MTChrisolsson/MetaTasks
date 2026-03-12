import logging
from io import BytesIO
from decimal import Decimal, InvalidOperation

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
from rest_framework.views import APIView

from core.models import UserProfile
from core.views import require_organization_access
from licensing.models import License, Service

from .forms import StatistikUploadForm
from .models import StatistikJob, VehicleRecord, VehicleValuation
from .serializers import (
    StatistikJobSerializer,
    VehicleValuationBatchResponseSerializer,
    VehicleValuationRequestSerializer,
    VehicleValuationSerializer,
)
from .services.groq_valuation_service import GroqValuationError, GroqVehicleValuationService

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


def _ensure_analytics_access_for_user(user):
    profile = _get_user_profile(user)
    if not profile or not profile.organization:
        raise PermissionDenied('User profile or organization is missing.')

    service = _get_analytics_service()
    if not service:
        raise PermissionDenied('Analytics service is not configured.')

    license_obj = _get_valid_org_license(profile.organization, service)
    if not license_obj:
        raise PermissionDenied('A valid analytics license is required.')

    return profile


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


def _to_decimal(value):
    try:
        if value is None or value == '':
            return None
        return Decimal(str(value)).quantize(Decimal('0.01'))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _build_vehicle_payload(vehicle, overrides=None):
    overrides = overrides or {}

    payload = {
        'make': (overrides.get('make') or vehicle.make or '').strip(),
        'model': (overrides.get('model') or vehicle.model or '').strip(),
        'year': overrides.get('year') if overrides.get('year') is not None else vehicle.year,
        'mileage': overrides.get('mileage') if overrides.get('mileage') is not None else vehicle.mileage,
        'condition': (overrides.get('condition') or vehicle.condition or '').strip(),
        'transmission': (overrides.get('transmission') or vehicle.transmission or '').strip(),
        'fuel_type': (overrides.get('fuel_type') or vehicle.fuel_type or '').strip(),
        'published_price': _to_decimal(overrides.get('published_price')) or vehicle.published_price,
    }

    missing = [
        key
        for key in ['make', 'model', 'year', 'published_price']
        if payload.get(key) in (None, '')
    ]
    return payload, missing


def _create_vehicle_valuation(job, vehicle, vehicle_payload, valuation_result):
    return VehicleValuation.objects.create(
        job=job,
        vehicle=vehicle,
        registration=vehicle.registration,
        make=vehicle_payload['make'],
        model=vehicle_payload['model'],
        year=vehicle_payload['year'],
        mileage=vehicle_payload.get('mileage'),
        condition=vehicle_payload.get('condition', ''),
        transmission=vehicle_payload.get('transmission', ''),
        fuel_type=vehicle_payload.get('fuel_type', ''),
        published_price=vehicle_payload['published_price'],
        estimated_market_value=valuation_result['estimated_market_value'],
        fairness_assessment=valuation_result['fairness_assessment'],
        suggested_price=valuation_result['suggested_price'],
        ai_explanation=valuation_result['ai_explanation'],
        raw_response=valuation_result.get('raw_response'),
        model_name=valuation_result.get('model_name', 'llama-3.1-8b-instant'),
    )


def _save_vehicle_records(job, rows):
    """Persist processed rows to VehicleRecord with tolerant parsing."""
    vehicle_records = []
    for row in rows:
        vehicle_records.append(
            VehicleRecord(
                job=job,
                registration=str(row.get('Reg', '') or ''),
                make=str(row.get('Tillverkare', row.get('Make', '')) or ''),
                model=str(row.get('Model', '') or ''),
                year=_to_int(row.get('Modellar', row.get('Modellår', row.get('Year', None))), None),
                mileage=_to_int(row.get('Mileage', row.get('Miltal', None)), None),
                condition=str(row.get('Condition', '') or ''),
                transmission=str(row.get('Transmission', '') or ''),
                fuel_type=str(row.get('FuelType', row.get('Fuel', '')) or ''),
                published_price=_to_int(row.get('Pris', row.get('Price', None)), None),
                status=_to_int(row.get('Status', 0), 0),
                current_station=str(row.get('CurrentStation', '') or ''),
                days_in_stock=_to_int(row.get('DaysInStock', None), None),
                is_published=_to_bool(row.get('Published', False)),
                is_photographed=_to_bool(row.get('Photographed', False)),
                photo_count=_to_int(row.get('PhotoURL_Count', row.get('PhotoCount', 0)), 0),
                needs_photos=_to_bool(row.get('NeedsPhotos', False)),
                missing_citk=_to_bool(row.get('CITKMatched', False)) is False,
                is_sold=str(row.get('Status', '')).lower() == 'sold',
                notes=str(row.get('Note', row.get('note', '')) or ''),
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


DETAIL_EXPORT_HEADERS = [
    'Reg',
    'Status',
    'Model',
    'InboundSeller',
    'DaysInStock',
    'Published',
    'Photographed',
    'PhotoURL_Count',
    'WaykeURL',
    'CurrentStation',
    'Note',
    'WaykeMatched',
    'CITKMatched',
    'Uppdaterad',
    'Skapad',
    'Tillverkare',
    'Modellar',
    'Pris',
]


def _to_detail_export_dataframe(records):
    rows = []
    for record in records:
        if isinstance(record, dict):
            rows.append(
                {
                    'Reg': record.get('Reg', ''),
                    'Status': record.get('Status', ''),
                    'Model': record.get('Model', record.get('Modell', '')),
                    'InboundSeller': record.get('InboundSeller', record.get('Inb. säljare', '')),
                    'DaysInStock': record.get('DaysInStock', record.get('Lagerdagar', '')),
                    'Published': record.get('Published', False),
                    'Photographed': record.get('Photographed', False),
                    'PhotoURL_Count': record.get('PhotoURL_Count', record.get('PhotoCount', 0)),
                    'WaykeURL': record.get('WaykeURL', record.get('Wayke: URL', '')),
                    'CurrentStation': record.get('CurrentStation', ''),
                    'Note': record.get('Note', record.get('note', '')),
                    'WaykeMatched': record.get('WaykeMatched', record.get('Published', False)),
                    'CITKMatched': record.get('CITKMatched', False),
                    'Uppdaterad': record.get('Uppdaterad', ''),
                    'Skapad': record.get('Skapad', ''),
                    'Tillverkare': record.get('Tillverkare', ''),
                    'Modellar': record.get('Modellar', record.get('Modellår', '')),
                    'Pris': record.get('Pris', ''),
                }
            )
            continue

        rows.append(
            {
                'Reg': record.registration,
                'Status': record.status,
                'Model': record.model,
                'InboundSeller': '',
                'DaysInStock': record.days_in_stock,
                'Published': record.is_published,
                'Photographed': record.is_photographed,
                'PhotoURL_Count': record.photo_count,
                'WaykeURL': '',
                'CurrentStation': record.current_station,
                'Note': record.notes,
                'WaykeMatched': record.is_published,
                'CITKMatched': not record.missing_citk,
                'Uppdaterad': '',
                'Skapad': '',
                'Tillverkare': '',
                'Modellar': '',
                'Pris': '',
            }
        )

    return pd.DataFrame(rows, columns=DETAIL_EXPORT_HEADERS)


def _to_sold_export_dataframe(records):
    rows = []
    for record in records:
        if isinstance(record, dict):
            rows.append(
                {
                    'Reg': record.get('Reg', ''),
                    'Status': record.get('Status', ''),
                    'Model': record.get('Model', record.get('Modell', '')),
                    'InboundSeller': record.get('InboundSeller', record.get('Inb. säljare', '')),
                    'DaysInStock': record.get('DaysInStock', record.get('Lagerdagar', '')),
                }
            )
            continue

        rows.append(
            {
                'Reg': record.registration,
                'Status': record.status,
                'Model': record.model,
                'InboundSeller': '',
                'DaysInStock': record.days_in_stock,
            }
        )

    return pd.DataFrame(rows, columns=['Reg', 'Status', 'Model', 'InboundSeller', 'DaysInStock'])


def _to_station_dataframe(station_data):
    rows = []
    for station in station_data:
        if hasattr(station, 'to_dict'):
            station = station.to_dict()
        elif not isinstance(station, dict):
            station = vars(station)

        rows.append(
            {
                'Station': station.get('Station')
                or station.get('station')
                or station.get('CurrentStation')
                or station.get('current_station')
                or '',
                'Count': station.get('Count') or station.get('count') or 0,
                'Percentage': station.get('Percentage') or station.get('pct') or 0,
            }
        )

    return pd.DataFrame(rows, columns=['Station', 'Count', 'Percentage'])


def _build_statistik_export_excel(job):
    result_kpis = job.kpis or {}
    station_data = job.station_stats or []

    records = VehicleRecord.objects.filter(job=job)
    inventory_24_records = records.filter(status=24)
    needs_photos_records = records.filter(is_published=True, photo_count__lt=job.photo_min_urls)
    not_published_records = records.filter(is_published=False)
    missing_citk_records = records.filter(missing_citk=True)
    sold_records = records.filter(status__in=[34, 35, 36])

    inventory_24_rows = list(inventory_24_records)
    not_published_rows = list(not_published_records)
    sold_rows = list(sold_records)

    # Fallback: regenerate detail rows from uploaded files when persisted rows are missing.
    if not inventory_24_rows and not not_published_rows and not sold_rows:
        try:
            from .services.statistik_processor import StatistikProcessor

            processor = StatistikProcessor(
                inventory_path=job.inventory_file.path,
                wayke_path=job.wayke_file.path,
                citk_path=job.citk_file.path,
                notes_path=job.notes_file.path if job.notes_file else None,
                inventory_sheet=job.inventory_sheet,
                citk_sheet=job.citk_sheet,
                photo_min_urls=job.photo_min_urls,
            )
            processor_result = processor.process()

            inventory_24_rows = processor_result.get('inventory_24', []) or []
            not_published_rows = processor_result.get('not_published', []) or []
            sold_rows = processor_result.get('sold', []) or []

            if not result_kpis:
                result_kpis = processor_result.get('kpis', {}) or {}
            if not station_data:
                station_data = processor_result.get('by_station', []) or []
        except Exception as exc:
            logger.warning('Export fallback processing failed for job %s: %s', job.id, exc)

    summary_df = pd.DataFrame(
        [
            {
                'Inventory (Status 24)': result_kpis.get('inventory_24', 0),
                'Published on Wayke': result_kpis.get('published', 0),
                'Published %': result_kpis.get('published_pct', 0),
                'Need Photos': result_kpis.get('needs_photos', 0),
                'Missing in CITK': result_kpis.get('missing_citk', 0),
            }
        ]
    )

    station_df = _to_station_dataframe(station_data)
    inventory_df = _to_detail_export_dataframe(inventory_24_rows)
    not_published_df = _to_detail_export_dataframe(not_published_rows)

    # Explicit empty sheets required by spec.
    needs_photos_df = pd.DataFrame()
    missing_citk_df = pd.DataFrame()
    notes_df = pd.DataFrame()

    sold_df = _to_sold_export_dataframe(sold_rows)

    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: Summary (summary table + by-station table)
        summary_df.to_excel(writer, index=False, sheet_name='Summary', startrow=0)
        start_row = len(summary_df) + 3
        station_df.to_excel(writer, index=False, sheet_name='Summary', startrow=start_row)

        # Sheets 2-8 as required
        inventory_df.to_excel(writer, index=False, sheet_name='Inventory_24_detail')
        needs_photos_df.to_excel(writer, index=False, sheet_name='Needs_Photos')
        not_published_df.to_excel(writer, index=False, sheet_name='Not_Published')
        station_df.to_excel(writer, index=False, sheet_name='By_Station')
        missing_citk_df.to_excel(writer, index=False, sheet_name='Missing_in_CITK')
        sold_df.to_excel(writer, index=False, sheet_name='Sold_34_35_36')
        notes_df.to_excel(writer, index=False, sheet_name='Notes')

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

    # Blocket integration stats (silently skipped if not configured or unavailable)
    blocket_stats = None
    try:
        from services.staff_panel.models import Integration as StaffIntegration
        blocket_integration = StaffIntegration.objects.filter(
            organization=profile.organization,
            integration_type='blocket',
            is_enabled=True,
        ).first()
        if blocket_integration:
            org_id = blocket_integration.config.get('org_id')
            if org_id:
                from .services.blocket_service import fetch_blocket_shop_stats
                blocket_stats = fetch_blocket_shop_stats(int(org_id))
    except Exception:
        pass

    return render(
        request,
        'analytics/dashboard.html',
        {
            'profile': profile,
            'recent_jobs': recent_jobs,
            'latest_job': latest_completed,
            'stats': stats,
            'blocket_stats': blocket_stats,
        },
    )


@analytics_access_required
def blocket_listings(request):
    """Display all Blocket listings with filtering options"""
    profile = request.analytics_profile
    
    # Get Blocket integration
    blocket_integration = None
    listings_data = None
    org_id = None
    
    try:
        from services.staff_panel.models import Integration as StaffIntegration
        blocket_integration = StaffIntegration.objects.filter(
            organization=profile.organization,
            integration_type='blocket',
            is_enabled=True,
        ).first()
        
        if blocket_integration:
            org_id = blocket_integration.config.get('org_id')
            if org_id:
                # Get filter parameters
                make_filter = request.GET.get('make', '').strip()
                min_price = request.GET.get('min_price', '').strip()
                max_price = request.GET.get('max_price', '').strip()
                
                # Convert price strings to ints
                min_price_int = int(min_price) if min_price and min_price.isdigit() else None
                max_price_int = int(max_price) if max_price and max_price.isdigit() else None
                
                from .services.blocket_service import fetch_blocket_listings
                listings_data = fetch_blocket_listings(
                    int(org_id),
                    make_filter=make_filter if make_filter else None,
                    min_price=min_price_int,
                    max_price=max_price_int,
                )
                
                # Pagination
                paginator = Paginator(listings_data['listings'], 20)
                page_number = request.GET.get('page', 1)
                try:
                    page = paginator.get_page(page_number)
                except:
                    page = paginator.get_page(1)
                
                listings_data['page'] = page
                listings_data['filters'] = {
                    'make': make_filter,
                    'min_price': min_price if min_price else '',
                    'max_price': max_price if max_price else '',
                }

                # Match current page Blocket listings to persisted VehicleRecord rows.
                for listing in listings_data['page'].object_list:
                    listing['matched_vehicle_id'] = None
                    regno = str(listing.get('registration_number') or '').strip()
                    if not regno:
                        continue

                    matched_vehicle = (
                        VehicleRecord.objects.filter(
                            job__organization=profile.organization,
                            registration__iexact=regno,
                        )
                        .select_related('job')
                        .order_by('-job__uploaded_at', '-id')
                        .first()
                    )
                    if matched_vehicle:
                        listing['matched_vehicle_id'] = matched_vehicle.id
    except Exception:
        pass
    
    if not listings_data:
        listings_data = {
            'listings': [],
            'total_count': 0,
            'filtered_count': 0,
            'makes': [],
            'error': 'Blocket integration not configured' if not blocket_integration else 'Could not fetch listings',
            'page': None,
            'filters': {},
        }
    
    return render(
        request,
        'analytics/blocket_listings.html',
        {
            'profile': profile,
            'listings_data': listings_data,
            'org_id': org_id,
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


class VehicleValuationAPIView(APIView):
    """Valuate one vehicle or all vehicles in a job using Groq AI."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        try:
            return self._handle_post(request)
        except Exception as exc:
            logger.exception('Unexpected error in VehicleValuationAPIView.post: %s', exc)
            return Response(
                {'error': f'Internal server error: {str(exc)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    def _handle_post(self, request):
        profile = _ensure_analytics_access_for_user(request.user)

        request_serializer = VehicleValuationRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        data = request_serializer.validated_data

        try:
            valuation_service = GroqVehicleValuationService()
        except GroqValuationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        if data.get('job_id') and not data.get('vehicle_id'):
            return self._handle_batch(profile, data, valuation_service)
        return self._handle_single(profile, data, valuation_service)

    def _handle_single(self, profile, data, valuation_service):
        vehicle_id = data.get('vehicle_id')
        if not vehicle_id:
            return Response(
                {'error': 'vehicle_id is required for single valuation requests.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            vehicle = VehicleRecord.objects.select_related('job').get(
                id=vehicle_id,
                job__organization=profile.organization,
            )
        except VehicleRecord.DoesNotExist:
            return Response({'error': 'Vehicle record not found.'}, status=status.HTTP_404_NOT_FOUND)

        payload, missing = _build_vehicle_payload(vehicle, overrides=data)
        if missing:
            return Response(
                {
                    'error': 'Vehicle data is incomplete for valuation.',
                    'missing_fields': missing,
                    'vehicle_id': vehicle.id,
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            valuation_result = valuation_service.evaluate_vehicle(payload)
            valuation = _create_vehicle_valuation(vehicle.job, vehicle, payload, valuation_result)
        except GroqValuationError as exc:
            return Response({'error': str(exc)}, status=status.HTTP_502_BAD_GATEWAY)

        return Response(VehicleValuationSerializer(valuation).data, status=status.HTTP_201_CREATED)

    def _handle_batch(self, profile, data, valuation_service):
        job_id = data.get('job_id')
        try:
            job = StatistikJob.objects.get(id=job_id, organization=profile.organization)
        except StatistikJob.DoesNotExist:
            return Response({'error': 'Job not found.'}, status=status.HTTP_404_NOT_FOUND)

        vehicles = list(job.vehicle_records.all().order_by('id'))
        if not vehicles:
            return Response(
                {'error': 'No vehicles available in this job.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        created = []
        skipped = 0

        for vehicle in vehicles:
            payload, missing = _build_vehicle_payload(vehicle)
            if missing:
                skipped += 1
                continue

            try:
                valuation_result = valuation_service.evaluate_vehicle(payload)
                valuation = _create_vehicle_valuation(job, vehicle, payload, valuation_result)
                created.append(valuation)
            except GroqValuationError:
                skipped += 1

        response_data = {
            'job_id': job.id,
            'total_vehicles': len(vehicles),
            'valued_vehicles': len(created),
            'skipped_vehicles': skipped,
            'valuations': VehicleValuationSerializer(created, many=True).data,
        }
        return Response(VehicleValuationBatchResponseSerializer(response_data).data, status=status.HTTP_200_OK)


class AnalyticsViewSet(viewsets.ModelViewSet):
    """Analytics and Statistik endpoints"""
    serializer_class = StatistikJobSerializer
    permission_classes = [IsAuthenticated]

    def _ensure_access(self):
        return _ensure_analytics_access_for_user(self.request.user)
    
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