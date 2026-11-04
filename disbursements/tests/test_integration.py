"""Integration: the whole flow of a payment day with the real services, without huey.

A payment day: create_disbursements (DAILY and WEEKLY) → create_disbursement_packages →
process_disbursement_package for each package. It is what the tasks do, called in order.

Base data (payment of Wednesday 2/8):
- padberg_group (DAILY): 2 orders of 2/7 → 533.21 gross, 4.63 in commissions, 528.58 to pay.
- rempel_ltd (DAILY): 1 order of 2/7 → 10.50, 0.11, 10.39.
- deckow_gibson (WEEKLY, live_on Wednesday): orders of 2/1 and 2/6 → 250.00, 2.38, 247.62.
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

# Wednesday.
PAYMENT_DATE = date(2023, 2, 8)
YESTERDAY = date(2023, 2, 7)
SERVICE = "disbursement_packages.services.package_processing"


def create_payment_day(payment_date):
    """Creates the disbursements of the day and packages them, without processing them. Returns the packages."""
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
    """Everything the process leaves in the tables, to compare before and after."""
    return {
        "disbursements": list(
            Disbursement.objects.order_by("id").values(
                "id", "reference", "status", "package_id", "has_processed_delayed_orders",
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
    # 2023-01-04 is a Wednesday: paid on Wednesdays.
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
    """Case 1: daily and weekly merchants, all of them with orders.

    The disbursements are created and processed OK.
    """
    run_payment_day(PAYMENT_DATE)

    assert Disbursement.objects.count() == 3
    padberg = disbursement_of(daily_merchant)
    assert padberg.reference == "padberg_group_for_20230207"
    assert padberg.status == COMPLETED
    assert padberg.orders.count() == 2
    assert padberg.has_processed_delayed_orders is False
    assert amounts(padberg) == (Decimal("533.21"), Decimal("4.63"), Decimal("528.58"))
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.reference == "rempel_ltd_for_20230207"
    assert rempel.status == COMPLETED
    assert rempel.orders.count() == 1
    assert rempel.has_processed_delayed_orders is False
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    deckow = disbursement_of(weekly_merchant)
    assert deckow.reference == "deckow_gibson_from_20230201_to_20230207"
    assert deckow.status == COMPLETED
    assert deckow.orders.count() == 2
    assert deckow.has_processed_delayed_orders is False
    assert amounts(deckow) == (Decimal("250.00"), Decimal("2.38"), Decimal("247.62"))
    assert not Order.objects.filter(disbursement__isnull=True).exists()
    # A normal day fits in a single package.
    assert DisbursementPackage.objects.count() == 1
    package = padberg.package
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.order_count == 5
    assert package.attempts == 1


# --- caso 2 ---

def test_only_merchants_with_orders_get_a_disbursement(daily_merchant, weekly_merchant):
    """Case 2: daily and weekly merchants, but only some of them with orders.

    Disbursements are created only for the ones with orders, and processed OK.
    """
    OrderFactory(merchant=daily_merchant, order_creation_date=YESTERDAY, amount="100.00", commission_fee="0.95")
    OrderFactory(merchant=weekly_merchant, order_creation_date=date(2023, 2, 1), amount="200.00", commission_fee="1.90")
    # A DAILY and a WEEKLY (also on Wednesdays) without orders.
    MerchantFactory(reference="rempel_ltd", disbursement_frequency=DAILY, live_on=date(2023, 1, 1))
    MerchantFactory(reference="kunze_inc", disbursement_frequency=WEEKLY, live_on=date(2023, 1, 4))

    run_payment_day(PAYMENT_DATE)

    references = set(Disbursement.objects.values_list("merchant__reference", flat=True))
    assert references == {"padberg_group", "deckow_gibson"}
    padberg = disbursement_of(daily_merchant)
    assert padberg.status == COMPLETED
    assert padberg.orders.count() == 1
    assert amounts(padberg) == (Decimal("100.00"), Decimal("0.95"), Decimal("99.05"))
    deckow = disbursement_of(weekly_merchant)
    assert deckow.status == COMPLETED
    assert deckow.orders.count() == 1
    assert amounts(deckow) == (Decimal("200.00"), Decimal("1.90"), Decimal("198.10"))
    assert DisbursementPackage.objects.count() == 1
    package = padberg.package
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.order_count == 2


# --- caso 3 ---

def test_delayed_orders_are_paid_in_the_next_payment_and_flagged(
    daily_merchant, other_daily_merchant, weekly_merchant, orders_for_all_merchants
):
    """Case 3: daily and weekly merchants with orders, some of them from old dates that arrived late.

    The disbursements include those orders, are processed OK and are flagged with
    has_processed_delayed_orders, to know they paid something from another date.
    """
    # Orders from old dates that arrived late and were never paid: outside the window of this run.
    delayed_daily = OrderFactory(merchant=daily_merchant, order_creation_date=date(2023, 2, 3), amount="20.00", commission_fee="0.20")
    # deckow_gibson is paid from 2/1 to 2/7: the one of 1/25 is from the previous week.
    delayed_weekly = OrderFactory(merchant=weekly_merchant, order_creation_date=date(2023, 1, 25), amount="30.00", commission_fee="0.30")

    run_payment_day(PAYMENT_DATE)

    padberg = disbursement_of(daily_merchant)
    assert delayed_daily.id in set(padberg.orders.values_list("id", flat=True))
    assert padberg.reference == "padberg_group_for_20230207"
    assert padberg.status == COMPLETED
    assert padberg.orders.count() == 3
    assert padberg.has_processed_delayed_orders is True
    assert amounts(padberg) == (Decimal("553.21"), Decimal("4.83"), Decimal("548.38"))
    deckow = disbursement_of(weekly_merchant)
    assert delayed_weekly.id in set(deckow.orders.values_list("id", flat=True))
    assert deckow.reference == "deckow_gibson_from_20230201_to_20230207"
    assert deckow.status == COMPLETED
    assert deckow.orders.count() == 3
    assert deckow.has_processed_delayed_orders is True
    assert amounts(deckow) == (Decimal("280.00"), Decimal("2.68"), Decimal("277.32"))
    # rempel_ltd has no delayed orders: it is not flagged.
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == COMPLETED
    assert rempel.has_processed_delayed_orders is False
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))


# --- caso 4 ---

def test_reprocessing_what_is_already_completed_does_not_duplicate_or_change_anything(orders_for_all_merchants):
    """Case 4: daily and weekly merchants with orders; the disbursements are created and processed OK.

    Then the same is reprocessed (the package, and the disbursements by id): no records are duplicated
    and the results do not change.
    """
    # Reprocessing is manual and limited: a package or some disbursements by id, never the whole day.
    run_payment_day(PAYMENT_DATE)
    before = snapshot()
    package_id = before["packages"][0]["id"]
    disbursement_ids = [str(disbursement["id"]) for disbursement in before["disbursements"]]

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


# --- cases 5 and 5 bis: data failure, without automatic retry ---

@pytest.fixture
def package_with_a_data_failure(other_daily_merchant, orders_for_all_merchants):
    (package,) = create_payment_day(PAYMENT_DATE)
    # Inconsistent data: the commission of rempel_ltd's order is greater than its amount.
    Order.objects.filter(merchant=other_daily_merchant).update(commission_fee="20.00")
    process_disbursement_package(package.id)
    return package


def test_data_failure_leaves_the_valid_disbursements_completed_and_is_not_retried(
    daily_merchant, other_daily_merchant, weekly_merchant, package_with_a_data_failure
):
    """Case 5: daily and weekly merchants with orders; some disbursements are processed OK and others
    fail because of data, with no possible retry.

    It checks how disbursements, package and orders end up, and that the check does not retry it.
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
    assert "greater than the gross amount" in rempel.error
    assert amounts(rempel) == (None, None, None)
    # The orders stay assigned to their disbursement, even though it failed.
    assert not Order.objects.filter(disbursement__isnull=True).exists()


