"""Ingreso de una order (lo que usaría la API REST)."""

from datetime import date
from decimal import Decimal

import pytest

from merchants.tests.factories import MerchantFactory
from orders.exceptions import InvalidOrder
from orders.models import Order
from orders.services.orders import create_order

pytestmark = pytest.mark.django_db


def test_commission_is_calculated_when_the_order_is_saved():
    MerchantFactory(reference="padberg_group")

    order = create_order(
        order_id="e653f3e14bc4", merchant_reference="padberg_group", amount=Decimal("102.29"), order_creation_date=date(2023, 2, 1)
    )

    order.refresh_from_db()
    assert order.commission_fee == Decimal("0.97")
    assert order.disbursement is None


def test_unknown_merchant_is_rejected():
    with pytest.raises(InvalidOrder):
        create_order(order_id="x1", merchant_reference="does_not_exist", amount=Decimal("10.00"), order_creation_date=date(2023, 2, 1))
    assert not Order.objects.exists()


def test_negative_amount_is_rejected():
    MerchantFactory(reference="padberg_group")
    with pytest.raises(InvalidOrder):
        create_order(order_id="x1", merchant_reference="padberg_group", amount=Decimal("-5.00"), order_creation_date=date(2023, 2, 1))
    assert not Order.objects.exists()


def test_zero_amount_is_accepted_with_zero_commission():
    # Es raro, pero podría ser válida.
    MerchantFactory(reference="padberg_group")

    create_order(order_id="x1", merchant_reference="padberg_group", amount=Decimal("0.00"), order_creation_date=date(2023, 2, 1))

    order = Order.objects.get(id="x1")
    assert order.amount == Decimal("0.00")
    assert order.commission_fee == Decimal("0.00")


def test_duplicated_order_id_is_rejected():
    MerchantFactory(reference="padberg_group")
    create_order(order_id="x1", merchant_reference="padberg_group", amount=Decimal("10.00"), order_creation_date=date(2023, 2, 1))

    with pytest.raises(InvalidOrder):
        create_order(order_id="x1", merchant_reference="padberg_group", amount=Decimal("20.00"), order_creation_date=date(2023, 2, 1))
    assert Order.objects.get(id="x1").amount == Decimal("10.00")
