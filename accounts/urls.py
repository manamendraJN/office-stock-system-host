from django.urls import path

from accounts import views

app_name = 'accounts'
urlpatterns = [
    path('login/', views.login_view, name='login'),
    path('logout/', views.logout_view, name='logout'),
    path('password/', views.change_password_view, name='change_password'),
    path('users/', views.user_list, name='user_list'),
    path('users/new/', views.user_create, name='user_create'),
    path('users/<int:pk>/', views.user_edit, name='user_edit'),
    path('users/<int:pk>/reset-password/', views.user_reset_password, name='user_reset_password'),
    path('users/<int:pk>/toggle/', views.user_toggle_active, name='user_toggle'),
    path('roles/', views.role_list, name='role_list'),
    path('roles/new/', views.role_create, name='role_create'),
    path('roles/<int:pk>/', views.role_edit, name='role_edit'),
    path('roles/<int:pk>/delete/', views.role_delete, name='role_delete'),
    path('branches/', views.branch_list, name='branch_list'),
    path('branches/new/', views.branch_create, name='branch_create'),
    path('branches/<int:pk>/', views.branch_edit, name='branch_edit'),
    path('branches/<int:pk>/delete/', views.branch_delete, name='branch_delete'),
]
