"""process_disbursement_package: atomic take of the package and a result per disbursement.

- Data failure (an invalid disbursement): the others become COMPLETED with their totals.
- Infrastructure or unexpected failure: everything is rolled back and nothing is left half done.
- Reprocessing only touches what is not COMPLETED.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.db import OperationalError, connection

from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_processing import process_disbursement_package
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.models import Order
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status
PAYMENT_DATE = date(2023, 2, 8)
ORDERS_DATE = date(2023, 2, 7)
SERVICE = "disbursement_packages.services.package_processing"


@pytest.fixture
def package():
    merchant_a = MerchantFactory(reference="a_merchant")
    merchant_b = MerchantFactory(reference="b_merchant")
    orders_a = [
        OrderFactory(merchant=merchant_a, order_creation_date=ORDERS_DATE, amount="100.00", commission_fee="0.95"),
        OrderFactory(merchant=merchant_a, order_creation_date=ORDERS_DATE, amount="433.21", commission_fee="3.68"),
    ]
    orders_b = [OrderFactory(merchant=merchant_b, order_creation_date=ORDERS_DATE, amount="10.50", commission_fee="0.11")]
    disbursements = [
        DisbursementFactory(merchant=merchant_a, payment_date=PAYMENT_DATE, orders=orders_a),
        DisbursementFactory(merchant=merchant_b, payment_date=PAYMENT_DATE, orders=orders_b),
    ]
    return DisbursementPackageFactory(disbursements=disbursements)


def test_calculates_totals_and_completes_package_and_disbursements(package):
    processed = process_disbursement_package(package.id)

    assert processed is True

    package.refresh_from_db()
    assert package.status == Status.COMPLETED
    assert package.attempts == 1
    disbursement_a = Disbursement.objects.get(merchant__reference="a_merchant")
    assert disbursement_a.status == Disbursement.Status.COMPLETED
    assert disbursement_a.gross_amount == Decimal("533.21")
    assert disbursement_a.commission_fee_amount == Decimal("4.63")
    # Commissions are subtracted from the gross amount.
    assert disbursement_a.disbursed_amount == Decimal("528.58")
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert disbursement_b.status == Disbursement.Status.COMPLETED
    assert (disbursement_b.gross_amount, disbursement_b.commission_fee_amount, disbursement_b.disbursed_amount) == (
        Decimal("10.50"),
        Decimal("0.11"),
        Decimal("10.39"),
    )


@pytest.mark.parametrize("status", [Status.PROCESSING, Status.COMPLETED])
def test_package_that_cannot_be_taken_is_left_alone(package, status):
    DisbursementPackage.objects.filter(id=package.id).update(status=status)
    disbursements_before = disbursements_snapshot(package)

    processed = process_disbursement_package(package.id)

    assert processed is False
    package.refresh_from_db()
    assert package.status == status
    assert package.attempts == 0
    # It does not touch the disbursements: they stay as they were, with or without totals.
    assert disbursements_snapshot(package) == disbursements_before


def disbursements_snapshot(package):
    return list(
        Disbursement.objects.filter(package=package)
        .order_by("id")
        .values("status", "gross_amount", "commission_fee_amount", "disbursed_amount", "updated_at")
    )


def test_failed_package_can_be_processed_again(package):
    DisbursementPackage.objects.filter(id=package.id).update(status=Status.FAILED, attempts=1)
    Disbursement.objects.filter(package=package).update(
        status=Disbursement.Status.FAILED, error="connection lost", is_retryable=True
    )

    processed = process_disbursement_package(package.id)

    assert processed is True

    package.refresh_from_db()
    assert package.status == Status.COMPLETED
    assert package.attempts == 2
    assert not Disbursement.objects.exclude(status=Disbursement.Status.COMPLETED).exists()
    # When completed, the error of the previous run is cleared.
    assert list(Disbursement.objects.values_list("error", "is_retryable").distinct()) == [("", None)]


@pytest.mark.parametrize(
    "error, retryable",
    [
        # Infraestructura: reintentar puede servir.
        (OperationalError("deadlock detected"), True),
        (TimeoutError("timeout"), True),
        # Unexpected (a bug): retrying does not help.
        (ValueError("invalid data"), False),
    ],
)
def test_unexpected_error_rolls_back_and_fails_package_and_disbursements(package, error, retryable):
    # Fails while saving: we rely on transaction.atomic so nothing is left written.
    with mock.patch(f"{SERVICE}.save_disbursement_results", side_effect=error):
        process_disbursement_package(package.id)

    package.refresh_from_db()
    assert package.status == Status.FAILED
    assert package.attempts == 1
    for disbursement in Disbursement.objects.filter(package=package):
        assert disbursement.status == Disbursement.Status.FAILED
        assert disbursement.is_retryable is retryable
        assert str(error) in disbursement.error
        assert disbursement.gross_amount is None


@pytest.mark.parametrize(
    "amount, commission_fee, reason",
    [
        # Data fixed by hand that left the order with a negative amount.
        ("-10.50", "0.11", "Negative amounts"),
        # Commissions greater than the gross amount: a negative amount would be paid.
        ("10.50", "20.00", "greater than the gross amount"),
    ],
)
def test_disbursement_with_invalid_amounts_fails_and_does_not_undo_the_others(package, amount, commission_fee, reason):
    Order.objects.filter(merchant__reference="b_merchant").update(amount=amount, commission_fee=commission_fee)

    process_disbursement_package(package.id)

    disbursement_a = Disbursement.objects.get(merchant__reference="a_merchant")
    assert disbursement_a.status == Disbursement.Status.COMPLETED
    assert (disbursement_a.gross_amount, disbursement_a.commission_fee_amount, disbursement_a.disbursed_amount) == (
        Decimal("533.21"),
        Decimal("4.63"),
        Decimal("528.58"),
    )
    assert disbursement_a.error == ""
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert disbursement_b.status == Disbursement.Status.FAILED
    assert reason in disbursement_b.error
    # Retrying does not help until someone fixes the data.
    assert disbursement_b.is_retryable is False
    assert (disbursement_b.gross_amount, disbursement_b.commission_fee_amount, disbursement_b.disbursed_amount) == (None, None, None)
    package.refresh_from_db()
    assert package.status == Status.FAILED


def test_reprocessing_only_touches_what_is_not_completed(package):
    # Commission greater than the gross amount: disbursement_b fails because of data.
    Order.objects.filter(merchant__reference="b_merchant").update(commission_fee="20.00")
    process_disbursement_package(package.id)
    a_before = disbursements_snapshot(package)[0]
    # Someone fixes the data and sends it to reprocess.
    Order.objects.filter(merchant__reference="b_merchant").update(commission_fee="0.11")

    processed = process_disbursement_package(package.id)

    assert processed is True
    package.refresh_from_db()
    assert package.status == Status.COMPLETED
    assert package.attempts == 2
    # disbursement_a is not touched again.
    assert disbursements_snapshot(package)[0] == a_before
    # disbursement_b gives the same as if it had been processed fine from the start.
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert disbursement_b.status == Disbursement.Status.COMPLETED
    assert disbursement_b.error == ""
    assert (disbursement_b.gross_amount, disbursement_b.commission_fee_amount, disbursement_b.disbursed_amount) == (
        Decimal("10.50"),
        Decimal("0.11"),
        Decimal("10.39"),
    )


def sleep_in_db(*args):
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_sleep(2)")


def test_query_slower_than_the_statement_timeout_fails_the_package_as_retryable(package, settings):
    # A hung query: Postgres cuts it after PACKAGE_STATEMENT_TIMEOUT_SECONDS.
    settings.PACKAGE_STATEMENT_TIMEOUT_SECONDS = 1
    with mock.patch(f"{SERVICE}.aggregate_package_totals", side_effect=sleep_in_db):
        process_disbursement_package(package.id)

    package.refresh_from_db()
    assert package.status == Status.FAILED
    for disbursement in Disbursement.objects.filter(package=package):
        assert disbursement.status == Disbursement.Status.FAILED
        assert disbursement.is_retryable is True
        assert "statement timeout" in disbursement.error
