"""create_disbursements_daily / weekly y el backfill create_disbursements_for_range.

Ventanas (opción A): la corrida del día D paga días cerrados.
- DAILY: orders de D-1.
- WEEKLY: el weekday del live_on, orders de D-7 a D-1.
"""

import logging
from datetime import date, timedelta

import pytest

from disbursements.models import Disbursement, Order
from disbursements.services.disbursement_creation import (
    create_disbursements,
    create_disbursements_for_range,
    natural_key_hash,
)
from disbursements.tests.factories import DisbursementFactory, OrderFactory
from merchants.models import Merchant
from merchants.tests.factories import MerchantFactory

pytestmark = pytest.mark.django_db

DAILY = Merchant.Frequency.DAILY
WEEKLY = Merchant.Frequency.WEEKLY

# Miércoles.
PAYMENT_DATE = date(2023, 2, 8)
YESTERDAY = PAYMENT_DATE - timedelta(days=1)


@pytest.fixture
def daily_merchant():
    return MerchantFactory(reference="padberg_group", disbursement_frequency=DAILY, live_on=date(2023, 1, 1))


@pytest.fixture
def weekly_merchant():
    # 2023-01-04 también es miércoles.
    return MerchantFactory(reference="deckow_gibson", disbursement_frequency=WEEKLY, live_on=date(2023, 1, 4))


# --- daily ---

def test_pays_the_orders_of_the_previous_day(daily_merchant):
    order_1 = OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    order_2 = OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, DAILY)

    disbursement = Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE)
    assert disbursement.merchant_id == daily_merchant.id
    assert disbursement.payment_date == PAYMENT_DATE
    assert disbursement.status == Disbursement.Status.PENDING
    assert disbursement.order_count == 2
    assert set(disbursement.orders.values_list("id", flat=True)) == {order_1.id, order_2.id}
    assert disbursement.has_processed_delayed_orders is False


def test_reference_is_readable_with_the_date_of_the_orders(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, DAILY)

    disbursement = Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE)
    assert disbursement.reference == "padberg_group_for_20230207"


