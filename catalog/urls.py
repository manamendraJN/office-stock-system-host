from django.urls import path

from catalog import views

app_name = 'catalog'
urlpatterns = [
    path('items/', views.item_list, name='item_list'),
    path('items/new/', views.item_create, name='item_create'),
    path('items/<int:pk>/', views.item_edit, name='item_edit'),
    path('items/<int:pk>/delete/', views.item_delete, name='item_delete'),
    path('categories/', views.category_list, name='category_list'),
    path('categories/<int:pk>/rename/', views.category_rename, name='category_rename'),
    path('categories/<int:pk>/delete/', views.category_delete, name='category_delete'),
    path('suppliers/', views.supplier_list, name='supplier_list'),
    path('suppliers/new/', views.supplier_create, name='supplier_create'),
    path('suppliers/<int:pk>/', views.supplier_edit, name='supplier_edit'),
    path('suppliers/<int:pk>/delete/', views.supplier_delete, name='supplier_delete'),
]
