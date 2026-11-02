"""Comandos manuales: carga de CSV, generate_orders, backfill y reintento manual."""

import shutil
from datetime import date
from decimal import Decimal
from io import StringIO
from pathlib import Path

import pytest
from django.core.management import CommandError, call_command

from disbursements.models import Disbursement, DisbursementPackage, Merchant, MonthlyFee, Order
from disbursements.tests.factories import DisbursementFactory, DisbursementPackageFactory, MerchantFactory, OrderFactory

pytestmark = pytest.mark.django_db

# CSVs de prueba, con el mismo formato que los del challenge.
DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def import_dir(tmp_path, settings):
    settings.IMPORT_DIR = tmp_path
    return tmp_path


def put_in_import_dir(import_dir, data_file, name):
    """Copia un CSV de tests/data a la carpeta de importación con el nombre que espera el comando."""
    shutil.copy(DATA_DIR / data_file, import_dir / name)


@pytest.fixture
def merchants_csv(import_dir):
    put_in_import_dir(import_dir, "merchants.csv", "merchants.csv")


@pytest.fixture
def orders_csv(import_dir):
    put_in_import_dir(import_dir, "orders.csv", "orders.csv")


def run(*args):
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()


# --- load merchants ---

def test_load_merchants_missing_file_asks_to_put_it_in_the_import_folder(import_dir):
    with pytest.raises(CommandError) as error:
        run("load_merchants", "merchants.csv")
    assert str(import_dir) in str(error.value)


def test_load_merchants_loads_the_csv_from_the_import_folder(merchants_csv):
    output = run("load_merchants", "merchants.csv")

    merchant = Merchant.objects.get(reference="deckow_gibson")
    assert merchant.disbursement_frequency == Merchant.Frequency.WEEKLY
    assert merchant.live_on == date(2023, 2, 1)
    assert merchant.minimum_monthly_fee == Decimal("29.00")
    assert "2" in output


def test_load_merchants_is_idempotent_by_id(merchants_csv):
    run("load_merchants", "merchants.csv")
    run("load_merchants", "merchants.csv")

    assert Merchant.objects.count() == 2


def test_load_merchants_invalid_rows_are_skipped_and_reported(import_dir):
    # Uuid, frecuencia, fecha y minimum negativo inválidos.
    put_in_import_dir(import_dir, "merchants_with_invalid_rows.csv", "merchants.csv")

    output = run("load_merchants", "merchants.csv")

    # padberg_group tiene minimum 0.0: es válido y se carga.
    assert set(Merchant.objects.values_list("reference", flat=True)) == {"padberg_group", "deckow_gibson"}
    assert "invalid" in output.lower()


def test_load_merchants_missing_minimum_is_loaded_as_zero(import_dir):
    put_in_import_dir(import_dir, "merchants_with_missing_minimum.csv", "merchants.csv")

    run("load_merchants", "merchants.csv")

    merchant = Merchant.objects.get(reference="no_minimum")
    assert merchant.minimum_monthly_fee == Decimal("0.00")


# --- load orders ---

@pytest.fixture
def merchants(merchants_csv):
    run("load_merchants", "merchants.csv")


def test_load_orders_missing_file_asks_to_put_it_in_the_import_folder(merchants, import_dir):
    with pytest.raises(CommandError) as error:
        run("load_orders", "orders.csv")
    assert str(import_dir) in str(error.value)


def test_load_orders_loads_orders_with_their_commission(merchants, orders_csv):
    run("load_orders", "orders.csv")

    assert Order.objects.count() == 3
    assert Order.objects.get(id="e653f3e14bc4").commission_fee == Decimal("0.97")
    assert Order.objects.get(id="0f2f0a1c5b1a").commission_fee == Decimal("0.11")
    assert not Order.objects.filter(disbursement__isnull=False).exists()


def test_load_orders_is_idempotent_by_id(merchants, orders_csv):
    run("load_orders", "orders.csv")
    run("load_orders", "orders.csv")

    assert Order.objects.count() == 3


def test_load_orders_invalid_rows_are_skipped_and_reported(merchants, import_dir):
    # Merchant desconocido, monto negativo, monto no numérico y fecha inválidos.
    put_in_import_dir(import_dir, "orders_with_invalid_rows.csv", "orders.csv")

    output = run("load_orders", "orders.csv")

    assert Order.objects.count() == 3
    assert "invalid" in output.lower()


# --- generate orders ---