def test_orders_of_the_payment_day_are_not_included(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    today_order = OrderFactory(merchant=daily_merchant, created_at=PAYMENT_DATE)

    create_disbursements(PAYMENT_DATE, DAILY)

    today_order.refresh_from_db()
    assert today_order.disbursement_id is None


def test_no_orders_means_no_disbursement(daily_merchant):
    create_disbursements(PAYMENT_DATE, DAILY)

    assert not Disbursement.objects.exists()


def test_only_daily_merchants_are_processed(daily_merchant, weekly_merchant):
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    weekly_order = OrderFactory(merchant=weekly_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, DAILY)

    weekly_order.refresh_from_db()
    assert weekly_order.disbursement_id is None
    assert list(Disbursement.objects.values_list("merchant__reference", flat=True)) == ["padberg_group"]


def test_each_merchant_gets_its_own_disbursement(daily_merchant):
    other = MerchantFactory(reference="windler_and_sons", disbursement_frequency=DAILY)
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    OrderFactory(merchant=other, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, DAILY)

    assert Disbursement.objects.count() == 2


# --- weekly ---

def test_pays_the_closed_week_on_the_live_on_weekday(weekly_merchant):
    first_day = OrderFactory(merchant=weekly_merchant, created_at=PAYMENT_DATE - timedelta(days=7))
    last_day = OrderFactory(merchant=weekly_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, WEEKLY)

    disbursement = Disbursement.objects.get(merchant=weekly_merchant, payment_date=PAYMENT_DATE)
    assert disbursement.order_count == 2
    assert set(disbursement.orders.values_list("id", flat=True)) == {first_day.id, last_day.id}
    assert disbursement.reference == "deckow_gibson_from_20230201_to_20230207"


def test_weekly_merchant_is_only_paid_on_its_own_weekday(weekly_merchant):
    # deckow_gibson tiene live_on un miércoles: su día de pago es el miércoles. La corrida del jueves 9/2
    # NO es una corrida de pago para él, así que no hace nada aunque tenga orders sin pagar.
    # Su siguiente día de pago es el miércoles 15/2, que paga los días cerrados del 8/2 al 14/2.
    wednesday_order = OrderFactory(merchant=weekly_merchant, created_at=date(2023, 2, 8))
    saturday_order = OrderFactory(merchant=weekly_merchant, created_at=date(2023, 2, 11))

    create_disbursements(date(2023, 2, 9), WEEKLY)

    assert not Disbursement.objects.filter(merchant=weekly_merchant).exists()

    create_disbursements(date(2023, 2, 15), WEEKLY)

    disbursement = Disbursement.objects.get(merchant=weekly_merchant, payment_date=date(2023, 2, 15))
    assert set(disbursement.orders.values_list("id", flat=True)) == {wednesday_order.id, saturday_order.id}
    assert disbursement.reference == "deckow_gibson_from_20230208_to_20230214"


def test_weekly_merchant_live_on_a_thursday_is_paid_on_thursdays():
    # Mismas orders que el test anterior, pero el merchant tiene live_on un jueves (05/01/2023):
    # la corrida del jueves 9/2 paga del 2/2 al 8/2 y la del jueves 16/2, del 9/2 al 15/2.
    thursday_merchant = MerchantFactory(
        reference="thursday_merchant", disbursement_frequency=WEEKLY, live_on=date(2023, 1, 5)
    )
    wednesday_order = OrderFactory(merchant=thursday_merchant, created_at=date(2023, 2, 8))
    saturday_order = OrderFactory(merchant=thursday_merchant, created_at=date(2023, 2, 11))

    create_disbursements(date(2023, 2, 9), WEEKLY)
    create_disbursements(date(2023, 2, 16), WEEKLY)

    first = Disbursement.objects.get(merchant=thursday_merchant, payment_date=date(2023, 2, 9))
    assert list(first.orders.values_list("id", flat=True)) == [wednesday_order.id]
    assert first.reference == "thursday_merchant_from_20230202_to_20230208"
    second = Disbursement.objects.get(merchant=thursday_merchant, payment_date=date(2023, 2, 16))
    assert list(second.orders.values_list("id", flat=True)) == [saturday_order.id]
    assert second.reference == "thursday_merchant_from_20230209_to_20230215"


def test_only_weekly_merchants_are_processed(daily_merchant, weekly_merchant):
    daily_order = OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    OrderFactory(merchant=weekly_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, WEEKLY)

    daily_order.refresh_from_db()
    assert daily_order.disbursement_id is None
    assert list(Disbursement.objects.values_list("merchant__reference", flat=True)) == ["deckow_gibson"]


# --- idempotency and exactly once ---

def test_running_twice_creates_a_single_disbursement(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, DAILY)
    first = Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE)
    create_disbursements(PAYMENT_DATE, DAILY)

    assert Disbursement.objects.count() == 1
    assert Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE).id == first.id


def test_existing_disbursement_is_not_touched_and_late_orders_wait(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    create_disbursements(PAYMENT_DATE, DAILY)

    late_order = OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)
    create_disbursements(PAYMENT_DATE, DAILY)

    late_order.refresh_from_db()
    assert late_order.disbursement_id is None
    assert Disbursement.objects.count() == 1
    assert Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE).order_count == 1


def test_orders_already_disbursed_are_never_reassigned(daily_merchant):
    previous = DisbursementFactory(merchant=daily_merchant, payment_date=YESTERDAY)
    disbursed = OrderFactory(merchant=daily_merchant, created_at=YESTERDAY, disbursement=previous)

    create_disbursements(PAYMENT_DATE, DAILY)

    disbursed.refresh_from_db()
    assert disbursed.disbursement_id == previous.id
    assert Disbursement.objects.count() == 1


def test_disbursement_is_saved_with_the_natural_key_hash_of_its_merchant_and_date(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, DAILY)

    disbursement = Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE)
    assert disbursement.natural_key_hash == natural_key_hash(daily_merchant.id, PAYMENT_DATE)


def test_natural_key_hash_is_the_same_for_the_same_merchant_and_date(daily_merchant):
    # Es lo que permite que el constraint único de la DB frene una segunda creación.
    first = natural_key_hash(daily_merchant.id, PAYMENT_DATE)
    second = natural_key_hash(daily_merchant.id, PAYMENT_DATE)

    assert first == second
    assert len(first) == 64


def test_natural_key_hash_changes_with_the_merchant_or_the_date(daily_merchant, weekly_merchant):
    base = natural_key_hash(daily_merchant.id, PAYMENT_DATE)
    other_date = natural_key_hash(daily_merchant.id, YESTERDAY)
    other_merchant = natural_key_hash(weekly_merchant.id, PAYMENT_DATE)

    assert len({base, other_date, other_merchant}) == 3


