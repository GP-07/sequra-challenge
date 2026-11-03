"""Tabla anual del README.

Assumptions: los disbursements se imputan por fecha de pago, y la monthly fee al mes que cubre.
"""

from datetime import date
from decimal import Decimal

import pytest

from disbursements.models import Disbursement
from disbursements.services.reports import yearly_report
from disbursements.tests.factories import DisbursementFactory
from fees.models import MonthlyFee
from merchants.tests.factories import MerchantFactory

pytestmark = pytest.mark.django_db


def completed(merchant, payment_date, gross, fee):
    return DisbursementFactory(
        merchant=merchant,
        payment_date=payment_date,
        status=Disbursement.Status.COMPLETED,
        gross_amount=Decimal(gross),
        commission_fee_amount=Decimal(fee),
        disbursed_amount=Decimal(gross) - Decimal(fee),
    )


def test_yearly_rows():
    merchant = MerchantFactory(reference="padberg_group", live_on=date(2022, 1, 1))
    other = MerchantFactory(reference="windler_and_sons", live_on=date(2022, 1, 1))
    completed(merchant, date(2022, 12, 30), "100.00", "0.95")
    # Orders del 31/12 pagadas el 1/1: cuentan en 2023.
    completed(merchant, date(2023, 1, 1), "200.00", "1.90")
    completed(other, date(2023, 1, 2), "50.00", "0.48")
    # La monthly fee de diciembre se calcula en enero, pero cuenta en 2022.
    MonthlyFee.objects.create(
        merchant=merchant, month=date(2022, 12, 1), commissions_amount=Decimal("5.00"),
        minimum_monthly_fee=Decimal("29.00"), amount=Decimal("24.00"),
    )
    MonthlyFee.objects.create(
        merchant=other, month=date(2023, 1, 1), commissions_amount=Decimal("0.48"),
        minimum_monthly_fee=Decimal("15.00"), amount=Decimal("14.52"),
    )

    report = yearly_report()

    assert report == [
        {
            "year": 2022,
            "disbursements_count": 1,
            "disbursed_amount": Decimal("99.05"),
            "order_fees_amount": Decimal("0.95"),
            "monthly_fees_count": 1,
            "monthly_fees_amount": Decimal("24.00"),
        },
        {
            "year": 2023,
            "disbursements_count": 2,
            "disbursed_amount": Decimal("247.62"),
            "order_fees_amount": Decimal("2.38"),
            "monthly_fees_count": 1,
            "monthly_fees_amount": Decimal("14.52"),
        },
    ]


def test_only_completed_disbursements_are_reported():
    merchant = MerchantFactory(reference="padberg_group")
    DisbursementFactory(merchant=merchant, payment_date=date(2023, 1, 2), status=Disbursement.Status.PENDING)
    DisbursementFactory(merchant=merchant, payment_date=date(2023, 1, 3), status=Disbursement.Status.FAILED)
    DisbursementFactory(merchant=merchant, payment_date=date(2023, 1, 4), status=Disbursement.Status.REQUIRES_ATTENTION)

    report = yearly_report()

    assert report == []


def test_year_with_only_monthly_fees():
    merchant = MerchantFactory(reference="padberg_group")
    MonthlyFee.objects.create(
        merchant=merchant, month=date(2023, 1, 1), commissions_amount=Decimal("0.00"),
        minimum_monthly_fee=Decimal("29.00"), amount=Decimal("29.00"),
    )

    report = yearly_report()

    assert report == [
        {
            "year": 2023,
            "disbursements_count": 0,
            "disbursed_amount": Decimal("0.00"),
            "order_fees_amount": Decimal("0.00"),
            "monthly_fees_count": 1,
            "monthly_fees_amount": Decimal("29.00"),
        }
    ]