def test_generate_orders_creates_random_orders_for_existing_merchants():
    MerchantFactory(reference="padberg_group")

    run("generate_orders", "--count", "5", "--date", "2023-02-07")

    assert Order.objects.filter(created_at=date(2023, 2, 7)).count() == 5
    assert not Order.objects.filter(commission_fee__lte=0).exists()


# --- backfill ---

@pytest.fixture
def loaded(merchants_csv, orders_csv):
    run("load_merchants", "merchants.csv")
    run("load_orders", "orders.csv")


def test_backfill_creates_packages_and_processes_them(loaded):
    # deckow_gibson es WEEKLY desde un miércoles: su primer pago es el 8/2.
    output = run("create_disbursements_for_range", "--from", "2023-02-01", "--to", "2023-02-08")

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


def test_backfill_monthly_fees_for_range(loaded):
    run("calculate_monthly_fees_for_range", "--from", "2023-02", "--to", "2023-02")

    # padberg_group tiene minimum 0: no se le cobra.
    assert MonthlyFee.objects.count() == 1
    fee = MonthlyFee.objects.get(merchant__reference="deckow_gibson", month=date(2023, 2, 1))
    assert fee.commissions_amount == Decimal("0.11")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("28.89")


# --- retry disbursement package ---

def test_retry_reprocesses_a_non_retryable_package_after_fixing_the_data():
    # Así queda un paquete tras una falla de datos: FAILED no retryable, porque reintentar
    # automáticamente no sirve. Alguien ya corrigió el dato (order_count vuelve a coincidir) y lo
    # reprocesa a mano: el retry manual no mira is_retryable.
    merchant = MerchantFactory(reference="padberg_group")
    order = OrderFactory(merchant=merchant, created_at=date(2023, 2, 7))
    disbursement = DisbursementFactory(
        merchant=merchant,
        payment_date=date(2023, 2, 8),
        orders=[order],
        status=Disbursement.Status.FAILED,
        error="Se esperaban 2 orders y hay 1.",
    )
    package = DisbursementPackageFactory(
        disbursements=[disbursement], status=DisbursementPackage.Status.FAILED, attempts=1, is_retryable=False
    )

    run("retry_disbursement_package", str(package.id))

    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    disbursement.refresh_from_db()
    assert disbursement.status == Disbursement.Status.COMPLETED
    assert disbursement.error == ""


def test_retry_unknown_package():
    with pytest.raises(CommandError):
        run("retry_disbursement_package", "999999")


def test_retry_completed_package_is_skipped_and_reported():
    merchant = MerchantFactory(reference="padberg_group")
    order = OrderFactory(merchant=merchant, created_at=date(2023, 2, 7))
    disbursement = DisbursementFactory(
        merchant=merchant, payment_date=date(2023, 2, 8), orders=[order], status=Disbursement.Status.COMPLETED
    )
    package = DisbursementPackageFactory(
        disbursements=[disbursement], status=DisbursementPackage.Status.COMPLETED, attempts=1
    )

    output = run("retry_disbursement_package", str(package.id))

    assert "already completed" in output.lower()
    package.refresh_from_db()
    assert package.status == DisbursementPackage.Status.COMPLETED
    assert package.attempts == 1


# --- retry disbursements ---

def test_retry_disbursements_reprocesses_by_id_and_reports_what_was_skipped():
    # padberg_group falló por un dato que ya se corrigió; deckow_gibson ya estaba COMPLETED.
    padberg = MerchantFactory(reference="padberg_group")
    failed = DisbursementFactory(
        merchant=padberg,
        payment_date=date(2023, 2, 8),
        orders=[OrderFactory(merchant=padberg, created_at=date(2023, 2, 7), amount="10.50", commission_fee="0.11")],
        status=Disbursement.Status.FAILED,
        error="Se esperaban 2 orders y hay 1.",
    )
    deckow = MerchantFactory(reference="deckow_gibson")
    completed = DisbursementFactory(
        merchant=deckow,
        payment_date=date(2023, 2, 8),
        orders=[OrderFactory(merchant=deckow, created_at=date(2023, 2, 7))],
        status=Disbursement.Status.COMPLETED,
    )
    DisbursementPackageFactory(
        disbursements=[failed, completed], status=DisbursementPackage.Status.FAILED, attempts=1, is_retryable=False
    )

    output = run("retry_disbursements", str(failed.id), str(completed.id), "999999")

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
        run("retry_disbursements")
