"""Integración: el flujo completo de un día de pago con los servicios reales, sin huey.

Un día de pago: create_disbursements (DAILY y WEEKLY) → create_disbursement_packages →
process_disbursement_package de cada paquete. Es lo que hacen las tasks, llamado en orden.

Datos base (pago del miércoles 8/2):
- padberg_group (DAILY): 2 orders del 7/2 → 533.21 bruto, 4.63 de comisiones, 528.58 a pagar.
- rempel_ltd (DAILY): 1 order del 7/2 → 10.50, 0.11, 10.39.
- deckow_gibson (WEEKLY, live_on miércoles): orders del 1/2 y del 6/2 → 250.00, 2.38, 247.62.
"""

from datetime import date
from decimal import Decimal
from io import StringIO
from unittest import mock

import pytest
from django.core.management import call_command
from django.db import OperationalError

from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_checks import check_disbursement_packages
from disbursement_packages.services.package_creation import create_disbursement_packages
from disbursement_packages.services.package_processing import process_disbursement_package
from disbursements.models import Disbursement
from disbursements.services.disbursement_creation import create_disbursements
from disbursements.tests.factories import DisbursementFactory
from fees.models import MonthlyFee
from fees.services.monthly_fees import calculate_monthly_fees
from merchants.models import Merchant
from merchants.tests.factories import MerchantFactory
from orders.models import Order
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

DAILY = Merchant.Frequency.DAILY
WEEKLY = Merchant.Frequency.WEEKLY
COMPLETED = Disbursement.Status.COMPLETED
FAILED = Disbursement.Status.FAILED

# Miércoles.
PAYMENT_DATE = date(2023, 2, 8)
YESTERDAY = date(2023, 2, 7)
SERVICE = "disbursement_packages.services.package_processing"


def create_payment_day(payment_date):
    """Crea los disbursements del día y los empaqueta, sin procesarlos. Devuelve los paquetes."""
    create_disbursements(payment_date, DAILY)
    create_disbursements(payment_date, WEEKLY)
    return create_disbursement_packages(payment_date).packages


def run_payment_day(payment_date):
    for package in create_payment_day(payment_date):
        process_disbursement_package(package.id)


def disbursement_of(merchant):
    return Disbursement.objects.get(merchant=merchant, payment_date=PAYMENT_DATE)


def amounts(disbursement):
    return (disbursement.gross_amount, disbursement.commission_fee_amount, disbursement.disbursed_amount)


def snapshot():
    """Todo lo que deja el proceso en las tablas, para comparar antes y después."""
    return {
        "disbursements": list(
            Disbursement.objects.order_by("id").values(
                "id", "reference", "status", "package_id", "order_count", "has_processed_delayed_orders",
                "error", "is_retryable", "gross_amount", "commission_fee_amount", "disbursed_amount", "updated_at",
            )
        ),
        "packages": list(
            DisbursementPackage.objects.order_by("id").values(
                "id", "status", "order_count", "attempts", "updated_at"
            )
        ),
        "orders": list(Order.objects.order_by("id").values("id", "amount", "commission_fee", "disbursement_id")),
    }


@pytest.fixture
def daily_merchant():
    return MerchantFactory(reference="padberg_group", disbursement_frequency=DAILY, live_on=date(2023, 1, 1))


@pytest.fixture
def other_daily_merchant():
    return MerchantFactory(reference="rempel_ltd", disbursement_frequency=DAILY, live_on=date(2023, 1, 1))


@pytest.fixture
def weekly_merchant():
    # 2023-01-04 es miércoles: cobra los miércoles.
    return MerchantFactory(reference="deckow_gibson", disbursement_frequency=WEEKLY, live_on=date(2023, 1, 4))


@pytest.fixture
def orders_for_all_merchants(daily_merchant, other_daily_merchant, weekly_merchant):
    OrderFactory(merchant=daily_merchant, order_creation_date=YESTERDAY, amount="100.00", commission_fee="0.95")
    OrderFactory(merchant=daily_merchant, order_creation_date=YESTERDAY, amount="433.21", commission_fee="3.68")
    OrderFactory(merchant=other_daily_merchant, order_creation_date=YESTERDAY, amount="10.50", commission_fee="0.11")
    OrderFactory(merchant=weekly_merchant, order_creation_date=date(2023, 2, 1), amount="200.00", commission_fee="1.90")
    OrderFactory(merchant=weekly_merchant, order_creation_date=date(2023, 2, 6), amount="50.00", commission_fee="0.48")


