"""Factories de factory_boy para crear datos de prueba."""

from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from merchants.tests.factories import MerchantFactory
from orders.models import Order


class OrderFactory(DjangoModelFactory):
    """commission_fee es explícita para no depender del cálculo."""

    class Meta:
        model = Order

    id = factory.Sequence(lambda n: f"order{n:07d}")
    merchant = factory.SubFactory(MerchantFactory)
    amount = Decimal("100.00")
    commission_fee = Decimal("0.95")
    order_creation_date = date(2023, 2, 7)
