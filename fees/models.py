from django.db import models

from core.constants import MONEY


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
