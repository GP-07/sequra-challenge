"""retry_disbursement_package: reprocesses a whole package by hand."""

from datetime import date

import pytest
from django.core.management import CommandError

from core.tests.helpers import run_command
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db


def test_retry_reprocesses_a_non_retryable_package_after_fixing_the_data():
    # This is how a package ends up after a data failure: FAILED not retryable, because retrying
    # automatically does not help. Someone already fixed the data (the commission no longer exceeds the
    # gross amount) and reprocesses it by hand: the manual retry does not look at is_retryable.
    merchant = MerchantFactory(reference="padberg_group")
    order = OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 7))
    disbursement = DisbursementFactory(
        merchant=merchant,
        payment_date=date(2023, 2, 8),
        orders=[order],
        status=Disbursement.Status.FAILED,
        error="Commission fees 20.00 are greater than the gross amount 10.50.",
        is_retryable=False,
    )
    package = DisbursementPackageFactory(disbursements=[disbursement], status=DisbursementPackage.Status.FAILED, attempts=1)

    run_command("retry_disbursement_package", str(package.id))

    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    disbursement.refresh_from_db()
    assert disbursement.status == Disbursement.Status.COMPLETED
    assert disbursement.error == ""
    assert disbursement.is_retryable is None


def test_retry_unknown_package():
    with pytest.raises(CommandError):
        run_command("retry_disbursement_package", "999999")


def test_retry_completed_package_is_skipped_and_reported():
    merchant = MerchantFactory(reference="padberg_group")
    order = OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 7))
    disbursement = DisbursementFactory(
        merchant=merchant, payment_date=date(2023, 2, 8), orders=[order], status=Disbursement.Status.COMPLETED
    )
    package = DisbursementPackageFactory(
        disbursements=[disbursement], status=DisbursementPackage.Status.COMPLETED, attempts=1
    )

    output = run_command("retry_disbursement_package", str(package.id))

    assert "already completed" in output.lower()
    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.attempts == 1
