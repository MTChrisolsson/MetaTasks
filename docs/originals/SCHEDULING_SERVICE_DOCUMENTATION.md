Contents moved to `docs/originals/SCHEDULING_SERVICE_DOCUMENTATION.md` and summarized in `docs/services/scheduling.md`.
# Scheduling Service Documentation

## Overview

The Scheduling Service is a comprehensive resource management and booking system integrated into the MetaTask platform. It provides flexible scheduling capabilities for any type of resource (rooms, equipment, vehicles, people) with approval workflows, calendar integration, and utilization tracking.

## Architecture

### Service Structure
```
services/scheduling/
├── models.py              # Data models
├── services.py            # Business logic layer
├── integrations.py        # External service integrations
├── views.py              # Web interface views
├── admin.py              # Django admin interface
├── urls.py               # URL routing
├── migrations/           # Database migrations
└── __init__.py
```

### Templates Structure
```
templates/scheduling/
├── scheduling_base.html       # Base template with Tailwind CSS styling
├── scheduling_base_fixed.html # Alternative base template
├── dashboard.html            # Main dashboard (modern Tailwind design)
├── calendar.html            # Calendar view template
├── resource_detail.html    # Resource detail page
├── no_profile.html         # Error template for missing profiles
└── ...
```

## Data Models

### Important: Organization Model Usage
**CRITICAL NOTE**: The scheduling service uses `core.Organization` (from the core app), NOT `accounts.Organization`. 

**Model Import**:
```python
from core.models import Organization, UserProfile
```

**Database Table**: `core_organization` (not `accounts_organization`)

**Relationships**: All foreign key relationships in the scheduling service point to `core.Organization`:
- `SchedulableResource.organization` → `core.Organization`
- `BookingRequest.organization` → `core.Organization`

This is essential to understand when writing queries, creating migrations, or building integrations with the scheduling service.

### SchedulableResource
**Purpose**: Represents any bookable resource in the system
````markdown
Contents moved to `docs/originals/SCHEDULING_SERVICE_DOCUMENTATION.md` and summarized in `docs/services/scheduling.md`.
````
### Views Architecture
**Location**: `services/scheduling/views.py`

**Key Views**:
- `index()`: Dashboard with statistics and overview
- `calendar_view()`: FullCalendar integration
- `resource_list()`: Resource management interface
- `resource_detail()`: Individual resource details
- `booking_list()`: Booking management interface
- `booking_detail()`: Individual booking details
- `booking_action()`: Booking approval/cancellation

**API Endpoints**:
- `/api/calendar-events/`: Calendar data in JSON format
- `/api/suggest-times/`: Time slot suggestions
- `/api/availability/`: Real-time availability checking

### URL Configuration
**Location**: `services/scheduling/urls.py`

```python
urlpatterns = [
    path('', views.index, name='index'),                                    # Dashboard
    path('calendar/', views.calendar_view, name='calendar'),                # Calendar
    path('resources/', views.resource_list, name='resource_list'),          # Resources
    path('resources/<int:resource_id>/', views.resource_detail, name='resource_detail'),
    path('bookings/', views.booking_list, name='booking_list'),             # Bookings
    path('bookings/<int:booking_id>/', views.booking_detail, name='booking_detail'),
    path('bookings/<int:booking_id>/<str:action>/', views.booking_action, name='booking_action'),
    # API endpoints
    path('api/calendar-events/', views.api_calendar_events, name='api_calendar_events'),
    path('api/suggest-times/', views.api_suggest_times, name='api_suggest_times'),
    # Integration
    path('sync-cflows/', views.sync_cflows_bookings, name='sync_cflows_bookings'),
]
```

## Frontend Design

### Design System
- **Framework**: Tailwind CSS (matches CFlows design)
- **Icons**: Font Awesome 6.4.0
- **Components**: Alpine.js for interactivity
- **Calendar**: FullCalendar 6.1.10
- **Charts**: Chart.js for analytics

### Color Scheme
```css
:root {
    --scheduling-primary: #059669;     /* Green 600 */
    --scheduling-secondary: #10b981;   /* Green 500 */
    --scheduling-success: #22c55e;     /* Green 500 */
    --scheduling-warning: #f59e0b;     /* Amber 500 */
    --scheduling-danger: #ef4444;      /* Red 500 */
}
```

