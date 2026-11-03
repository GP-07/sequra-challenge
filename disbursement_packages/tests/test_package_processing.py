"""process_disbursement_package: toma atómica del paquete y resultado por disbursement.

- Falla de datos (un disbursement inválido): los demás quedan COMPLETED con sus totales.
- Falla de infraestructura o inesperada: se revierte todo y no queda nada a medias.
- Reprocesar solo toca lo que no está COMPLETED.
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
    a = Disbursement.objects.get(merchant__reference="a_merchant")
    assert a.status == Disbursement.Status.COMPLETED
    assert a.gross_amount == Decimal("533.21")
    assert a.commission_fee_amount == Decimal("4.63")
    # Las comisiones se restan del bruto.
    assert a.disbursed_amount == Decimal("528.58")
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert b.status == Disbursement.Status.COMPLETED
    assert (b.gross_amount, b.commission_fee_amount, b.disbursed_amount) == (
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
    # No toca los disbursements: quedan como estaban, tengan o no totales.
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
    # Al completarse se limpia el error de la corrida anterior.
    assert list(Disbursement.objects.values_list("error", "is_retryable").distinct()) == [("", None)]


@pytest.mark.parametrize(
    "error, retryable",
    [
        # Infraestructura: reintentar puede servir.
        (OperationalError("deadlock detected"), True),
        (TimeoutError("timeout"), True),
        # Inesperado (un bug): reintentar no sirve.
        (ValueError("invalid data"), False),
    ],
)
def test_unexpected_error_rolls_back_and_fails_package_and_disbursements(package, error, retryable):
    # Falla al guardar: confiamos en transaction.atomic para que no quede nada escrito.
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


def test_invalid_disbursement_does_not_undo_the_others(package):
    # b dice tener 3 orders pero tiene 1 asignada.
    Disbursement.objects.filter(merchant__reference="b_merchant").update(order_count=3)

    process_disbursement_package(package.id)

    package.refresh_from_db()
    assert package.status == Status.FAILED
    a = Disbursement.objects.get(merchant__reference="a_merchant")
    assert a.status == Disbursement.Status.COMPLETED
    assert (a.gross_amount, a.commission_fee_amount, a.disbursed_amount) == (
        Decimal("533.21"),
        Decimal("4.63"),
        Decimal("528.58"),
    )
    assert a.error == ""
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert b.status == Disbursement.Status.FAILED
    assert "3" in b.error
    # Reintentar no sirve hasta que alguien corrija los datos.
    assert b.is_retryable is False
    assert (b.gross_amount, b.commission_fee_amount, b.disbursed_amount) == (None, None, None)


@pytest.mark.parametrize(
    "amount, commission_fee, reason",
    [
        # Un dato corregido a mano que dejó la order con monto negativo.
        ("-10.50", "0.11", "Negative amounts"),
        # Comisiones mayores al bruto: se pagaría un monto negativo.
        ("10.50", "20.00", "greater than the gross amount"),
    ],
)
def test_disbursement_with_invalid_amounts_fails_and_does_not_undo_the_others(package, amount, commission_fee, reason):
    Order.objects.filter(merchant__reference="b_merchant").update(amount=amount, commission_fee=commission_fee)

    process_disbursement_package(package.id)

    a = Disbursement.objects.get(merchant__reference="a_merchant")
    assert a.status == Disbursement.Status.COMPLETED
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert b.status == Disbursement.Status.FAILED
    assert reason in b.error
    assert b.is_retryable is False
    assert (b.gross_amount, b.commission_fee_amount, b.disbursed_amount) == (None, None, None)
    package.refresh_from_db()
    assert package.status == Status.FAILED


def test_reprocessing_only_touches_what_is_not_completed(package):
    Disbursement.objects.filter(merchant__reference="b_merchant").update(order_count=3)
    process_disbursement_package(package.id)
    a_before = disbursements_snapshot(package)[0]
    # Alguien corrige el dato y manda a reprocesar.
    Disbursement.objects.filter(merchant__reference="b_merchant").update(order_count=1)

    processed = process_disbursement_package(package.id)

    assert processed is True
    package.refresh_from_db()
    assert package.status == Status.COMPLETED
    assert package.attempts == 2
    # a no se vuelve a tocar.
    assert disbursements_snapshot(package)[0] == a_before
    # b da lo mismo que si se hubiera procesado bien de entrada.
    b = Disbursement.objects.get(merchant__reference="b_merchant")
    assert b.status == Disbursement.Status.COMPLETED
    assert b.error == ""
    assert (b.gross_amount, b.commission_fee_amount, b.disbursed_amount) == (
        Decimal("10.50"),
        Decimal("0.11"),
        Decimal("10.39"),
    )
