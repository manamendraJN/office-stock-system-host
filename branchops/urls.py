from django.urls import path

from branchops import views

app_name = 'branchops'

urlpatterns = [
    path('requests/', views.request_list, name='request_list'),
    path('requests/new/', views.request_create, name='request_create'),
    path('requests/<int:pk>/', views.request_detail, name='request_detail'),
    path('requests/<int:pk>/cancel/', views.request_cancel, name='request_cancel'),
    path('requests/<int:pk>/review/', views.request_review, name='request_review'),
    path('dispatches/', views.dispatch_list, name='dispatch_list'),
    path('dispatches/new/', views.dispatch_create, name='dispatch_create'),
    path('dispatches/<int:pk>/', views.dispatch_detail, name='dispatch_detail'),
    path('dispatches/<int:pk>/receive/', views.dispatch_receive, name='dispatch_receive'),
    path('dispatches/<int:pk>/close/', views.dispatch_close, name='dispatch_close'),
]
