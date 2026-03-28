from django.urls import include, path
from rest_framework.routers import DefaultRouter

from . import views

app_name = 'inventory'

router = DefaultRouter()
router.register('api/items', views.InventoryItemViewSet, basename='api-items')
router.register('api/locations', views.InventoryLocationViewSet, basename='api-locations')
router.register('api/stocks', views.ItemStockViewSet, basename='api-stocks')
router.register('api/movements', views.StockMovementViewSet, basename='api-movements')

urlpatterns = [
    path('', views.index, name='index'),

    # Item management
    path('items/', views.items_list, name='items-list'),
    path('items/create/', views.item_create, name='item-create'),
    path('items/<int:item_id>/', views.item_detail, name='item-detail'),
    path('items/<int:item_id>/edit/', views.item_edit, name='item-edit'),

    # Location management
    path('locations/', views.locations_list, name='locations-list'),
    path('locations/create/', views.location_create, name='location-create'),
    path('locations/<int:location_id>/', views.location_detail, name='location-detail'),
    path('locations/<int:location_id>/edit/', views.location_edit, name='location-edit'),
    path('locations/<int:location_id>/view-settings/', views.location_view_settings, name='location-view-settings'),

    # Movements and alerts
    path('movements/', views.movements_list, name='movements-list'),
    path('movements/create/', views.movement_create, name='movement-create'),
    path('alerts/low-stock/', views.low_stock_alerts, name='low-stock-alerts'),

    # Configuration
    path('configuration/', views.configuration, name='configuration'),
    path('configuration/reasons/create/', views.movement_reason_create, name='movement-reason-create'),
    path('configuration/reasons/<int:reason_id>/edit/', views.movement_reason_edit, name='movement-reason-edit'),
    path('configuration/fields/create/', views.field_definition_create, name='field-definition-create'),
    path('configuration/fields/<int:field_id>/edit/', views.field_definition_edit, name='field-definition-edit'),

    # Exports
    path('exports/stocks.csv', views.export_stock_csv, name='export-stock-csv'),
    path('exports/movements.csv', views.export_movements_csv, name='export-movements-csv'),

    # API
    path('', include(router.urls)),
]
