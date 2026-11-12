from django.contrib import admin
from django.urls import include, path
from django.http import HttpResponse, JsonResponse

def home(request):
    return HttpResponse("Welcome to the API")

def health(request):
    return JsonResponse({'status': 'ok'})

urlpatterns = [
    path('admin/', admin.site.urls),
    path('health/', health, name='health'),
    path('', home, name='home'),
    path('api/', include('inventory.urls')),
]
