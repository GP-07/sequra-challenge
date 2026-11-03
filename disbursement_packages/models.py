from django.db import models


class DisbursementPackage(models.Model):
    """Agrupación lógica de disbursements para procesarlos juntos.

    El resultado (COMPLETED/FAILED, error, si se puede reintentar) es de cada disbursement; el status
    del paquete resume: COMPLETED si todos sus disbursements lo están, FAILED si alguno no.
    """

    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    order_count = models.PositiveIntegerField(default=0)
    # Cada vez que se toma para procesar (1 + reintentos): limita cuántas veces se reprocesa.
    attempts = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
