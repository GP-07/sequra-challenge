"""check_package_status and release_stuck_packages: manual commands to follow the packages."""

from datetime import date, timedelta

import pytest
from django.core.management import CommandError
from django.utils import timezone

from core.tests.helpers import run_command
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status


def package_paid_on(payment_date, status, reference):
    merchant = MerchantFactory(reference=reference)
    disbursement = DisbursementFactory(
        merchant=merchant,
        payment_date=payment_date,
        orders=[OrderFactory(merchant=merchant, order_creation_date=payment_date - timedelta(days=1))],
    )
    return DisbursementPackageFactory(disbursements=[disbursement], status=status)


@pytest.fixture
def packages():
    return {
        "completed": package_paid_on(date(2023, 2, 2), Status.COMPLETED, "a_merchant"),
        "failed": package_paid_on(date(2023, 2, 3), Status.FAILED, "b_merchant"),
        "processing": package_paid_on(date(2023, 2, 3), Status.PROCESSING, "c_merchant"),
        # Outside the 2/2 - 2/3 range.
        "pending": package_paid_on(date(2023, 2, 4), Status.PENDING, "d_merchant"),
    }


def test_status_by_ids(packages):
    ids = [str(packages[name].id) for name in ("completed", "failed", "pending")] + ["999999"]

    output = run_command("check_package_status", *ids)

    assert output.splitlines() == [
        "Packages: 4",
        "Pending: 1",
        "Processing: 0",
        "Completed: 1",
        "Failed: 1",
        "Not found: 1",
        f"  failed: {packages['failed'].id}",
        "  not found: 999999",
    ]


def test_status_by_payment_dates_of_a_backfill(packages):
    output = run_command("check_package_status", "--from", "2023-02-02", "--to", "2023-02-03")

    assert output.splitlines() == [
        "Packages: 3",
        "Pending: 0",
        "Processing: 1",
        "Completed: 1",
        "Failed: 1",
        f"  failed: {packages['failed'].id}",
        f"  processing: {packages['processing'].id}",
    ]


@pytest.mark.parametrize(
    "args",
    (
        (),
        ("1", "--from", "2023-02-02", "--to", "2023-02-03"),
        ("--from", "2023-02-02"),
        ("--from", "02/02/2023", "--to", "2023-02-03"),
    ),
)
def test_status_rejects_invalid_arguments(args):
    with pytest.raises(CommandError):
        run_command("check_package_status", *args)


def test_release_command_reports_what_it_did(settings, packages):
    settings.PACKAGE_STUCK_AFTER_MINUTES = 5
    stuck = packages["processing"]
    DisbursementPackage.objects.filter(id=stuck.id).update(updated_at=timezone.now() - timedelta(minutes=10))

    output = run_command("release_stuck_packages", str(stuck.id), str(packages["completed"].id))

    stuck.refresh_from_db()
    assert stuck.status == Status.FAILED
    assert output.splitlines() == [
        "Released (now FAILED, retryable): 1",
        "Still being processed by a worker: 0",
        "In PROCESSING for less than 5 minutes: 0",
        "Not in PROCESSING: 1",
        "Not found: 0",
        f"  released: {stuck.id}",
        f"  not in PROCESSING: {packages['completed'].id} (COMPLETED)",
        "Retry them with retry_disbursement_package.",
    ]
