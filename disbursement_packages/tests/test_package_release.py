"""release_stuck_packages: libera los paquetes trabados en PROCESSING sin tocar los que un worker procesa."""

import threading
from datetime import date, timedelta
from unittest import mock

import pytest
from django.db import connection
from django.utils import timezone

from disbursement_packages.constants import STUCK_PACKAGE_ERROR
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_processing import process_disbursement_package
from disbursement_packages.services.package_release import release_stuck_packages
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.tests.factories import OrderFactory

Status = DisbursementPackage.Status
SERVICE = "disbursement_packages.services.package_processing"

PROCESSING_STARTED = threading.Event()
LET_PROCESSING_FINISH = threading.Event()


def package_with(status, minutes_in_status):
    """Paquete con un disbursement COMPLETED y otro PENDING, en `status` desde hace `minutes_in_status`."""
    disbursements = []
    for reference, disbursement_status in (("a_merchant", Disbursement.Status.COMPLETED), ("b_merchant", Disbursement.Status.PENDING)):
        merchant = MerchantFactory(reference=reference)
        disbursements.append(
            DisbursementFactory(
                merchant=merchant,
                payment_date=date(2023, 2, 8),
                orders=[OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 7))],
                status=disbursement_status,
            )
        )
    package = DisbursementPackageFactory(disbursements=disbursements, status=status, attempts=1)
    DisbursementPackage.objects.filter(id=package.id).update(updated_at=timezone.now() - timedelta(minutes=minutes_in_status))
    return package


def block_while_processing(*args):
    PROCESSING_STARTED.set()
    LET_PROCESSING_FINISH.wait(10)
    return {}


def process_in_another_worker(package_id):
    try:
        process_disbursement_package(package_id)
    finally:
        connection.close()


@pytest.mark.django_db
def test_stuck_package_is_released_with_its_unfinished_disbursements_failed_and_retryable(settings):
    # Nadie tiene el lock: el worker que lo tomaba murió.
    settings.PACKAGE_STUCK_AFTER_MINUTES = 5
    package = package_with(Status.PROCESSING, minutes_in_status=10)

    result = release_stuck_packages([package.id])

    assert result.released == [package.id]
    assert (result.being_processed, result.too_recent, result.not_processing, result.not_found) == ([], [], [], [])
    package.refresh_from_db()
    assert package.status == Status.FAILED
    assert package.attempts == 1
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert (b.status, b.is_retryable, b.error) == (Disbursement.Status.FAILED, True, STUCK_PACKAGE_ERROR)
    # Lo que ya estaba COMPLETED no se toca.
    a = Disbursement.objects.get(merchant__reference="a_merchant")
    assert (a.status, a.error) == (Disbursement.Status.COMPLETED, "")


@pytest.mark.django_db
def test_recent_processing_package_is_not_released(settings):
    settings.PACKAGE_STUCK_AFTER_MINUTES = 5
    package = package_with(Status.PROCESSING, minutes_in_status=1)

    result = release_stuck_packages([package.id])

    assert result.too_recent == [package.id]
    assert result.released == []
    package.refresh_from_db()
    assert package.status == Status.PROCESSING


@pytest.mark.django_db
def test_packages_not_in_processing_or_unknown_are_reported_and_left_alone():
    completed = package_with(Status.COMPLETED, minutes_in_status=60)

    result = release_stuck_packages([completed.id, 999999])

    assert result.not_processing == [(completed.id, Status.COMPLETED)]
    assert result.not_found == [999999]
    assert result.released == []
    completed.refresh_from_db()
    assert completed.status == Status.COMPLETED


@pytest.mark.django_db(transaction=True)
def test_package_a_live_worker_is_processing_is_never_released(settings):
    # Concurrencia real: otro worker (otro thread, otra conexión) está en plena transacción de
    # procesamiento, con el lock del paquete tomado. Con 0 minutos, solo el lock lo protege.
    settings.PACKAGE_STUCK_AFTER_MINUTES = 0
    package = package_with(Status.PENDING, minutes_in_status=0)
    PROCESSING_STARTED.clear()
    LET_PROCESSING_FINISH.clear()
    with mock.patch(f"{SERVICE}.aggregate_package_totals", side_effect=block_while_processing):
        worker = threading.Thread(target=process_in_another_worker, args=(package.id,))
        worker.start()
        assert PROCESSING_STARTED.wait(5)

        result = release_stuck_packages([package.id])

        LET_PROCESSING_FINISH.set()
        worker.join(10)

    assert result.being_processed == [package.id]
    assert result.released == []
    assert not Disbursement.objects.filter(error=STUCK_PACKAGE_ERROR).exists()
