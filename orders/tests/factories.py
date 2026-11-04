"""factory_boy factories to create test data."""

from datetime import date
from decimal import Decimal

import factory
from factory.django import DjangoModelFactory

from merchants.tests.factories import MerchantFactory
from orders.models import Order


class OrderFactory(DjangoModelFactory):
    """commission_fee is explicit so as not to depend on the calculation."""

    class Meta:
        model = Order

    external_id = factory.Sequence(lambda number: f"order{number:07d}")
    merchant = factory.SubFactory(MerchantFactory)
    amount = Decimal("100.00")
    commission_fee = Decimal("0.95")
    order_creation_date = date(2023, 2, 7)