def test_data_failure_is_fixed_by_a_user_and_the_manual_retry_completes_the_package(
    daily_merchant, other_daily_merchant, weekly_merchant, package_with_a_data_failure
):
    """Case 5 bis: the same as case 5, and then a user fixes the data and reprocesses by hand.

    The process ends OK and what was already COMPLETED is not touched.
    """
    package = package_with_a_data_failure
    completed_before = [disbursement for disbursement in snapshot()["disbursements"] if disbursement["status"] == COMPLETED]
    # A user fixes the data and reprocesses the package by hand.
    Order.objects.filter(merchant=other_daily_merchant).update(commission_fee="0.11")

    call_command("retry_disbursement_package", str(package.id))

    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.attempts == 2
    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == COMPLETED
    assert rempel.error == ""
    assert rempel.is_retryable is None
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    # The ones already COMPLETED are not touched again.
    completed_after = [disbursement for disbursement in snapshot()["disbursements"] if disbursement["id"] in {completed["id"] for completed in completed_before}]
    assert completed_after == completed_before


def test_retry_processes_the_same_orders_and_a_late_order_goes_to_the_next_disbursement(
    other_daily_merchant, package_with_a_data_failure
):
    """Case 5 ter: the same as case 5 bis, but before the retry a late order of the same day arrives,
    and the disbursement of the next day, which includes it, is already created and packaged.

    A disbursement does not change once created: the retry processes the same orders of the failed
    disbursement and does not touch the disbursement or the package of the next day.
    """
    package = package_with_a_data_failure
    late_order = OrderFactory(merchant=other_daily_merchant, order_creation_date=YESTERDAY, amount="99.00", commission_fee="0.94")
    next_payment_date = date(2023, 2, 9)
    (next_package,) = create_payment_day(next_payment_date)
    next_disbursement = Disbursement.objects.get(merchant=other_daily_merchant, payment_date=next_payment_date)
    next_disbursement_before = [disbursement for disbursement in snapshot()["disbursements"] if disbursement["id"] == next_disbursement.id]
    next_package_before = [package for package in snapshot()["packages"] if package["id"] == next_package.id]
    # A user fixes the data of the order of the failed disbursement and reprocesses by hand.
    Order.objects.filter(merchant=other_daily_merchant, order_creation_date=YESTERDAY).exclude(id=late_order.id).update(
        commission_fee="0.11"
    )

    call_command("retry_disbursement_package", str(package.id))

    rempel = disbursement_of(other_daily_merchant)
    assert rempel.status == COMPLETED
    assert amounts(rempel) == (Decimal("10.50"), Decimal("0.11"), Decimal("10.39"))
    assert late_order.id not in set(rempel.orders.values_list("id", flat=True))
    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert set(package.disbursements.values_list("id", flat=True)) == set(
        Disbursement.objects.filter(payment_date=PAYMENT_DATE).values_list("id", flat=True)
    )
    # The late order is in the disbursement of the next day, which the retry did not touch.
    late_order.refresh_from_db()
    assert late_order.disbursement_id == next_disbursement.id
    assert next_disbursement.package_id == next_package.id
    assert next_disbursement.has_processed_delayed_orders is True
    assert [disbursement for disbursement in snapshot()["disbursements"] if disbursement["id"] == next_disbursement.id] == next_disbursement_before
    assert [package for package in snapshot()["packages"] if package["id"] == next_package.id] == next_package_before


