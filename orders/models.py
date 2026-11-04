from django.db import models

from core.constants import MONEY
from orders.managers import OrderQuerySet


class Order(models.Model):
    # CSV id: used for lookups. The PK is the DB autoincrement id, which is the one used for ordering and in FKs.
    external_id = models.CharField(max_length=64, unique=True)
    merchant = models.ForeignKey("merchants.Merchant", on_delete=models.PROTECT, related_name="orders")
    amount = models.DecimalField(**MONEY)
    commission_fee = models.DecimalField(**MONEY)
    # Date the order was created (created_at in the CSV); it is not an audit field.
    order_creation_date = models.DateField()
    disbursement = models.ForeignKey(
        "disbursements.Disbursement", null=True, blank=True, on_delete=models.PROTECT, related_name="orders"
    )

    objects = OrderQuerySet.as_manager()

    class Meta:
        indexes = [
            models.Index(fields=["merchant", "order_creation_date"], name="order_merchant_date_idx"),
            # Only the unpaid orders: the search for pending orders does not go through the assigned ones.
            models.Index(
                fields=["merchant", "order_creation_date"],
                name="order_pending_merchant_idx",
                condition=models.Q(disbursement__isnull=True),
            ),
        ]
