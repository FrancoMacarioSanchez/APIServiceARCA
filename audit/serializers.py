from rest_framework import serializers
from .models import PeticionFacturacion

class NuevaFacturacionSerializer(serializers.Serializer):
    saas = serializers.CharField(max_length=50)
    tenant = serializers.CharField(max_length=100)
    punto_venta = serializers.IntegerField()
    cuit_emisor = serializers.CharField(max_length=15)
    monto_total = serializers.DecimalField(max_digits=15, decimal_places=2)
    
    concepto = serializers.IntegerField(default=1)
    cliente_doc_tipo = serializers.IntegerField(default=99)
    cliente_doc_nro = serializers.IntegerField(default=0)
    tipo_comprobante = serializers.IntegerField(default=11)
    # Nuevo campo obligatorio para la RG 5616
    cliente_condicion_iva = serializers.IntegerField(default=5)

class PeticionFacturacionSerializer(serializers.ModelSerializer):
    """
    Serializa el modelo para la consulta de la bitácora (GET).
    """
    class Meta:
        model = PeticionFacturacion
        fields = '__all__'
        read_only_fields = ('fecha_hora', 'cae_asignado', 'respuesta_arca', 'estado')