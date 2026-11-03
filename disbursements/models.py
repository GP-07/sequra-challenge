from django.db import models

from core.constants import MONEY
from disbursements.managers import DisbursementQuerySet


class Disbursement(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"
        REQUIRES_ATTENTION = "REQUIRES_ATTENTION"

    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="disbursements")
    payment_date = models.DateField()
    reference = models.CharField(max_length=255, unique=True)
    natural_key_hash = models.CharField(max_length=64, unique=True)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    package = models.ForeignKey(
        "disbursement_packages.DisbursementPackage", null=True, blank=True, on_delete=models.PROTECT, related_name="disbursements"
    )
    order_count = models.PositiveIntegerField(default=0)
    has_processed_delayed_orders = models.BooleanField(default=False)
    # Motivo por el que falló al procesar su paquete.
    error = models.TextField(blank=True)
    # Si falló: True si reintentarlo puede servir (error de infraestructura), False si no (datos o bug).
    is_retryable = models.BooleanField(null=True)
    # Se completan al procesar el paquete.
    gross_amount = models.DecimalField(null=True, blank=True, **MONEY)
    commission_fee_amount = models.DecimalField(null=True, blank=True, **MONEY)
    disbursed_amount = models.DecimalField(null=True, blank=True, **MONEY)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = DisbursementQuerySet.as_manager()

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "payment_date"], name="unique_disbursement_per_merchant_and_date"),
        ]
