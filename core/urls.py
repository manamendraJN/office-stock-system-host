from django.urls import path

from core import views

app_name = 'core'
urlpatterns = [
    path('', views.dashboard, name='dashboard'),
    path('settings/', views.settings_view, name='settings'),
    path('audit/', views.audit_log, name='audit'),
    path('audit/clear/', views.audit_clear, name='audit_clear'),
    path('health/', views.health, name='health'),
    path('maintenance/stock-ledger-retention/', views.stock_ledger_retention, name='stock_retention'),
]
