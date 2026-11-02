"""Factories de factory_boy para crear datos de prueba."""

import uuid
from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from merchants.models import Merchant


class MerchantFactory(DjangoModelFactory):
    class Meta:
        model = Merchant

    id = factory.LazyFunction(uuid.uuid4)
    reference = factory.Sequence(lambda n: f"merchant_{n}")
    email = factory.LazyAttribute(lambda merchant: f"info@{merchant.reference}.com")
    live_on = date(2023, 1, 1)
    disbursement_frequency = Merchant.Frequency.DAILY
    minimum_monthly_fee = Decimal("0.00")
