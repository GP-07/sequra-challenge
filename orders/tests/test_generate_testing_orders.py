"""generate_testing_orders: test data to exercise the daily flow."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest
from django.core.management import CommandError

from core.tests.helpers import run_command
from merchants.models import Merchant
from merchants.tests.factories import MerchantFactory
from orders.models import Order
from orders.services.commissions import calculate_commission_fee

pytestmark = pytest.mark.django_db

TODAY = datetime(2023, 2, 8, 10, 0, tzinfo=timezone.utc)
YESTERDAY = date(2023, 2, 7)


@pytest.fixture(autouse=True)
def fixed_today():
    with mock.patch("orders.management.commands.generate_testing_orders.now", return_value=TODAY):
        yield


def test_creates_the_orders_dated_yesterday_with_their_commission():
    output = run_command("generate_testing_orders", "--count", "6")

    orders = list(Order.objects.all())
    assert len(orders) == 6
    assert {order.order_creation_date for order in orders} == {YESTERDAY}
    assert all(order.commission_fee == calculate_commission_fee(order.amount) for order in orders)
    assert "Orders created: 6, dated 2023-02-07" in output
    assert "They are paid by the disbursement run of 2023-02-08." in output


def test_creates_two_daily_merchants_live_since_the_day_before():
    run_command("generate_testing_orders", "--count", "2", "--date", "2023-02-01")

    merchants = list(Merchant.objects.all())
    assert len(merchants) == 2
    assert {merchant.disbursement_frequency for merchant in merchants} == {Merchant.Frequency.DAILY}
    assert {merchant.live_on for merchant in merchants} == {date(2023, 1, 31)}
    assert {merchant.minimum_monthly_fee for merchant in merchants} == {Decimal("29.00")}
    assert all(merchant.reference.startswith("testing_") for merchant in merchants)
    assert all(merchant.email == f"info@{merchant.reference}.com" for merchant in merchants)


def test_with_two_orders_each_merchant_gets_one():
    output = run_command("generate_testing_orders", "--count", "2")

    for merchant in Merchant.objects.all():
        assert Order.objects.filter(merchant=merchant).count() == 1
        assert f"{merchant.reference} (DAILY): 1 orders" in output


def test_every_merchant_gets_at_least_one_order():
    run_command("generate_testing_orders", "--count", "50")

    order_counts = [Order.objects.filter(merchant=merchant).count() for merchant in Merchant.objects.all()]
    assert len(order_counts) == 2
    assert min(order_counts) >= 1
    assert sum(order_counts) == 50


def test_existing_merchants_get_no_orders():
    existing = MerchantFactory()

    run_command("generate_testing_orders", "--count", "10")

    assert Merchant.objects.count() == 3
    assert Order.objects.filter(merchant=existing).count() == 0


def test_orders_cover_the_three_commission_tiers():
    run_command("generate_testing_orders", "--count", "3")

    amounts = sorted(Order.objects.values_list("amount", flat=True))
    assert Decimal("1.00") <= amounts[0] < Decimal("50")
    assert Decimal("50") <= amounts[1] < Decimal("300")
    assert Decimal("300") <= amounts[2] <= Decimal("1000.00")


@pytest.mark.parametrize("count", ["1", "51"])
def test_count_must_be_from_two_to_fifty(count):
    with pytest.raises(CommandError) as error:
        run_command("generate_testing_orders", "--count", count)

    assert "--count must be from 2 to 50" in str(error.value)
    assert Merchant.objects.count() == 0


def test_a_date_after_today_is_rejected():
    with pytest.raises(CommandError) as error:
        run_command("generate_testing_orders", "--date", "2023-02-09")

    assert "after today" in str(error.value)
    assert Order.objects.count() == 0
