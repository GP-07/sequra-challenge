"""create_disbursement_packages: arma paquetes de hasta N orders sin partir disbursements."""

import logging
from datetime import date

import pytest

from disbursements.models import Disbursement, DisbursementPackage
from disbursements.services.packages import create_disbursement_packages
from disbursements.tests.factories import DisbursementFactory, DisbursementPackageFactory, OrderFactory
from merchants.tests.factories import MerchantFactory

pytestmark = pytest.mark.django_db

PAYMENT_DATE = date(2023, 2, 8)
ORDERS_DATE = date(2023, 2, 7)


def disbursement_with(reference, order_count, payment_date=PAYMENT_DATE, **fields):
    merchant = MerchantFactory(reference=reference)
    orders = OrderFactory.create_batch(order_count, merchant=merchant, created_at=ORDERS_DATE)
    return DisbursementFactory(merchant=merchant, payment_date=payment_date, orders=orders, **fields)


def test_packs_disbursements_in_a_deterministic_order_without_splitting():
    # Orden determinístico: fecha de pago y reference del merchant.
    # PENDIENTE: revisar si la reference sirve como criterio; si cambia, cambian los paquetes.
    c = disbursement_with("c_merchant", 2)
    a = disbursement_with("a_merchant", 2)
    b = disbursement_with("b_merchant", 1)

    result = create_disbursement_packages(PAYMENT_DATE, max_orders=3)

    first, second = result.packages
    assert set(first.disbursements.values_list("id", flat=True)) == {a.id, b.id}
    assert first.order_count == 3
    assert set(second.disbursements.values_list("id", flat=True)) == {c.id}
    assert second.order_count == 2
    assert all(p.status == DisbursementPackage.Status.PENDING for p in result.packages)


def test_same_data_produces_the_same_packages():
    disbursement_with("a_merchant", 2)
    disbursement_with("b_merchant", 2)
    disbursement_with("c_merchant", 2)

    first = composition(create_disbursement_packages(PAYMENT_DATE, max_orders=4))
    # Se deshacen los paquetes para volver a armarlos sobre los mismos datos.
    Disbursement.objects.update(package=None)
    DisbursementPackage.objects.all().delete()
    second = composition(create_disbursement_packages(PAYMENT_DATE, max_orders=4))

    assert first == [["a_merchant", "b_merchant"], ["c_merchant"]]
    assert second == first


def composition(result):
    return [sorted(p.disbursements.values_list("merchant__reference", flat=True)) for p in result.packages]


def test_uses_the_configured_max_orders_by_default(settings):
    settings.PACKAGE_MAX_ORDERS = 2
    disbursement_with("a_merchant", 2)
    disbursement_with("b_merchant", 2)

    result = create_disbursement_packages(PAYMENT_DATE)

    assert len(result.packages) == 2


def test_disbursement_that_does_not_fit_requires_attention(caplog):
    # Caso raro: un merchant con más de N orders en un solo pago. No se parte el disbursement;
    # se procesa a mano (cómo, queda por definir).
    too_big = disbursement_with("big_merchant", 4)
    fits = disbursement_with("small_merchant", 1)

    with caplog.at_level(logging.CRITICAL):
        result = create_disbursement_packages(PAYMENT_DATE, max_orders=3)

    too_big.refresh_from_db()
    fits.refresh_from_db()
    assert too_big.status == Disbursement.Status.REQUIRES_ATTENTION
    assert too_big.package is None
    assert [d.id for d in result.requires_attention] == [too_big.id]
    assert fits.package is not None
    assert any(r.levelno == logging.CRITICAL and too_big.reference in r.getMessage() for r in caplog.records)


def test_only_pending_disbursements_without_package_of_the_date():
    already_packed = disbursement_with("a_merchant", 1)
    DisbursementPackageFactory(disbursements=[already_packed])
    disbursement_with("b_merchant", 1, status=Disbursement.Status.COMPLETED)
    disbursement_with("c_merchant", 1, payment_date=date(2023, 2, 9))
    pending = disbursement_with("d_merchant", 1)

    result = create_disbursement_packages(PAYMENT_DATE, max_orders=10)

    assert len(result.packages) == 1
    assert list(result.packages[0].disbursements.values_list("id", flat=True)) == [pending.id]


def test_running_twice_does_not_create_new_packages():
    disbursement = disbursement_with("a_merchant", 1)

    first = create_disbursement_packages(PAYMENT_DATE, max_orders=10)
    assert len(first.packages) == 1
    assert list(first.packages[0].disbursements.values_list("id", flat=True)) == [disbursement.id]

    second = create_disbursement_packages(PAYMENT_DATE, max_orders=10)

    assert second.packages == []
    assert DisbursementPackage.objects.count() == 1


def test_backfill_packs_a_whole_range_of_payment_dates():
    disbursement_with("a_merchant", 1, payment_date=date(2023, 2, 1))
    disbursement_with("b_merchant", 1, payment_date=date(2023, 2, 2))
    disbursement_with("c_merchant", 1, payment_date=date(2023, 2, 3))

    result = create_disbursement_packages(date(2023, 2, 1), date(2023, 2, 2), max_orders=10)

    assert len(result.packages) == 1
    assert result.packages[0].disbursements.count() == 2
