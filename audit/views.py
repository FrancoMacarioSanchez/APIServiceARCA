from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status, generics
from rest_framework.permissions import IsAuthenticated
from django.utils.dateparse import parse_datetime

from .models import PeticionFacturacion
from .serializers import PeticionFacturacionSerializer, NuevaFacturacionSerializer
from .authentication import StaticApiKeyAuthentication
from arca_engine.client import emitir_factura_arca

class FacturarArqueAPIView(APIView):
    authentication_classes = [StaticApiKeyAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = NuevaFacturacionSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        datos = serializer.validated_data
        
        # 1. Crear el registro asumiendo fallo por defecto (útil ante un crash severo)
        registro = PeticionFacturacion.objects.create(
            sistema_origen=datos['saas'],
            tenant_id=datos['tenant'],
            punto_venta=datos['punto_venta'],
            cuit_emisor=datos['cuit_emisor'],
            monto_total=datos['monto_total'],
            payload_recibido=request.data,
            estado='ERROR_RED'  
        )

        try:
            # 2. Llamada síncrona al motor de ARCA
            respuesta_arca = emitir_factura_arca(
                payload=datos,
                cuit_emisor=datos['cuit_emisor'],
                punto_venta=datos['punto_venta']
            )

            registro.respuesta_arca = respuesta_arca
            
            if respuesta_arca.get("resultado") == "A":
                registro.estado = 'EXITO'
                registro.cae_asignado = respuesta_arca.get("cae")
                http_status = status.HTTP_201_CREATED
            else:
                registro.estado = 'RECHAZO'
                http_status = status.HTTP_400_BAD_REQUEST

        except Exception as e:
            # 3. Captura timeouts, problemas de certificados o WSAA caído
            registro.respuesta_arca = {"error_interno": str(e)}
            http_status = status.HTTP_502_BAD_GATEWAY
        
        finally:
            # 4. Persistir SIEMPRE la actualización en la base de datos
            registro.save()

        # 5. Devolver la respuesta estructurada al sistema origen
        if registro.estado == 'EXITO':
            return Response({
                'status': 'ok',
                'cae': registro.cae_asignado,
                'numero': registro.respuesta_arca.get("numero_asignado"),
                'vencimiento_cae': registro.respuesta_arca.get("cae_vencimiento"),
                'fecha_registro': registro.fecha_hora
            }, status=http_status)
        
        return Response({
            'status': 'error',
            'detalle': registro.respuesta_arca
        }, status=http_status)


class ConsultarBitacoraAPIView(generics.ListAPIView):
    authentication_classes = [StaticApiKeyAuthentication]
    permission_classes = [IsAuthenticated]
    serializer_class = PeticionFacturacionSerializer

    def get_queryset(self):
        queryset = PeticionFacturacion.objects.all()
        params = self.request.query_params
        
        # Filtros exactos
        filtros = {
            'sistema_origen': params.get('saas'),
            'tenant_id': params.get('tenant'),
            'estado': params.get('estado'),
        }
        
        for campo, valor in filtros.items():
            if valor:
                queryset = queryset.filter(**{campo: valor})

        # Filtros por rango de fechas
        if desde := params.get('fecha_desde'):
            if parsed_desde := parse_datetime(desde):
                queryset = queryset.filter(fecha_hora__gte=parsed_desde)
                
        if hasta := params.get('fecha_hasta'):
            if parsed_hasta := parse_datetime(hasta):
                queryset = queryset.filter(fecha_hora__lte=parsed_hasta)

        return queryset