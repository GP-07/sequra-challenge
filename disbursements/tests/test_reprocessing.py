"""reprocess_disbursements: reprocess manual de disbursements por id.

Solo procesa los ids pedidos; los COMPLETED se saltean y se informan.
"""

from datetime import date
from decimal import Decimal
from unittest import mock

import pytest
from django.db import OperationalError

from disbursements.models import Disbursement, DisbursementPackage
from disbursements.services.package_processing import process_disbursement_package
from disbursements.services.reprocessing import reprocess_disbursements
from disbursements.tests.factories import DisbursementFactory, DisbursementPackageFactory, MerchantFactory, OrderFactory

pytestmark = pytest.mark.django_db

Status = DisbursementPackage.Status
PAYMENT_DATE = date(2023, 2, 8)
ORDERS_DATE = date(2023, 2, 7)
SERVICE = "disbursements.services.package_processing"


def disbursement_with_one_order(reference, amount, commission_fee):
    merchant = MerchantFactory(reference=reference)
    order = OrderFactory(merchant=merchant, created_at=ORDERS_DATE, amount=amount, commission_fee=commission_fee)
    return DisbursementFactory(merchant=merchant, payment_date=PAYMENT_DATE, orders=[order])


def disbursement_state(disbursement_id):
    return Disbursement.objects.filter(id=disbursement_id).values(
        "status", "error", "gross_amount", "commission_fee_amount", "disbursed_amount", "updated_at"
    ).get()


def amounts(disbursement):
    return (disbursement.gross_amount, disbursement.commission_fee_amount, disbursement.disbursed_amount)


@pytest.fixture
def failed_package():
    """Paquete procesado con a COMPLETED y b y c FAILED por un dato inconsistente, ya corregido."""
    a = disbursement_with_one_order("a_merchant", "100.00", "0.95")
    b = disbursement_with_one_order("b_merchant", "10.50", "0.11")
    c = disbursement_with_one_order("c_merchant", "433.21", "3.68")
    package = DisbursementPackageFactory(disbursements=[a, b, c])
    Disbursement.objects.filter(id__in=[b.id, c.id]).update(order_count=3)
    process_disbursement_package(package.id)
    # Alguien corrige los datos de b y c.
    Disbursement.objects.filter(id__in=[b.id, c.id]).update(order_count=1)
    return package


def test_reprocesses_only_the_given_disbursements(failed_package):
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    c = Disbursement.objects.get(merchant__reference="c_merchant")
    c_before = disbursement_state(c.id)

    result = reprocess_disbursements([b.id])

    assert result.processed == [b.id]
    assert result.skipped_completed == []
    assert result.skipped_in_progress == []
    assert result.not_found == []
    b.refresh_from_db()
    assert b.status == Disbursement.Status.COMPLETED
    assert b.error == ""
    assert amounts(b) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    # c no se pidió: queda FAILED como estaba.
    assert disbursement_state(c.id) == c_before
    # Al paquete le queda c FAILED. Esta corrida no tuvo errores: mantiene el is_retryable que tenía
    # (False, por la falla de datos de c).
    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    assert failed_package.is_retryable is False
    assert failed_package.attempts == 2


def test_package_is_completed_when_its_last_failed_disbursement_is_reprocessed(failed_package):
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    c = Disbursement.objects.get(merchant__reference="c_merchant")

    result = reprocess_disbursements([b.id, c.id])

    assert sorted(result.processed) == sorted([b.id, c.id])
    c.refresh_from_db()
    assert c.status == Disbursement.Status.COMPLETED
    assert c.error == ""
    assert amounts(c) == (Decimal("433.21"), Decimal("3.68"), Decimal("429.53"))
    failed_package.refresh_from_db()
    assert failed_package.status == Status.COMPLETED
    assert failed_package.attempts == 2
    assert not Disbursement.objects.exclude(status=Disbursement.Status.COMPLETED).exists()


def test_completed_disbursements_are_skipped_and_reported(failed_package):
    a = Disbursement.objects.get(merchant__reference="a_merchant")
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    a_before = disbursement_state(a.id)

    result = reprocess_disbursements([a.id, b.id])

    assert result.processed == [b.id]
    assert result.skipped_completed == [a.id]
    assert disbursement_state(a.id) == a_before


