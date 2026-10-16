from django.db import models
from django.utils import timezone

class PeticionFacturacion(models.Model):
    ESTADOS = [
        ('EXITO', 'Aprobado por ARCA'),
        ('RECHAZO', 'Rechazado por ARCA'),
        ('ERROR_RED', 'Error de comunicación / Timeout'),
        ('PENDIENTE', 'Pendiente / En proceso'),
    ]

    # Identificadores de origen
    sistema_origen = models.CharField(max_length=50, help_text="Ej: Avany, NexoRetail")
    tenant_id = models.CharField(max_length=100, help_text="Schema o identificador del cliente")
    punto_venta = models.IntegerField()
    
    # Datos core
    cuit_emisor = models.CharField(max_length=15)
    monto_total = models.DecimalField(max_digits=15, decimal_places=2)
    
    # Bitácora
    fecha_hora = models.DateTimeField(default=timezone.now)
    estado = models.CharField(max_length=20, choices=ESTADOS, default='PENDIENTE')
    
    # Payload y Respuesta
    payload_recibido = models.JSONField(help_text="Cuerpo original del POST")
    respuesta_arca = models.JSONField(help_text="Respuesta XML parseada o traza de error", null=True, blank=True)
    cae_asignado = models.CharField(max_length=50, null=True, blank=True)

    class Meta:
        db_table = 'audit_peticion_facturacion'
        ordering = ['-fecha_hora']
        indexes = [
            # Índices compuestos para acelerar los filtros del endpoint GET
            models.Index(fields=['sistema_origen', 'tenant_id']),
            models.Index(fields=['fecha_hora']),
            models.Index(fields=['estado']),
        ]

    def __str__(self):
        return f"[{self.estado}] {self.sistema_origen}/{self.tenant_id} - ${self.monto_total}"