# --- caso 1 ---

def test_disbursements_of_daily_and_weekly_merchants_are_created_and_processed(
    daily_merchant, other_daily_merchant, weekly_merchant, orders_for_all_merchants
):
    """Caso 1: merchants daily y weekly, todos con orders.

    Se crean los disbursements y se procesan OK.
    """
    run_payment_day(PAYMENT_DATE)

    assert Disbursement.objects.count() == 3
    padberg = disbursement_of(daily_merchant)
    assert padberg.reference == "padberg_group_for_20230207"
    assert padberg.status == COMPLETED
    assert padberg.order_count == 2
    assert padberg.has_processed_delayed_orders is False
    assert amounts(padberg) == (Decimal("533.21"), Decimal("4.63"), Decimal("528.58"))
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.reference == "rempel_ltd_for_20230207"
    assert rempel.status == COMPLETED
    assert rempel.order_count == 1
    assert rempel.has_processed_delayed_orders is False
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    deckow = disbursement_of(weekly_merchant)
    assert deckow.reference == "deckow_gibson_from_20230201_to_20230207"
    assert deckow.status == COMPLETED
    assert deckow.order_count == 2
    assert deckow.has_processed_delayed_orders is False
    assert amounts(deckow) == (Decimal("250.00"), Decimal("2.38"), Decimal("247.62"))
    assert not Order.objects.filter(disbursement__isnull=True).exists()
    # Un día normal entra en un solo paquete.
    assert DisbursementPackage.objects.count() == 1
    package = padberg.package
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.order_count == 5
    assert package.attempts == 1


# --- caso 2 ---

def test_only_merchants_with_orders_get_a_disbursement(daily_merchant, weekly_merchant):
    """Caso 2: merchants daily y weekly, pero solo algunos con orders.

    Se crean disbursements solo para los que tienen orders y se procesan OK.
    """
    OrderFactory(merchant=daily_merchant, order_creation_date=YESTERDAY, amount="100.00", commission_fee="0.95")
    OrderFactory(merchant=weekly_merchant, order_creation_date=date(2023, 2, 1), amount="200.00", commission_fee="1.90")
    # Un DAILY y un WEEKLY (también de miércoles) sin orders.
    MerchantFactory(reference="rempel_ltd", disbursement_frequency=DAILY, live_on=date(2023, 1, 1))
    MerchantFactory(reference="kunze_inc", disbursement_frequency=WEEKLY, live_on=date(2023, 1, 4))

    run_payment_day(PAYMENT_DATE)

    references = set(Disbursement.objects.values_list("merchant__reference", flat=True))
    assert references == {"padberg_group", "deckow_gibson"}
    padberg = disbursement_of(daily_merchant)
    assert padberg.status == COMPLETED
    assert padberg.order_count == 1
    assert amounts(padberg) == (Decimal("100.00"), Decimal("0.95"), Decimal("99.05"))
    deckow = disbursement_of(weekly_merchant)
    assert deckow.status == COMPLETED
    assert deckow.order_count == 1
    assert amounts(deckow) == (Decimal("200.00"), Decimal("1.90"), Decimal("198.10"))
    assert DisbursementPackage.objects.count() == 1
    package = padberg.package
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.order_count == 2


# --- caso 3 ---

def test_delayed_orders_are_paid_in_the_next_payment_and_flagged(
    daily_merchant, other_daily_merchant, weekly_merchant, orders_for_all_merchants
):
    """Caso 3: merchants daily y weekly con orders, algunas de fechas viejas que entraron tarde.

    Los disbursements incluyen esas orders, se procesan OK y quedan marcados con
    has_processed_delayed_orders para saber que pagaron algo de otra fecha.
    """
    # Orders de fechas viejas que entraron tarde y nunca se pagaron: fuera de la ventana de esta corrida.
    delayed_daily = OrderFactory(merchant=daily_merchant, order_creation_date=date(2023, 2, 3), amount="20.00", commission_fee="0.20")
    # deckow_gibson cobra del 1/2 al 7/2: la del 25/1 es de la semana anterior.
    delayed_weekly = OrderFactory(merchant=weekly_merchant, order_creation_date=date(2023, 1, 25), amount="30.00", commission_fee="0.30")

    run_payment_day(PAYMENT_DATE)

    padberg = disbursement_of(daily_merchant)
    assert delayed_daily.id in set(padberg.orders.values_list("id", flat=True))
    assert padberg.reference == "padberg_group_for_20230207"
    assert padberg.status == COMPLETED
    assert padberg.order_count == 3
    assert padberg.has_processed_delayed_orders is True
    assert amounts(padberg) == (Decimal("553.21"), Decimal("4.83"), Decimal("548.38"))
    deckow = disbursement_of(weekly_merchant)
    assert delayed_weekly.id in set(deckow.orders.values_list("id", flat=True))
    assert deckow.reference == "deckow_gibson_from_20230201_to_20230207"
    assert deckow.status == COMPLETED
    assert deckow.order_count == 3
    assert deckow.has_processed_delayed_orders is True
    assert amounts(deckow) == (Decimal("280.00"), Decimal("2.68"), Decimal("277.32"))
    # rempel_ltd no tiene orders atrasadas: no se marca.
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == COMPLETED
    assert rempel.has_processed_delayed_orders is False
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))