# --- cases 6 and 6 bis: infrastructure failure, with automatic retry ---

@pytest.fixture
def packages_with_an_infrastructure_failure(settings, daily_merchant, orders_for_all_merchants):
    settings.PACKAGE_MAX_RETRIES = 1
    # With 2 orders per package there is one package per merchant.
    settings.PACKAGE_MAX_ORDERS = 2
    packages = create_payment_day(PAYMENT_DATE)
    failing = disbursement_of(daily_merchant).package
    for package in packages:
        if package.id == failing.id:
            # The DB goes down while saving the results of padberg_group's package.
            with mock.patch(f"{SERVICE}.save_disbursement_results", side_effect=OperationalError("connection lost")):
                process_disbursement_package(package.id)
        else:
            process_disbursement_package(package.id)
    return failing


def test_infrastructure_failure_fails_only_its_package_and_can_be_retried(
    daily_merchant, other_daily_merchant, weekly_merchant, packages_with_an_infrastructure_failure
):
    """Case 6: daily and weekly merchants with orders; some packages are processed OK and another one
    fails because of infrastructure, with a possible retry.

    It checks how disbursements and packages end up, and that the check marks it to be retried.
    """
    failing = packages_with_an_infrastructure_failure

    result = check_disbursement_packages(PAYMENT_DATE, is_last_run=False)

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
    """Case 6 bis: the same as case 6, and then the automatic retry runs the process again.

    The process ends OK and the packages already COMPLETED are not processed again.
    """
    failing = packages_with_an_infrastructure_failure
    others_before = [package for package in snapshot()["packages"] if package["id"] != failing.id]
    # What the check task does: asks for the packages to retry and processes them.
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
    # The other packages are not processed again.
    others_after = [package for package in snapshot()["packages"] if package["id"] != failing.id]
    assert others_after == others_before


# --- case 7: monthly fees with disbursements in different statuses ---

def test_monthly_fees_count_every_order_of_the_month_whatever_the_state_of_its_disbursement():
    """Case 7: disbursements not processed, processed with an error and processed OK, and merchants
    without disbursements. The monthly fees of January 2023 are calculated, minimum 29.00 unless stated.

    - processed_ok: order with 10.00 of commission and a COMPLETED disbursement → fee 19.00.
    - processed_with_error: 5.00 with a FAILED disbursement → fee 24.00.
    - not_processed: 4.00 with a PENDING disbursement (paid on 2/1) → fee 25.00.
    - not_disbursed: 3.00 without a disbursement yet → fee 26.00.
    - without_orders: live and without orders → pays the whole minimum, 29.00.
    - over_minimum: 30.00 in commissions → not charged.
    - without_minimum: minimum 0 → not charged.
    - not_live_yet: live_on 2/1 → not charged for January.
    The fee is saved in MonthlyFee and is not deducted from any disbursement or order.
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
        error="Expected 2 orders and found 1.",
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
    # Nothing is deducted: disbursements, packages and orders stay the same.
    assert snapshot() == before
