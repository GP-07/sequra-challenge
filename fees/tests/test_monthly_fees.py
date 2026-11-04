"""calculate_monthly_fees: on day 1 the previous month is checked per merchant."""

from datetime import date
from decimal import Decimal

import pytest

from disbursements.tests.factories import DisbursementFactory
from fees.models import MonthlyFee
from fees.services.monthly_fees import calculate_monthly_fees, calculate_monthly_fees_for_range
from merchants.models import Merchant
from merchants.tests.factories import MerchantFactory
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

JANUARY = date(2023, 1, 1)


@pytest.fixture
def merchant():
    return MerchantFactory(reference="padberg_group", live_on=date(2022, 6, 1), minimum_monthly_fee="29.00")


def test_charges_what_is_left_to_reach_the_minimum(merchant):
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 10), commission_fee="10.00")
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 31), commission_fee="5.50")

    calculate_monthly_fees(JANUARY)

    fee = MonthlyFee.objects.get(merchant=merchant, month=JANUARY)
    assert fee.commissions_amount == Decimal("15.50")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("13.50")


@pytest.mark.parametrize("commissions", ["29.00", "40.00"])
def test_nothing_is_charged_when_the_minimum_is_reached(merchant, commissions):
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 10), commission_fee=commissions)

    calculate_monthly_fees(JANUARY)

    assert not MonthlyFee.objects.filter(merchant=merchant).exists()


def test_merchant_without_minimum_is_never_charged():
    # 16 of the 50 merchants in the CSV have minimum_monthly_fee 0.0.
    no_minimum = MerchantFactory(reference="no_minimum", live_on=date(2022, 6, 1), minimum_monthly_fee="0.00")

    calculate_monthly_fees(JANUARY)

    assert not MonthlyFee.objects.filter(merchant=no_minimum).exists()


def test_only_orders_created_in_that_month_count(merchant):
    OrderFactory(merchant=merchant, order_creation_date=date(2022, 12, 31), commission_fee="20.00")
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 15), commission_fee="10.00")
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 1), commission_fee="20.00")

    calculate_monthly_fees(JANUARY)

    fee = MonthlyFee.objects.get(merchant=merchant, month=JANUARY)
    assert fee.commissions_amount == Decimal("10.00")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("19.00")


def test_orders_count_even_if_not_disbursed_yet(merchant):
    # Assumption: the orders created in the month are used, whether they are paid or not.
    paid = OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 10), commission_fee="10.00")
    DisbursementFactory(merchant=merchant, payment_date=date(2023, 1, 11), orders=[paid])
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 31), commission_fee="10.00")

    calculate_monthly_fees(JANUARY)

    fee = MonthlyFee.objects.get(merchant=merchant, month=JANUARY)
    assert fee.commissions_amount == Decimal("20.00")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("9.00")


def test_merchant_live_mid_month_pays_the_full_minimum():
    # Assumption: the first month is not prorated.
    late = MerchantFactory(reference="late_merchant", live_on=date(2023, 1, 20), minimum_monthly_fee="29.00")
    OrderFactory(merchant=late, order_creation_date=date(2023, 1, 25), commission_fee="1.00")

    calculate_monthly_fees(JANUARY)

    fee = MonthlyFee.objects.get(merchant=late, month=JANUARY)
    assert fee.commissions_amount == Decimal("1.00")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("28.00")


def test_live_merchant_without_orders_pays_the_full_minimum(merchant):
    calculate_monthly_fees(JANUARY)

    fee = MonthlyFee.objects.get(merchant=merchant, month=JANUARY)
    assert fee.commissions_amount == Decimal("0.00")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("29.00")


def test_merchant_not_live_yet_is_not_charged():
    future = MerchantFactory(reference="future_merchant", live_on=date(2023, 2, 1), minimum_monthly_fee="29.00")

    calculate_monthly_fees(JANUARY)

    assert not MonthlyFee.objects.filter(merchant=future).exists()


def test_running_twice_does_not_duplicate(merchant):
    calculate_monthly_fees(JANUARY)
    calculate_monthly_fees(JANUARY)

    assert MonthlyFee.objects.filter(merchant=merchant, month=JANUARY).count() == 1


def test_range_calculates_each_month_included(merchant):
    # January and February are covered (both included), which are already closed.
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 1, 10), commission_fee="10.00")
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 10), commission_fee="20.00")
    # March is out of the range: it is not calculated.
    OrderFactory(merchant=merchant, order_creation_date=date(2023, 3, 10), commission_fee="5.00")

    calculate_monthly_fees_for_range(date(2023, 1, 1), date(2023, 2, 1))

    january = MonthlyFee.objects.get(merchant=merchant, month=date(2023, 1, 1))
    assert january.commissions_amount == Decimal("10.00")
    assert january.minimum_monthly_fee == Decimal("29.00")
    assert january.amount == Decimal("19.00")
    february = MonthlyFee.objects.get(merchant=merchant, month=date(2023, 2, 1))
    assert february.commissions_amount == Decimal("20.00")
    assert february.minimum_monthly_fee == Decimal("29.00")
    assert february.amount == Decimal("9.00")
    assert not MonthlyFee.objects.filter(merchant=merchant, month=date(2023, 3, 1)).exists()


def test_daily_and_weekly_merchants_are_charged_the_same_way():
    # The monthly fee depends on the commissions of the month, not on how often the merchant is paid.
    daily = MerchantFactory(
        reference="daily_merchant",
        disbursement_frequency=Merchant.Frequency.DAILY,
        live_on=date(2022, 6, 1),
        minimum_monthly_fee="15.00",
    )
    weekly = MerchantFactory(
        reference="weekly_merchant",
        disbursement_frequency=Merchant.Frequency.WEEKLY,
        live_on=date(2022, 6, 1),
        minimum_monthly_fee="15.00",
    )
    OrderFactory(merchant=daily, order_creation_date=date(2023, 1, 10), commission_fee="5.00")
    OrderFactory(merchant=weekly, order_creation_date=date(2023, 1, 10), commission_fee="5.00")

    calculate_monthly_fees(JANUARY)

    for merchant in (daily, weekly):
        fee = MonthlyFee.objects.get(merchant=merchant, month=JANUARY)
        assert fee.commissions_amount == Decimal("5.00")
        assert fee.minimum_monthly_fee == Decimal("15.00")
        assert fee.amount == Decimal("10.00")