# --- delayed orders ---

def test_delayed_order_goes_into_the_next_payment_and_is_flagged(daily_merchant, caplog):
    # Order del día 5 que entró tarde: el pago del 6 ya se hizo sin ella.
    delayed = OrderFactory(merchant=daily_merchant, created_at=PAYMENT_DATE - timedelta(days=3))
    on_time = OrderFactory(merchant=daily_merchant, created_at=YESTERDAY)

    with caplog.at_level(logging.WARNING):
        create_disbursements(PAYMENT_DATE, DAILY)

    disbursement = Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE)
    assert set(disbursement.orders.values_list("id", flat=True)) == {delayed.id, on_time.id}
    assert disbursement.has_processed_delayed_orders is True
    assert any(r.levelno == logging.WARNING and "padberg_group" in r.getMessage() for r in caplog.records)


def test_delayed_order_alone_creates_a_disbursement(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=PAYMENT_DATE - timedelta(days=3))

    create_disbursements(PAYMENT_DATE, DAILY)

    disbursement = Disbursement.objects.get(merchant=daily_merchant, payment_date=PAYMENT_DATE)
    assert disbursement.has_processed_delayed_orders is True


def test_weekly_delayed_order_from_a_previous_week(weekly_merchant):
    delayed = OrderFactory(merchant=weekly_merchant, created_at=PAYMENT_DATE - timedelta(days=10))
    OrderFactory(merchant=weekly_merchant, created_at=YESTERDAY)

    create_disbursements(PAYMENT_DATE, WEEKLY)

    delayed.refresh_from_db()
    assert delayed.disbursement.has_processed_delayed_orders is True


# --- backfill range ---

def test_backfill_creates_daily_and_weekly_disbursements_on_the_right_dates(daily_merchant, weekly_merchant):
    """Backfill de 2 semanas.

    Datos: una order por día, del 1/2 al 14/2, para padberg_group (DAILY) y para deckow_gibson
    (WEEKLY, cobra los miércoles).
    Ejecución: create_disbursements_for_range del 2/2 al 15/2 (fechas de pago).
    Resultado:
    - padberg_group: un disbursement por día de pago, del 2/2 al 15/2 (14), cada uno con las orders del día anterior.
    - deckow_gibson: dos disbursements, los miércoles 8/2 (orders del 1/2 al 7/2) y 15/2 (del 8/2 al 14/2).
    - Las 28 orders quedan asignadas y el servicio devuelve los 16 disbursements creados.
    """
    for day in range(1, 15):
        OrderFactory(merchant=daily_merchant, created_at=date(2023, 2, day))
        OrderFactory(merchant=weekly_merchant, created_at=date(2023, 2, day))

    result = create_disbursements_for_range(date(2023, 2, 2), date(2023, 2, 15))

    daily = Disbursement.objects.filter(merchant=daily_merchant).order_by("payment_date")
    assert list(daily.values_list("payment_date", flat=True)) == [date(2023, 2, d) for d in range(2, 16)]
    assert all(d.order_count == 1 for d in daily)
    weekly = Disbursement.objects.filter(merchant=weekly_merchant).order_by("payment_date")
    assert list(weekly.values_list("payment_date", "order_count")) == [(date(2023, 2, 8), 7), (date(2023, 2, 15), 7)]
    assert not Order.objects.filter(disbursement__isnull=True).exists()
    assert sorted(d.id for d in result.created) == sorted(Disbursement.objects.values_list("id", flat=True))
    assert len(result.created) == 16


def test_backfill_run_twice_over_the_same_range_does_not_duplicate_disbursements(daily_merchant):
    OrderFactory(merchant=daily_merchant, created_at=date(2023, 2, 1))
    OrderFactory(merchant=daily_merchant, created_at=date(2023, 2, 2))

    create_disbursements_for_range(date(2023, 2, 2), date(2023, 2, 3))
    second = create_disbursements_for_range(date(2023, 2, 2), date(2023, 2, 3))

    assert second.created == []
    disbursements = Disbursement.objects.filter(merchant=daily_merchant).order_by("payment_date")
    assert list(disbursements.values_list("payment_date", flat=True)) == [date(2023, 2, 2), date(2023, 2, 3)]
