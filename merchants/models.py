from django.db import models

from core.constants import MONEY


class Merchant(models.Model):
    class Frequency(models.TextChoices):
        DAILY = "DAILY"
        WEEKLY = "WEEKLY"

    id = models.UUIDField(primary_key=True)
    reference = models.CharField(max_length=255, unique=True)
    email = models.EmailField()
    live_on = models.DateField()
    disbursement_frequency = models.CharField(max_length=10, choices=Frequency.choices)
    minimum_monthly_fee = models.DecimalField(**MONEY)

    def __str__(self):
        return self.reference
