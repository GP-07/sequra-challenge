"""check_disbursement_packages: runs at several hours and decides based on the day's FAILED disbursements.

- COMPLETED, FAILED not retryable and FAILED on the last run are final.
- FAILED retryable with retries left and before the last run: it is retried.
- Before deciding, the day's packages stuck in PROCESSING are released as FAILED retryable.

Each package in these tests has a single disbursement, with the payment date of the checked day.
"""

import logging
from datetime import date, timedelta

import pytest
from django.utils import timezone

from disbursement_packages.constants import STUCK_PACKAGE_ERROR
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_checks import check_disbursement_packages
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.tests.factories import DisbursementFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status
RUN_DATE = date(2023, 2, 8)


# Disbursement status depending on how its package ended.
DISBURSEMENT_STATUS = {
    Status.PENDING: Disbursement.Status.PENDING,
    Status.PROCESSING: Disbursement.Status.PENDING,
    Status.COMPLETED: Disbursement.Status.COMPLETED,
    Status.FAILED: Disbursement.Status.FAILED,
}


def package_of(status, payment_date=RUN_DATE, is_retryable=None, attempts=1):
    disbursement = DisbursementFactory(
        payment_date=payment_date, status=DISBURSEMENT_STATUS[status], is_retryable=is_retryable
    )
    return DisbursementPackageFactory(disbursements=[disbursement], status=status, attempts=attempts)


def stuck_package_of(payment_date=RUN_DATE):
    """Package in PROCESSING for more than PACKAGE_STUCK_AFTER_MINUTES and without a worker holding it."""
    package = package_of(Status.PROCESSING, payment_date=payment_date)
    DisbursementPackage.objects.filter(id=package.id).update(updated_at=timezone.now() - timedelta(minutes=30))
    return package


@pytest.fixture(autouse=True)
def default_settings(settings):
    settings.PACKAGE_MAX_RETRIES = 1


def levels(caplog):
    return [record.levelno for record in caplog.records if record.name == "disbursements.alerts"]


def test_completed_packages_need_nothing(caplog):
    package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == []


def test_retryable_failure_is_retried():
    failed = package_of(Status.FAILED, is_retryable=True)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [failed.id]


def test_non_retryable_failure_alerts_and_is_not_retried(caplog):
    package_of(Status.FAILED, is_retryable=False)
    package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == [logging.ERROR]


def test_failure_on_the_last_run_is_critical_and_not_retried(caplog):
    package_of(Status.FAILED, is_retryable=True)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=True)

    assert result.to_retry == []
    assert levels(caplog) == [logging.CRITICAL]


def test_retryable_failure_without_retries_left_is_critical_and_not_retried(caplog):
    # attempts cuenta ejecuciones: 1 original + PACKAGE_MAX_RETRIES reintentos.
    package_of(Status.FAILED, is_retryable=True, attempts=2)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == [logging.CRITICAL]


def test_all_the_packages_of_the_day_failing_are_retried():
    # The case of a normal day: one or two packages, and all their disbursements fail.
    retryable = [package_of(Status.FAILED, is_retryable=True) for _ in range(2)]

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == sorted(package.id for package in retryable)


def test_only_packages_of_the_run_date_are_checked():
    package_of(Status.FAILED, payment_date=date(2023, 2, 7), is_retryable=True)
    of_the_run_date = package_of(Status.FAILED, is_retryable=True)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [of_the_run_date.id]


def test_pending_and_recently_processing_packages_are_not_touched(caplog):
    pending = package_of(Status.PENDING)
    processing = package_of(Status.PROCESSING)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.released == []
    assert result.to_retry == []
    assert levels(caplog) == []
    assert DisbursementPackage.objects.get(id=pending.id).status == Status.PENDING
    assert DisbursementPackage.objects.get(id=processing.id).status == Status.PROCESSING


def test_stuck_package_is_released_and_retried_in_the_same_run():
    stuck = stuck_package_of()

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.released == [stuck.id]
    assert result.to_retry == [stuck.id]
    assert DisbursementPackage.objects.get(id=stuck.id).status == Status.FAILED
    disbursement = Disbursement.objects.get(package_id=stuck.id)
    assert disbursement.status == Disbursement.Status.FAILED
    assert disbursement.is_retryable is True
    assert disbursement.error == STUCK_PACKAGE_ERROR


def test_stuck_package_released_on_the_last_run_is_critical_and_not_retried(caplog):
    stuck = stuck_package_of()

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=True)

    assert result.released == [stuck.id]
    assert result.to_retry == []
    assert levels(caplog) == [logging.CRITICAL]


def test_stuck_package_of_another_day_is_not_released():
    other_day = stuck_package_of(payment_date=date(2023, 2, 7))

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.released == []
    assert DisbursementPackage.objects.get(id=other_day.id).status == Status.PROCESSING


def test_package_with_retryable_and_non_retryable_failures_alerts_and_is_retried(caplog):
    # Retrying it processes both again: the non-retryable one keeps failing until it is fixed.
    retryable = DisbursementFactory(payment_date=RUN_DATE, status=Disbursement.Status.FAILED, is_retryable=True)
    non_retryable = DisbursementFactory(payment_date=RUN_DATE, status=Disbursement.Status.FAILED, is_retryable=False)
    package = DisbursementPackageFactory(disbursements=[retryable, non_retryable], status=Status.FAILED, attempts=1)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [package.id]
    assert levels(caplog) == [logging.ERROR]
