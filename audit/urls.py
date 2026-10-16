from django.contrib import admin
from django.urls import path

from django.urls import path
from .views import FacturarArqueAPIView, ConsultarBitacoraAPIView

urlpatterns = [
    path('emitir/', FacturarArqueAPIView.as_view(), name='emitir_factura'),
    path('bitacora/', ConsultarBitacoraAPIView.as_view(), name='consultar_bitacora'),
]