from django.db import models
from django.utils import timezone
from datetime import timedelta

class ArcaToken(models.Model):
    AMBIENTES = [
        ('HOMOLOGACION', 'Homologación'),
        ('PRODUCCION', 'Producción'),
    ]
    
    servicio = models.CharField(max_length=50, default='wsfe')
    ambiente = models.CharField(max_length=20, choices=AMBIENTES)
    
    token = models.TextField()
    sign = models.TextField()
    
    expiracion = models.DateTimeField()
    creado_el = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'arca_tokens'
        ordering = ['-expiracion']
        indexes = [
            models.Index(fields=['servicio', 'ambiente', 'expiracion']),
        ]

    def esta_vigente(self):
        # Retorna True si al token le quedan más de 5 minutos de vida útil.
        # Esto previene fallos por desincronización de relojes durante el request.
        return self.expiracion > timezone.now() + timedelta(minutes=5)

    def __str__(self):
        return f"TA {self.servicio} ({self.ambiente}) - Expira: {self.expiracion}"