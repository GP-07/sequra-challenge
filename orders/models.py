from django.db import models

from core.constants import MONEY
from orders.managers import OrderQuerySet


class Order(models.Model):
    # id del CSV: se usa para buscar. La PK es el id autoincremental de la DB, que es el que se usa para ordenar y en las FKs.
    external_id = models.CharField(max_length=64, unique=True)
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="orders")
    amount = models.DecimalField(**MONEY)
    commission_fee = models.DecimalField(**MONEY)
    # Fecha en que se creó la order (created_at del CSV); no es un campo de auditoría.
    order_creation_date = models.DateField()
    disbursement = models.ForeignKey(
        "disbursements.Disbursement", null=True, blank=True, on_delete=models.PROTECT, related_name="orders"
    )

    objects = OrderQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "order_creation_date"], name="order_merchant_date_idx"),
            # Solo las orders sin pagar: la búsqueda de pendientes no recorre las ya asignadas.
            models.Index(
                fields=["merchant", "order_creation_date"],
                name="order_pending_merchant_idx",
                condition=models.Q(disbursement__isnull=True),
            ),
        ]
