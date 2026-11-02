from django.db import models

from core.constants import MONEY


class DisbursementPackage(models.Model):
    class Status(models.TextChoices):
        PENDING = "PENDING"
        PROCESSING = "PROCESSING"
        COMPLETED = "COMPLETED"
        FAILED = "FAILED"

    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    order_count = models.PositiveIntegerField(default=0)
    attempts = models.PositiveIntegerField(default=0)
    is_retryable = models.BooleanField(null=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


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
        DisbursementPackage, null=True, blank=True, on_delete=models.PROTECT, related_name="disbursements"
    )
    order_count = models.PositiveIntegerField(default=0)
    has_processed_delayed_orders = models.BooleanField(default=False)
    # Motivo por el que falló al procesar su paquete.
    error = models.TextField(blank=True)
    # Se completan al procesar el paquete.
    gross_amount = models.DecimalField(null=True, blank=True, **MONEY)
    commission_fee_amount = models.DecimalField(null=True, blank=True, **MONEY)
    disbursed_amount = models.DecimalField(null=True, blank=True, **MONEY)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "payment_date"], name="unique_disbursement_per_merchant_and_date"),
        ]


class Order(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="orders")
    amount = models.DecimalField(**MONEY)
    commission_fee = models.DecimalField(**MONEY)
    created_at = models.DateField()
    disbursement = models.ForeignKey(
        Disbursement, null=True, blank=True, on_delete=models.PROTECT, related_name="orders"
    )

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "created_at"], name="order_merchant_created_idx"),
        ]


class MonthlyFee(models.Model):
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="monthly_fees")
    # Primer día del mes que cubre la fee.
    month = models.DateField()
    commissions_amount = models.DecimalField(**MONEY)
    minimum_monthly_fee = models.DecimalField(**MONEY)
    amount = models.DecimalField(**MONEY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["merchant", "month"], name="unique_monthly_fee_per_merchant_and_month"),
        ]
