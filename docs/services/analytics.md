# Analytics Service

Purpose: Vehicle inventory analytics with file upload processing, KPI generation, and job history.

Access control:
- Requires authenticated user
- Requires user profile with organization membership
- Requires active or trial license for service slug `analytics`

Core capabilities:
- Upload Inventory, Wayke, CITK, and optional notes files
- Process and store KPI summary per job
- Persist vehicle-level records for drill-down
- View recent jobs, full history, and job details in service UI

Key URLs:
- `/services/analytics/` - dashboard
- `/services/analytics/upload/` - upload and process files
- `/services/analytics/jobs/` - job history
- `/services/analytics/jobs/<job_id>/` - job details
- `/services/analytics/api/jobs/` - API endpoints

Operational notes:
- Analytics processing uses `StatistikProcessor` and requires `pandas` in runtime.
- The service is seeded by `python manage.py setup_licensing` which creates:
  - Service: `analytics`
  - License types: `personal_free`, `basic`, `professional`, `enterprise`
