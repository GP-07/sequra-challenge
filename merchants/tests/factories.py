"""factory_boy factories to create test data."""

import uuid
from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from merchants.models import Merchant


class MerchantFactory(DjangoModelFactory):
    class Meta:
        model = Merchant

    external_id = factory.LazyFunction(uuid.uuid4)
    reference = factory.Sequence(lambda number: f"merchant_{number}")
    email = factory.LazyAttribute(lambda merchant: f"info@{merchant.reference}.com")
    live_on = date(2023, 1, 1)
    disbursement_frequency = Merchant.Frequency.DAILY
    minimum_monthly_fee = Decimal("0.00")