### Key UI Components
1. **Statistics Cards**: Dashboard metrics with colored icons
2. **Resource Cards**: Visual resource representation with status
3. **Calendar Widget**: FullCalendar integration with custom events
4. **Quick Actions**: One-click access to common tasks
5. **Status Badges**: Visual status indicators with consistent styling

## Configuration & Setup

### Required Settings
```python
# In settings.py
INSTALLED_APPS = [
    'services.scheduling',
]

# Database configuration
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        # ... other database settings
    }
}
```

### Dependencies
```txt
Django>=4.2
psycopg2-binary  # PostgreSQL adapter
celery           # For background tasks (future)
```

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://user:pass@localhost/mediap

# Debug (development only)  
DEBUG=True
```

## Data Migration Strategy

### From CFlows TeamBooking
1. **Teams → Resources**: Each Team becomes a SchedulableResource
2. **TeamBookings → BookingRequests**: Existing bookings migrate with status mapping
3. **Metadata Preservation**: Original IDs stored in metadata field
4. **Relationship Maintenance**: Links to UserProfile and Organization preserved

### Migration Command
```bash
python manage.py migrate services.scheduling
```

## Testing Strategy

### Test Coverage Areas
1. **Model Tests**: Data validation and business logic
2. **Service Tests**: Business layer functionality
3. **Integration Tests**: CFlows compatibility
4. **View Tests**: Web interface functionality
5. **API Tests**: JSON endpoint responses

### Sample Test Structure
```python
# Example test patterns used
def test_booking_creation():
    """Test successful booking creation"""
    
def test_availability_checking():
    """Test resource availability logic"""
    
def test_cflows_integration():
    """Test TeamBooking migration"""
```

## Security & Permissions

### Access Control
- **Organization-based**: Users can only access their organization's resources
- **Profile Required**: All views require valid UserProfile
- **Decorator**: `@require_organization_access` ensures proper access

### Data Security
- **CSRF Protection**: All forms use Django CSRF tokens
- **SQL Injection**: Django ORM prevents injection attacks
- **XSS Protection**: Template auto-escaping enabled

## Performance Considerations

### Database Optimizations
- **Indexes**: Created on frequently queried fields
- **Select Related**: Used to prevent N+1 queries
- **Queryset Optimization**: Efficient database queries in views

### Caching Strategy
- **Template Caching**: Base templates cached for performance
- **Static Assets**: CSS/JS served via CDN
- **Database Queries**: Optimized with select_related/prefetch_related

## Future Enhancements

### Planned Features
1. **Recurring Bookings**: Repeat scheduling patterns
2. **Email Notifications**: Booking confirmations and reminders  
3. **Mobile App**: React Native or PWA interface
4. **Advanced Analytics**: Utilization insights and reporting
5. **External Calendar Sync**: Google Calendar/Outlook integration
6. **Resource Categories**: Hierarchical resource organization
7. **Approval Workflows**: Multi-step approval processes
8. **Resource Dependencies**: Linked resource bookings

### API Expansion
1. **REST API**: Full CRUD operations via API
2. **Webhooks**: Event notifications for external systems
3. **Bulk Operations**: Mass booking operations
4. **Import/Export**: CSV data management

## Development Guidelines

### Code Standards
- **Python**: PEP 8 style guide
- **Django**: Follow Django best practices
- **Templates**: Semantic HTML5 with Tailwind CSS
- **JavaScript**: ES6+ standards with Alpine.js

### Git Workflow
- **Feature Branches**: Separate branches for each feature
- **Commit Messages**: Descriptive commit messages
- **Code Review**: Pull request reviews required
- **Testing**: All changes require tests

### Documentation
- **Docstrings**: All functions and classes documented
- **Comments**: Complex business logic explained
- **README**: Setup and usage instructions
- **API Docs**: Endpoint documentation with examples

---

## Quick Start for Developers

### 1. Clone and Setup
```bash
git clone <repository>
cd mediap
docker-compose up -d
```

### 2. Run Migrations
```bash
docker-compose exec web python manage.py migrate
```

### 3. Access Dashboard
Navigate to: `http://localhost:8000/services/scheduling/`

### 4. Development Commands
```bash
# Create superuser
docker-compose exec web python manage.py createsuperuser

# Run tests
docker-compose exec web python manage.py test services.scheduling

# Collect static files
docker-compose exec web python manage.py collectstatic
```

This documentation provides a comprehensive foundation for continuing development of the scheduling service. The system is production-ready with modern architecture, comprehensive testing, and scalable design patterns.