# --- caso 4 ---

def test_reprocessing_what_is_already_completed_does_not_duplicate_or_change_anything(orders_for_all_merchants):
    """Caso 4: merchants daily y weekly con orders; se crean los disbursements y se procesan OK.

    Después se reprocesa lo mismo (el paquete y los disbursements por id): no se duplican registros
    ni cambian los resultados.
    """
    # El reprocess es manual y acotado: un paquete o algunos disbursements por id, nunca el día entero.
    run_payment_day(PAYMENT_DATE)
    before = snapshot()
    package_id = before["packages"][0]["id"]
    disbursement_ids = [str(d["id"]) for d in before["disbursements"]]

    package_output = StringIO()
    call_command("retry_disbursement_package", str(package_id), stdout=package_output)
    disbursements_output = StringIO()
    call_command("retry_disbursements", *disbursement_ids, stdout=disbursements_output)

    assert snapshot() == before
    assert Disbursement.objects.count() == 3
    assert DisbursementPackage.objects.count() == 1
    assert "already completed" in package_output.getvalue().lower()
    assert "Reprocessed: 0" in disbursements_output.getvalue()
    assert "Skipped (already completed): 3" in disbursements_output.getvalue()


# --- caso 5 y 5 bis: falla de datos, sin reintento automático ---

@pytest.fixture
def package_with_a_data_failure(other_daily_merchant, orders_for_all_merchants):
    (package,) = create_payment_day(PAYMENT_DATE)
    # Dato inconsistente: rempel_ltd dice tener 3 orders pero tiene 1.
    Disbursement.objects.filter(merchant=other_daily_merchant).update(order_count=3)
    process_disbursement_package(package.id)
    return package


def test_data_failure_leaves_the_valid_disbursements_completed_and_is_not_retried(
    daily_merchant, other_daily_merchant, weekly_merchant, package_with_a_data_failure
):
    """Caso 5: merchants daily y weekly con orders; algunos disbursements se procesan OK y otros fallan
    por datos, sin posibilidad de reintentar.

    Se valida cómo quedan disbursements, paquete y orders, y que el control no lo reintenta.
    """
    package = package_with_a_data_failure
    result = check_disbursement_packages(PAYMENT_DATE, is_last_run=False)

    assert result.to_retry == []
    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.FAILED
    assert package.attempts == 1
    padberg = disbursement_of(daily_merchant)
    assert padberg.status == COMPLETED
    assert padberg.error == ""
    assert amounts(padberg) == (Decimal("533.21"), Decimal("4.63"), Decimal("528.58"))
    deckow = disbursement_of(weekly_merchant)
    assert deckow.status == COMPLETED
    assert deckow.error == ""
    assert amounts(deckow) == (Decimal("250.00"), Decimal("2.38"), Decimal("247.62"))
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == FAILED
    assert rempel.is_retryable is False
    assert "3" in rempel.error
    assert amounts(rempel) == (None, None, None)
    # Las orders siguen asignadas a su disbursement, aunque haya fallado.
    assert not Order.objects.filter(disbursement__isnull=True).exists()


