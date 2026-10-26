from django.urls import path

from inventory import views

app_name = 'inventory'

urlpatterns = [
    path('purchases/', views.purchase_list, name='purchase_list'),
    path('purchases/new/', views.purchase_create, name='purchase_create'),
    path('purchases/<int:pk>/', views.purchase_detail, name='purchase_detail'),
    path('purchases/<int:pk>/edit/', views.purchase_edit, name='purchase_edit'),
    path('purchases/<int:pk>/cancel/', views.purchase_cancel, name='purchase_cancel'),
    path('purchases/<int:pk>/receive/', views.purchase_receive, name='purchase_receive'),
    path('office-issues/', views.issue_list, name='issue_list'),
    path('office-issues/new/', views.issue_create, name='issue_create'),
    path('office-issues/<int:pk>/', views.issue_detail, name='issue_detail'),
    path('office-issues/<int:pk>/cancel/', views.issue_cancel, name='issue_cancel'),
    path('stock/', views.stock_page, name='stock'),
    path('stock/correct/', views.stock_correct, name='stock_correct'),
]