def test_only_completed_disbursements_do_not_touch_the_package(failed_package):
    a = Disbursement.objects.get(merchant__reference="a_merchant")

    result = reprocess_disbursements([a.id])

    assert result.processed == []
    assert result.skipped_completed == [a.id]
    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    # No se tomó el paquete: no cuenta como intento.
    assert failed_package.attempts == 1


def test_unknown_ids_are_reported(failed_package):
    b = Disbursement.objects.get(merchant__reference="b_merchant")

    result = reprocess_disbursements([b.id, 999999])

    assert result.processed == [b.id]
    assert result.not_found == [999999]


def test_disbursements_of_a_package_in_progress_are_skipped_and_reported(failed_package):
    # Otro worker tiene el paquete tomado.
    DisbursementPackage.objects.filter(id=failed_package.id).update(status=Status.PROCESSING)
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    b_before = disbursement_state(b.id)

    result = reprocess_disbursements([b.id])

    assert result.processed == []
    assert result.skipped_in_progress == [b.id]
    assert disbursement_state(b.id) == b_before


def test_disbursements_of_different_packages_are_reprocessed_in_their_own_package(failed_package):
    other = disbursement_with_one_order("d_merchant", "50.00", "0.48")
    other_package = DisbursementPackageFactory(disbursements=[other])
    Disbursement.objects.filter(id=other.id).update(order_count=2)
    process_disbursement_package(other_package.id)
    Disbursement.objects.filter(id=other.id).update(order_count=1)
    b = Disbursement.objects.get(merchant__reference="b_merchant")

    result = reprocess_disbursements([b.id, other.id])

    assert sorted(result.processed) == sorted([b.id, other.id])
    other.refresh_from_db()
    assert other.status == Disbursement.Status.COMPLETED
    assert other.package_id == other_package.id
    assert amounts(other) == (Decimal("50.00"), Decimal("0.48"), Decimal("49.52"))
    b.refresh_from_db()
    assert b.status == Disbursement.Status.COMPLETED
    assert b.package_id == failed_package.id
    other_package.refresh_from_db()
    assert other_package.status == Status.COMPLETED
    # failed_package todavía tiene a c FAILED.
    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED


@pytest.mark.parametrize(
    "error, retryable",
    [
        # Infraestructura: reintentar puede servir, aunque el paquete venga de una falla de datos.
        (OperationalError("deadlock detected"), True),
        (TimeoutError("timeout"), True),
        # Inesperado (un bug): reintentar no sirve.
        (ValueError("invalid data"), False),
    ],
)
def test_error_during_reprocess_sets_is_retryable_by_its_type(failed_package, error, retryable):
    b = Disbursement.objects.get(merchant__reference="b_merchant")

    with mock.patch(f"{SERVICE}.save_disbursement_results", side_effect=error):
        reprocess_disbursements([b.id])

    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    assert failed_package.is_retryable is retryable
    assert str(error) in failed_package.error
    assert failed_package.attempts == 2
    b.refresh_from_db()
    assert b.status == Disbursement.Status.FAILED
    assert str(error) in b.error
    assert amounts(b) == (None, None, None)


def test_data_failure_during_reprocess_is_not_retryable(failed_package):
    # Se reprocesa b sin que nadie haya corregido el dato.
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    Disbursement.objects.filter(id=b.id).update(order_count=3)

    reprocess_disbursements([b.id])

    failed_package.refresh_from_db()
    assert failed_package.status == Status.FAILED
    assert failed_package.is_retryable is False
    assert failed_package.attempts == 2
    b.refresh_from_db()
    assert b.status == Disbursement.Status.FAILED
    assert "3" in b.error
    assert amounts(b) == (None, None, None)


def test_disbursements_without_package_are_skipped_and_reported():
    # PENDING sin empaquetar: lo toma el flujo normal.
    pending = disbursement_with_one_order("e_merchant", "10.50", "0.11")
    pending_before = disbursement_state(pending.id)

    result = reprocess_disbursements([pending.id])

    assert result.processed == []
    assert result.skipped_without_package == [pending.id]
    assert disbursement_state(pending.id) == pending_before
    assert not DisbursementPackage.objects.exists()