def test_data_failure_is_fixed_by_a_user_and_the_manual_retry_completes_the_package(
    daily_merchant, other_daily_merchant, weekly_merchant, package_with_a_data_failure
):
    """Caso 5 bis: lo mismo que el caso 5, y después un usuario corrige el dato y reprocesa a mano.

    El proceso termina OK y lo que ya estaba COMPLETED no se toca.
    """
    package = package_with_a_data_failure
    completed_before = [d for d in snapshot()["disbursements"] if d["status"] == COMPLETED]
    # Un usuario corrige el dato y reprocesa el paquete a mano.
    Disbursement.objects.filter(merchant=other_daily_merchant).update(order_count=1)

    call_command("retry_disbursement_package", str(package.id))

    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.attempts == 2
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == COMPLETED
    assert rempel.error == ""
    assert rempel.is_retryable is None
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    # Los que ya estaban COMPLETED no se vuelven a tocar.
    completed_after = [d for d in snapshot()["disbursements"] if d["id"] in {c["id"] for c in completed_before}]
    assert completed_after == completed_before


# --- caso 6 y 6 bis: falla de infraestructura, con reintento automático ---

@pytest.fixture
def packages_with_an_infrastructure_failure(settings, daily_merchant, orders_for_all_merchants):
    settings.PACKAGE_MAX_RETRIES = 1
    settings.PACKAGE_FAILURE_THRESHOLD_PERCENT = 80
    # Con 2 orders por paquete queda un paquete por merchant.
    settings.PACKAGE_MAX_ORDERS = 2
    packages = create_payment_day(PAYMENT_DATE)
    failing = disbursement_of(daily_merchant).package
    for package in packages:
        if package.id == failing.id:
            # Se cae la DB al guardar los resultados del paquete de padberg_group.
            with mock.patch(f"{SERVICE}.save_disbursement_results", side_effect=OperationalError("connection lost")):
                process_disbursement_package(package.id)
        else:
            process_disbursement_package(package.id)
    return failing


def test_infrastructure_failure_fails_only_its_package_and_can_be_retried(
    daily_merchant, other_daily_merchant, weekly_merchant, packages_with_an_infrastructure_failure
):
    """Caso 6: merchants daily y weekly con orders; algunos paquetes se procesan OK y otro falla por
    infraestructura, con posibilidad de reintentar.

    Se valida cómo quedan disbursements y paquetes, y que el control lo marca para reintentar.
    """
    failing = packages_with_an_infrastructure_failure

    result = check_disbursement_packages(PAYMENT_DATE, is_last_run=False)

    # 1 de 3 disbursements del día FAILED (33%) no supera el umbral: se reintenta.
    assert result.to_retry == [failing.id]
    assert DisbursementPackage.objects.count() == 3
    failing.refresh_from_db()
    assert failing.status == DisbursementPackage.Status.FAILED
    assert failing.attempts == 1
    padberg = disbursement_of(daily_merchant)
    assert padberg.status == FAILED
    assert padberg.is_retryable is True
    assert "connection lost" in padberg.error
    assert amounts(padberg) == (None, None, None)
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == COMPLETED
    assert rempel.package.status == DisbursementPackage.Status.COMPLETED
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    deckow = disbursement_of(weekly_merchant)
    assert deckow.status == COMPLETED
    assert deckow.package.status == DisbursementPackage.Status.COMPLETED
    assert amounts(deckow) == (Decimal("250.00"), Decimal("2.38"), Decimal("247.62"))


def test_infrastructure_failure_is_completed_by_the_automatic_retry(daily_merchant, packages_with_an_infrastructure_failure):
    """Caso 6 bis: lo mismo que el caso 6, y después el reintento automático vuelve a correr el proceso.

    El proceso termina OK y los paquetes que ya estaban COMPLETED no se vuelven a procesar.
    """
    failing = packages_with_an_infrastructure_failure
    others_before = [p for p in snapshot()["packages"] if p["id"] != failing.id]
    # Lo que hace la task de control: pide los paquetes a reintentar y los procesa.
    result = check_disbursement_packages(PAYMENT_DATE, is_last_run=False)

    for package_id in result.to_retry:
        process_disbursement_package(package_id)

    failing.refresh_from_db()
    assert failing.status == DisbursementPackage.Status.COMPLETED
    assert failing.attempts == 2
    padberg = disbursement_of(daily_merchant)
    assert padberg.status == COMPLETED
    assert padberg.error == ""
    assert padberg.is_retryable is None
    assert amounts(padberg) == (Decimal("533.21"), Decimal("4.63"), Decimal("528.58"))
    assert not Disbursement.objects.exclude(status=COMPLETED).exists()
    # Los otros paquetes no se vuelven a procesar.
    others_after = [p for p in snapshot()["packages"] if p["id"] != failing.id]
    assert others_after == others_before


# --- caso 7: monthly fees con disbursements en distintos estados ---

