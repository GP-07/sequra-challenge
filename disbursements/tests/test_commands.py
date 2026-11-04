"""Comandos manuales de disbursements: backfill y reintento manual por id de disbursement."""

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest import mock

import pytest
from django.conf import settings
from django.core.management import CommandError
from django.db import OperationalError

from core.tests.helpers import put_in_import_dir, run_command
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement
from disbursements.services import disbursement_creation
from disbursements.tests.factories import DisbursementFactory
from merchants.models import Merchant
from merchants.tests.factories import MerchantFactory
from orders.models import Order
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

# CSVs de prueba, con el mismo formato que los del challenge.
MERCHANTS_DATA_DIR = settings.BASE_DIR / "merchants" / "tests" / "data"
ORDERS_DATA_DIR = settings.BASE_DIR / "orders" / "tests" / "data"
COMMAND = "disbursements.management.commands.create_disbursements_for_range"


@pytest.fixture
def merchants_csv(import_dir):
    put_in_import_dir(import_dir, MERCHANTS_DATA_DIR / "merchants.csv", "merchants.csv")


@pytest.fixture
def orders_csv(import_dir):
    put_in_import_dir(import_dir, ORDERS_DATA_DIR / "orders.csv", "orders.csv")


# --- backfill ---

@pytest.fixture
def loaded(merchants_csv, orders_csv):
    run_command("load_merchants", "merchants.csv")
    run_command("load_orders", "orders.csv")


def test_backfill_creates_packages_and_processes_them(loaded):
    # deckow_gibson es WEEKLY desde un miércoles: su primer pago es el 8/2.
    output = run_command("create_disbursements_for_range", "--from", "2023-02-01", "--to", "2023-02-08")

    assert set(Disbursement.objects.values_list("reference", flat=True)) == {
        "padberg_group_for_20230201",
        "deckow_gibson_from_20230201_to_20230207",
    }
    assert not Order.objects.filter(disbursement__isnull=True).exists()
    assert DisbursementPackage.objects.exists()
    # En los tests huey corre en modo immediate: los process ya terminaron.
    assert not Disbursement.objects.exclude(status=Disbursement.Status.COMPLETED).exists()
    # El comando termina al encolar los paquetes e informa qué armó.
    assert "Disbursements created: 2" in output
    assert "Packages enqueued: 1" in output
    package = DisbursementPackage.objects.get(disbursements__reference="padberg_group_for_20230201")
    assert f"  enqueued: {package.id}" in output
    assert "check_package_status --from 2023-02-01 --to 2023-02-08" in output


def test_backfill_run_twice_creates_and_enqueues_nothing_new(loaded):
    run_command("create_disbursements_for_range", "--from", "2023-02-01", "--to", "2023-02-08")

    output = run_command("create_disbursements_for_range", "--from", "2023-02-01", "--to", "2023-02-08")

    assert Disbursement.objects.count() == 2
    assert DisbursementPackage.objects.count() == 1
    assert "Disbursements created: 0" in output
    assert "Packages enqueued: 0" in output
    assert "Packages from previous runs" not in output


@pytest.mark.parametrize(
    ("date_from", "date_to", "message"),
    (
        ("2023-02-08", "2023-02-01", "is after --to"),
        ("2023-02-01", "2023-02-31", "Invalid date"),
        ("01/02/2023", "2023-02-08", "Invalid date"),
        # Hoy (fijado en el test) es 2023-02-08: el 9 todavía no cerró.
        ("2023-02-01", "2023-02-09", "is after today"),
    ),
)
def test_backfill_rejects_invalid_ranges(date_from, date_to, message):
    with mock.patch(f"{COMMAND}.timezone.now", return_value=datetime(2023, 2, 8, 10, 0, tzinfo=timezone.utc)):
        with pytest.raises(CommandError, match=message):
            run_command("create_disbursements_for_range", "--from", date_from, "--to", date_to)

    assert not Disbursement.objects.exists()


