"""calculate_monthly_fees_for_range: backfill of monthly fees for a range of months."""

from datetime import date
from decimal import Decimal

import pytest
from django.core.management import CommandError

from core.tests.helpers import run_command
from fees.models import MonthlyFee
from merchants.tests.factories import MerchantFactory
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db


def test_calculates_the_monthly_fees_of_the_range():
    # padberg_group has minimum 0: it is not charged.
    padberg = MerchantFactory(reference="padberg_group", live_on=date(2023, 2, 1), minimum_monthly_fee="0.00")
    deckow = MerchantFactory(reference="deckow_gibson", live_on=date(2023, 2, 1), minimum_monthly_fee="29.00")
    OrderFactory(merchant=padberg, order_creation_date=date(2023, 2, 1), commission_fee="0.97")
    OrderFactory(merchant=deckow, order_creation_date=date(2023, 2, 2), commission_fee="0.11")

    output = run_command("calculate_monthly_fees_for_range", "--from", "2023-02", "--to", "2023-02")

    assert MonthlyFee.objects.count() == 1
    fee = MonthlyFee.objects.get(merchant=deckow, month=date(2023, 2, 1))
    assert fee.commissions_amount == Decimal("0.11")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("28.89")
    assert "Monthly fees created: 1" in output


@pytest.mark.parametrize(
    "month_from, month_to",
    [
        ("2023-13", "2023-02"),
        ("2023-02", "febrero"),
        # The range is reversed.
        ("2023-03", "2023-02"),
    ],
)
def test_invalid_range_is_rejected(month_from, month_to):
    with pytest.raises(CommandError):
        run_command("calculate_monthly_fees_for_range", "--from", month_from, "--to", month_to)