def test_monthly_fees_count_every_order_of_the_month_whatever_the_state_of_its_disbursement():
    """Caso 7: disbursements sin procesar, procesados con error y procesados OK, y merchants sin
    disbursements. Se calculan las monthly fees de enero 2023, minimum 29.00 salvo que se indique otro.

    - processed_ok: order de 10.00 de comisión con disbursement COMPLETED → fee 19.00.
    - processed_with_error: 5.00 con disbursement FAILED → fee 24.00.
    - not_processed: 4.00 con disbursement PENDING (se paga el 1/2) → fee 25.00.
    - not_disbursed: 3.00 sin disbursement todavía → fee 26.00.
    - without_orders: live y sin orders → paga el minimum entero, 29.00.
    - over_minimum: 30.00 de comisiones → no se le cobra.
    - without_minimum: minimum 0 → no se le cobra.
    - not_live_yet: live_on 1/2 → enero no se le cobra.
    La fee queda guardada en MonthlyFee y no se descuenta de ningún disbursement ni order.
    """
    january = date(2023, 1, 1)
    live_on = date(2022, 6, 1)

    processed_ok = MerchantFactory(reference="processed_ok", live_on=live_on, minimum_monthly_fee="29.00")
    order = OrderFactory(merchant=processed_ok, order_creation_date=date(2023, 1, 10), amount="1176.47", commission_fee="10.00")
    DisbursementFactory(
        merchant=processed_ok, payment_date=date(2023, 1, 11), orders=[order], status=COMPLETED,
        gross_amount="1176.47", commission_fee_amount="10.00", disbursed_amount="1166.47",
    )

    processed_with_error = MerchantFactory(reference="processed_with_error", live_on=live_on, minimum_monthly_fee="29.00")
    order = OrderFactory(merchant=processed_with_error, order_creation_date=date(2023, 1, 10), amount="588.24", commission_fee="5.00")
    DisbursementFactory(
        merchant=processed_with_error, payment_date=date(2023, 1, 11), orders=[order], status=FAILED,
        error="Se esperaban 2 orders y hay 1.",
    )

    not_processed = MerchantFactory(reference="not_processed", live_on=live_on, minimum_monthly_fee="29.00")
    order = OrderFactory(merchant=not_processed, order_creation_date=date(2023, 1, 31), amount="470.59", commission_fee="4.00")
    DisbursementFactory(merchant=not_processed, payment_date=date(2023, 2, 1), orders=[order])

    not_disbursed = MerchantFactory(reference="not_disbursed", live_on=live_on, minimum_monthly_fee="29.00")
    OrderFactory(merchant=not_disbursed, order_creation_date=date(2023, 1, 31), amount="352.94", commission_fee="3.00")

    without_orders = MerchantFactory(reference="without_orders", live_on=live_on, minimum_monthly_fee="29.00")

    over_minimum = MerchantFactory(reference="over_minimum", live_on=live_on, minimum_monthly_fee="29.00")
    OrderFactory(merchant=over_minimum, order_creation_date=date(2023, 1, 10), amount="3529.41", commission_fee="30.00")

    without_minimum = MerchantFactory(reference="without_minimum", live_on=live_on, minimum_monthly_fee="0.00")
    OrderFactory(merchant=without_minimum, order_creation_date=date(2023, 1, 10), amount="100.00", commission_fee="0.95")

    not_live_yet = MerchantFactory(reference="not_live_yet", live_on=date(2023, 2, 1), minimum_monthly_fee="29.00")

    before = snapshot()

    calculate_monthly_fees(january)

    expected = {
        processed_ok: ("10.00", "19.00"),
        processed_with_error: ("5.00", "24.00"),
        not_processed: ("4.00", "25.00"),
        not_disbursed: ("3.00", "26.00"),
        without_orders: ("0.00", "29.00"),
    }
    assert MonthlyFee.objects.count() == len(expected)
    for merchant, (commissions, amount) in expected.items():
        fee = MonthlyFee.objects.get(merchant=merchant, month=january)
        assert fee.commissions_amount == Decimal(commissions), merchant.reference
        assert fee.minimum_monthly_fee == Decimal("29.00"), merchant.reference
        assert fee.amount == Decimal(amount), merchant.reference
    for merchant in (over_minimum, without_minimum, not_live_yet):
        assert not MonthlyFee.objects.filter(merchant=merchant).exists(), merchant.reference
    # No se descuenta de nada: disbursements, paquetes y orders quedan iguales.
    assert snapshot() == before