def test_backfill_stops_at_the_day_that_fails_and_keeps_the_previous_days():
    merchant = MerchantFactory(reference="padberg_group", disbursement_frequency=Merchant.Frequency.DAILY)
    for day in (1, 2, 3):
        OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, day))

    # Se crea de verdad el 2/2 (DAILY y WEEKLY) y falla la tercera llamada: el 2/3 DAILY.
    with mock.patch.object(
        disbursement_creation,
        "create_disbursements_in_bulk",
        wraps=disbursement_creation.create_disbursements_in_bulk,
        side_effect=[mock.DEFAULT, mock.DEFAULT, OperationalError("connection lost")],
    ):
        with pytest.raises(CommandError) as error:
            run_command("create_disbursements_for_range", "--from", "2023-02-02", "--to", "2023-02-04")

    assert "payment date 2023-02-03 failed" in str(error.value)
    assert "connection lost" in str(error.value)
    assert "Disbursements created before it: 1" in str(error.value)
    # El 2/2 quedó creado y sin paquete: el comando no arma paquetes si falla la creación.
    assert list(Disbursement.objects.values_list("payment_date", "package_id")) == [(date(2023, 2, 2), None)]
    assert not DisbursementPackage.objects.exists()


def test_backfill_reports_disbursements_that_require_attention(settings):
    settings.PACKAGE_MAX_ORDERS = 1
    merchant = MerchantFactory(reference="padberg_group", disbursement_frequency=Merchant.Frequency.DAILY)
    OrderFactory.create_batch(2, merchant=merchant, order_creation_date=date(2023, 2, 1))

    output = run_command("create_disbursements_for_range", "--from", "2023-02-02", "--to", "2023-02-02")

    disbursement = Disbursement.objects.get(merchant=merchant, payment_date=date(2023, 2, 2))
    assert disbursement.status == Disbursement.Status.REQUIRES_ATTENTION
    assert "Packages enqueued: 0" in output
    assert "Requires attention (too many orders for a package): 1" in output
    assert "  padberg_group_for_20230201" in output


def test_backfill_reports_unfinished_packages_of_previous_runs_without_enqueuing_them():
    merchant = MerchantFactory(reference="padberg_group")
    previous = DisbursementFactory(
        merchant=merchant,
        payment_date=date(2023, 2, 2),
        orders=[OrderFactory(merchant=merchant, order_creation_date=date(2023, 2, 1))],
        status=Disbursement.Status.FAILED,
    )
    package = DisbursementPackageFactory(disbursements=[previous], status=DisbursementPackage.Status.FAILED, attempts=1)

    output = run_command("create_disbursements_for_range", "--from", "2023-02-02", "--to", "2023-02-03")

    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.FAILED
    assert package.attempts == 1
    assert "Packages from previous runs not completed (PENDING or FAILED): 1" in output
    assert f"  {package.id}" in output


# --- retry disbursements ---

def test_retry_disbursements_reprocesses_by_id_and_reports_what_was_skipped():
    # padberg_group falló por un dato que ya se corrigió; deckow_gibson ya estaba COMPLETED.
    padberg = MerchantFactory(reference="padberg_group")
    failed = DisbursementFactory(
        merchant=padberg,
        payment_date=date(2023, 2, 8),
        orders=[OrderFactory(merchant=padberg, order_creation_date=date(2023, 2, 7), amount="10.50", commission_fee="0.11")],
        status=Disbursement.Status.FAILED,
        error="Expected 2 orders but found 1.",
        is_retryable=False,
    )
    deckow = MerchantFactory(reference="deckow_gibson")
    completed = DisbursementFactory(
        merchant=deckow,
        payment_date=date(2023, 2, 8),
        orders=[OrderFactory(merchant=deckow, order_creation_date=date(2023, 2, 7))],
        status=Disbursement.Status.COMPLETED,
    )
    DisbursementPackageFactory(
        disbursements=[failed, completed], status=DisbursementPackage.Status.FAILED, attempts=1
    )

    output = run_command("retry_disbursements", str(failed.id), str(completed.id), "999999")

    failed.refresh_from_db()
    assert failed.status == Disbursement.Status.COMPLETED
    assert failed.error == ""
    assert (failed.gross_amount, failed.commission_fee_amount, failed.disbursed_amount) == (
        Decimal("10.50"),
        Decimal("0.11"),
        Decimal("10.39"),
    )
    assert "Reprocessed: 1" in output
    assert "Skipped (already completed): 1" in output
    assert "Not found: 1" in output


def test_retry_disbursements_requires_at_least_one_id():
    with pytest.raises(CommandError):
        run_command("retry_disbursements")
