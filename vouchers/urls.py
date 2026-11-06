from django.urls import path

from vouchers import views

app_name = 'vouchers'
urlpatterns = [
    path('vouchers/', views.voucher_list, name='voucher_list'),
    path('vouchers/new/', views.voucher_create, name='voucher_create'),
    path('vouchers/<int:pk>/', views.voucher_detail, name='voucher_detail'),
    path('vouchers/<int:pk>/delete/', views.voucher_delete, name='voucher_delete'),
    path('vouchers/<int:pk>/edit/', views.voucher_update, name='voucher_update'),
    path('vouchers/<int:pk>/action/<str:action>/', views.voucher_action, name='voucher_action'),
    path('vouchers/<int:pk>/print/', views.voucher_print, name='voucher_print'),
    path('approvals/', views.approval_queue, name='approval_queue'),
    path('recommendations/', views.recommendation_queue, name='recommendation_queue'),
    path('schedules/', views.schedule_list, name='schedule_list'),
    path('schedules/new/', views.schedule_create, name='schedule_create'),
    path('schedules/<int:pk>/edit/', views.schedule_update, name='schedule_update'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/new/', views.category_create, name='category_create'),
    path('categories/<int:pk>/edit/', views.category_update, name='category_update'),
]
