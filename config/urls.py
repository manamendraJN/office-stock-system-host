from django.urls import include, path

urlpatterns = [
    path('', include('core.urls')),
    path('', include('accounts.urls')),
    path('', include('catalog.urls')),
    path('', include('inventory.urls')),
    path('', include('branchops.urls')),
    path('', include('pettycash.urls')),
    path('reports/', include('reports.urls')),
]

handler403 = 'core.views.permission_denied'
handler404 = 'core.views.not_found'
