from django.urls import path

from pettycash import views

app_name = 'pettycash'

urlpatterns = [
    path('petty-cash/', views.overview, name='overview'),
    path('petty-cash/requests/', views.request_list, name='request_list'),
    path('petty-cash/requests/new/', views.request_create, name='request_create'),
    path('petty-cash/requests/<int:pk>/', views.request_detail, name='request_detail'),
    path('petty-cash/requests/<int:pk>/cancel/', views.request_cancel, name='request_cancel'),
    path('petty-cash/requests/<int:pk>/review/', views.request_review, name='request_review'),
    path('petty-cash/cash-book/', views.ledger, name='ledger'),
    path('petty-cash/spend/', views.expense_create, name='expense_create'),
    path('petty-cash/entries/<int:pk>/cancel/', views.expense_cancel, name='expense_cancel'),
    path('petty-cash/settings/', views.settings_view, name='settings'),
]
