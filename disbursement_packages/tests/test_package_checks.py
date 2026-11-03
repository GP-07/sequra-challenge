"""check_disbursement_packages: corre en varios horarios y decide por los disbursements FAILED del día.

- COMPLETED, FAILED no retryable y FAILED en el último horario son finales.
- Solo FAILED retryable (con reintentos disponibles y antes del último horario) consulta
  el umbral de % de disbursements FAILED del día: si lo supera, alerta CRITICAL y no re-encola.

Cada paquete de estos tests tiene un solo disbursement, con la fecha de pago del día que se controla.
"""

import logging
from datetime import date

import pytest

from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_checks import check_disbursement_packages
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.tests.factories import DisbursementFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status
RUN_DATE = date(2023, 2, 8)


# Status del disbursement según cómo terminó su paquete.
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
    failed = package_of(Status.FAILED, is_retryable=True)
    for _ in range(4):
        package_of(Status.COMPLETED)

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
    for _ in range(4):
        package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=True)

    assert result.to_retry == []
    assert levels(caplog) == [logging.CRITICAL]


def test_retryable_failure_without_retries_left_is_critical_and_not_retried(caplog):
    # attempts cuenta ejecuciones: 1 original + PACKAGE_MAX_RETRIES reintentos.
    package_of(Status.FAILED, is_retryable=True, attempts=2)
    for _ in range(4):
        package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == [logging.CRITICAL]


def test_failures_above_threshold_are_critical_and_not_retried(caplog):
    # 5 de 5 disbursements FAILED: 100% supera el 80%.
    for _ in range(5):
        package_of(Status.FAILED, is_retryable=True)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert logging.CRITICAL in levels(caplog)


def test_failures_at_the_threshold_are_still_retried():
    # 4 de 5 disbursements FAILED: 80% no supera el umbral.
    retryable = [package_of(Status.FAILED, is_retryable=True) for _ in range(4)]
    package_of(Status.COMPLETED)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert sorted(result.to_retry) == sorted(p.id for p in retryable)


def test_only_packages_of_the_run_date_are_checked():
    package_of(Status.FAILED, payment_date=date(2023, 2, 7), is_retryable=True)
    of_the_run_date = package_of(Status.FAILED, is_retryable=True)
    # Para no superar el umbral: 1 de 5 disbursements del día FAILED.
    for _ in range(4):
        package_of(Status.COMPLETED)

    result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [of_the_run_date.id]


def test_pending_and_processing_packages_are_left_to_the_timeout_control(caplog):
    package_of(Status.PENDING)
    package_of(Status.PROCESSING)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == []
    assert levels(caplog) == []


def test_package_with_retryable_and_non_retryable_failures_alerts_and_is_retried(caplog):
    # Reintentarlo vuelve a procesar ambos: el no retryable falla igual hasta que se corrija.
    retryable = DisbursementFactory(payment_date=RUN_DATE, status=Disbursement.Status.FAILED, is_retryable=True)
    non_retryable = DisbursementFactory(payment_date=RUN_DATE, status=Disbursement.Status.FAILED, is_retryable=False)
    package = DisbursementPackageFactory(disbursements=[retryable, non_retryable], status=Status.FAILED, attempts=1)
    for _ in range(3):
        package_of(Status.COMPLETED)

    with caplog.at_level(logging.INFO):
        result = check_disbursement_packages(RUN_DATE, is_last_run=False)

    assert result.to_retry == [package.id]
    assert levels(caplog) == [logging.ERROR]
