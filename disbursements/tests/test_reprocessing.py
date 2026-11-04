"""reprocess_disbursements: manual reprocess of disbursements by id.

It only processes the requested ids; the COMPLETED ones are skipped and reported.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.db import OperationalError

from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_processing import process_disbursement_package
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.services.reprocessing import reprocess_disbursements
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.models import Order
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status
PAYMENT_DATE = date(2023, 2, 8)
ORDERS_DATE = date(2023, 2, 7)
SERVICE = "disbursement_packages.services.package_processing"


def disbursement_with_one_order(reference, amount, commission_fee):
    merchant = MerchantFactory(reference=reference)
    order = OrderFactory(merchant=merchant, order_creation_date=ORDERS_DATE, amount=amount, commission_fee=commission_fee)
    return DisbursementFactory(merchant=merchant, payment_date=PAYMENT_DATE, orders=[order])


def disbursement_state(disbursement_id):
    return Disbursement.objects.filter(id=disbursement_id).values(
        "status", "error", "gross_amount", "commission_fee_amount", "disbursed_amount", "updated_at"
    ).get()


def amounts(disbursement):
    return (disbursement.gross_amount, disbursement.commission_fee_amount, disbursement.disbursed_amount)


@pytest.fixture
def failed_package():
    """Processed package with disbursement_a COMPLETED, and disbursement_b and disbursement_c FAILED because of commissions greater than the gross amount, already fixed."""
    disbursement_a = disbursement_with_one_order("a_merchant", "100.00", "0.95")
    disbursement_b = disbursement_with_one_order("b_merchant", "10.50", "0.11")
    disbursement_c = disbursement_with_one_order("c_merchant", "433.21", "3.68")
    package = DisbursementPackageFactory(disbursements=[disbursement_a, disbursement_b, disbursement_c])
    Order.objects.filter(disbursement_id__in=[disbursement_b.id, disbursement_c.id]).update(commission_fee="999.00")
    process_disbursement_package(package.id)
    # Someone fixes the data of disbursement_b and disbursement_c.
    Order.objects.filter(disbursement_id=disbursement_b.id).update(commission_fee="0.11")
    Order.objects.filter(disbursement_id=disbursement_c.id).update(commission_fee="3.68")
    return package


def test_reprocesses_only_the_given_disbursements(failed_package):
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    disbursement_c = Disbursement.objects.get(merchant__reference="c_merchant")
    disbursement_c_before = disbursement_state(disbursement_c.id)

    result = reprocess_disbursements([disbursement_b.id])

    assert result.processed == [disbursement_b.id]
    assert result.skipped_completed == []
    assert result.skipped_in_progress == []
    assert result.not_found == []
    disbursement_b.refresh_from_db()
    assert disbursement_b.status == Disbursement.Status.COMPLETED
    assert disbursement_b.error == ""
    assert amounts(disbursement_b) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    # disbursement_c was not requested: it stays FAILED as it was.
    assert disbursement_state(disbursement_c.id) == disbursement_c_before
    # The package still has disbursement_c FAILED.
    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    assert failed_package.attempts == 2


def test_package_is_completed_when_its_last_failed_disbursement_is_reprocessed(failed_package):
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    disbursement_c = Disbursement.objects.get(merchant__reference="c_merchant")

    result = reprocess_disbursements([disbursement_b.id, disbursement_c.id])

    assert sorted(result.processed) == sorted([disbursement_b.id, disbursement_c.id])
    disbursement_c.refresh_from_db()
    assert disbursement_c.status == Disbursement.Status.COMPLETED
    assert disbursement_c.error == ""
    assert amounts(disbursement_c) == (Decimal("433.21"), Decimal("3.68"), Decimal("429.53"))
    failed_package.refresh_from_db()
    assert failed_package.status == Status.COMPLETED
    assert failed_package.attempts == 2
    assert not Disbursement.objects.exclude(status=Disbursement.Status.COMPLETED).exists()


def test_completed_disbursements_are_skipped_and_reported(failed_package):
    disbursement_a = Disbursement.objects.get(merchant__reference="a_merchant")
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    a_before = disbursement_state(disbursement_a.id)

    result = reprocess_disbursements([disbursement_a.id, disbursement_b.id])

    assert result.processed == [disbursement_b.id]
    assert result.skipped_completed == [disbursement_a.id]
    assert disbursement_state(disbursement_a.id) == a_before


def test_only_completed_disbursements_do_not_touch_the_package(failed_package):
    disbursement_a = Disbursement.objects.get(merchant__reference="a_merchant")

    result = reprocess_disbursements([disbursement_a.id])

    assert result.processed == []
    assert result.skipped_completed == [disbursement_a.id]
    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    # The package was not taken: it does not count as an attempt.
    assert failed_package.attempts == 1


def test_unknown_ids_are_reported(failed_package):
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")

    result = reprocess_disbursements([disbursement_b.id, 999999])

    assert result.processed == [disbursement_b.id]
    assert result.not_found == [999999]


def test_disbursements_of_a_package_in_progress_are_skipped_and_reported(failed_package):
    # Another worker has taken the package.
    DisbursementPackage.objects.filter(id=failed_package.id).update(status=Status.PROCESSING)
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    b_before = disbursement_state(disbursement_b.id)

    result = reprocess_disbursements([disbursement_b.id])

    assert result.processed == []
    assert result.skipped_in_progress == [disbursement_b.id]
    assert disbursement_state(disbursement_b.id) == b_before


def test_disbursements_of_different_packages_are_reprocessed_in_their_own_package(failed_package):
    other = disbursement_with_one_order("d_merchant", "50.00", "0.48")
    other_package = DisbursementPackageFactory(disbursements=[other])
    Order.objects.filter(disbursement_id=other.id).update(commission_fee="999.00")
    process_disbursement_package(other_package.id)
    Order.objects.filter(disbursement_id=other.id).update(commission_fee="0.48")
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")

    result = reprocess_disbursements([disbursement_b.id, other.id])

    assert sorted(result.processed) == sorted([disbursement_b.id, other.id])
    other.refresh_from_db()
    assert other.status == Disbursement.Status.COMPLETED
    assert other.package_id == other_package.id
    assert amounts(other) == (Decimal("50.00"), Decimal("0.48"), Decimal("49.52"))
    disbursement_b.refresh_from_db()
    assert disbursement_b.status == Disbursement.Status.COMPLETED
    assert disbursement_b.package_id == failed_package.id
    other_package.refresh_from_db()
    assert other_package.status == Status.COMPLETED
    # failed_package still has disbursement_c FAILED.
    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED


@pytest.mark.parametrize(
    "error, retryable",
    [
        # Infrastructure: retrying may help, even if the package comes from a data failure.
        (OperationalError("deadlock detected"), True),
        (TimeoutError("timeout"), True),
        # Unexpected (a bug): retrying does not help.
        (ValueError("invalid data"), False),
    ],
)
def test_error_during_reprocess_sets_is_retryable_by_its_type(failed_package, error, retryable):
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")

    with mock.patch(f"{SERVICE}.save_disbursement_results", side_effect=error):
        reprocess_disbursements([disbursement_b.id])

    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    assert failed_package.attempts == 2
    disbursement_b.refresh_from_db()
    assert disbursement_b.status == Disbursement.Status.FAILED
    assert disbursement_b.is_retryable is retryable
    assert str(error) in disbursement_b.error
    assert amounts(disbursement_b) == (None, None, None)


def test_data_failure_during_reprocess_is_not_retryable(failed_package):
    # disbursement_b is reprocessed without anyone fixing the data.
    disbursement_b = Disbursement.objects.get(merchant__reference="b_merchant")
    Order.objects.filter(disbursement_id=disbursement_b.id).update(commission_fee="999.00")

    reprocess_disbursements([disbursement_b.id])

    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    assert failed_package.attempts == 2
    disbursement_b.refresh_from_db()
    assert disbursement_b.status == Disbursement.Status.FAILED
    assert disbursement_b.is_retryable is False
    assert "greater than the gross amount" in disbursement_b.error
    assert amounts(disbursement_b) == (None, None, None)


def test_disbursements_without_package_are_skipped_and_reported():
    # PENDING without a package: the normal flow takes it.
    pending = disbursement_with_one_order("e_merchant", "10.50", "0.11")
    pending_before = disbursement_state(pending.id)

    result = reprocess_disbursements([pending.id])

    assert result.processed == []
    assert result.skipped_without_package == [pending.id]
    assert disbursement_state(pending.id) == pending_before
    assert not DisbursementPackage.objects.exists()
