"""check_disbursement_packages: corre en varios horarios y decide por estado de cada paquete.

- COMPLETED, FAILED no retryable y FAILED en el último horario son finales.
- Solo FAILED retryable (con reintentos disponibles y antes del último horario) consulta
  el umbral de % de paquetes FAILED del día: si lo supera, alerta CRITICAL y no re-encola.
"""

import logging
from datetime import date, datetime, timezone

import pytest

from disbursements.models import DisbursementPackage
from disbursements.services.package_checks import check_disbursement_packages
from disbursements.tests.factories import DisbursementPackageFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status
RUN_DATE = date(2023, 2, 8)


def package_of(status, run_date=RUN_DATE, **fields):
    package = DisbursementPackageFactory(status=status, **fields)
    # created_at es auto_now_add: se pisa después de crear el paquete.
    DisbursementPackage.objects.filter(id=package.id).update(
        created_at=datetime(run_date.year, run_date.month, run_date.day, 0, 10, tzinfo=timezone.utc)
    )
    return package


@pytest.fixture(autouse=True)
def default_settings(settings):
    settings.PACKAGE_MAX_RETRIES = 1
    settings.PACKAGE_FAILURE_THRESHOLD_PERCENT = 80


def levels(caplog):
    return [r.levelno for r in caplog.records if r.name == "disbursements.alerts"]


def test_completed_packages_need_nothing(caplog):
    package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == []


def test_retryable_failure_is_retried():
    failed = package_of(Status.FAILED, is_retryable=True, attempts=1)
    for _ in range(4):
        package_of(Status.COMPLETED)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [failed.id]


def test_non_retryable_failure_alerts_and_is_not_retried(caplog):
    package_of(Status.FAILED, is_retryable=False, attempts=1)
    package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == [logging.ERROR]


def test_failure_on_the_last_run_is_critical_and_not_retried(caplog):
    package_of(Status.FAILED, is_retryable=True, attempts=1)
    for _ in range(4):
        package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=True)

    assert result.to_retry == []
    assert levels(caplog) == [logging.CRITICAL]


def test_retryable_failure_without_retries_left_is_not_retried():
    # attempts cuenta ejecuciones: 1 original + PACKAGE_MAX_RETRIES reintentos.
    package_of(Status.FAILED, is_retryable=True, attempts=2)
    for _ in range(4):
        package_of(Status.COMPLETED)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []


def test_failures_above_threshold_are_critical_and_not_retried(caplog):
    # 5 de 5 FAILED: 100% supera el 80%.
    for _ in range(5):
        package_of(Status.FAILED, is_retryable=True, attempts=1)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert logging.CRITICAL in levels(caplog)


def test_failures_at_the_threshold_are_still_retried():
    # 4 de 5 FAILED: 80% no supera el umbral.
    retryable = [package_of(Status.FAILED, is_retryable=True, attempts=1) for _ in range(4)]
    package_of(Status.COMPLETED)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert sorted(result.to_retry) == sorted(p.id for p in retryable)


def test_only_packages_of_the_run_date_are_checked():
    package_of(Status.FAILED, run_date=date(2023, 2, 7), is_retryable=True, attempts=1)
    of_the_run_date = package_of(Status.FAILED, is_retryable=True, attempts=1)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [of_the_run_date.id]


def test_pending_and_processing_packages_are_left_to_the_timeout_control(caplog):
    package_of(Status.PENDING)
    package_of(Status.PROCESSING)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == []
