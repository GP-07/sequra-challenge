"""Comisión de seQura por order: tramos del enunciado, redondeo half-up a 2 decimales."""

from decimal import Decimal

import pytest

from disbursements.services.commissions import calculate_commission_fee


@pytest.mark.parametrize(
    "amount, expected",
    [
        # Menos de 50 €: 1,00%.
        ("10.00", "0.10"),
        ("49.99", "0.50"),
        # Assumption: 50 € exactos pagan 0,95%.
        ("50.00", "0.48"),
        ("102.29", "0.97"),
        ("299.99", "2.85"),
        # Assumption: 300 € exactos pagan 0,85%.
        ("300.00", "2.55"),
        ("433.21", "3.68"),
    ],
)
def test_commission_by_tier(amount, expected):
    fee = calculate_commission_fee(Decimal(amount))

    assert fee == Decimal(expected)


def test_rounds_half_up_not_half_even():
    # 10,50 × 1% = 0,105. Half-up da 0,11; el redondeo bancario daría 0,10.
    fee = calculate_commission_fee(Decimal("10.50"))

    assert fee == Decimal("0.11")


def test_result_has_two_decimals():
    fee = calculate_commission_fee(Decimal("61.74"))

    assert fee.as_tuple().exponent == -2


def test_zero_amount_has_zero_commission():
    fee = calculate_commission_fee(Decimal("0.00"))

    assert fee == Decimal("0.00")


def test_rejects_negative_amounts():
    with pytest.raises(ValueError):
        calculate_commission_fee(Decimal("-10.00"))
