from django.db import models

from core.constants import MONEY
from merchants.managers import MerchantQuerySet


class Merchant(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "DAILY"
        WEEKLY = "WEEKLY"

    # CSV id: used for lookups. The PK is the DB autoincrement id, which is the one used for ordering and in FKs.
    external_id = models.UUIDField(unique=True)
    reference = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    live_on = models.DateField()
    disbursement_frequency = models.CharField(max_length=10, choices=Frequency.choices)
    minimum_monthly_fee = models.DecimalField(**MONEY)

    objects = MerchantQuerySet.as_manager()

    def __str__(self):
        return self.reference
