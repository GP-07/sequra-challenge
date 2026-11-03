"""Comandos manuales de disbursements: backfill y reintento manual por id de disbursement."""

from datetime import date
from decimal import Decimal

import pytest
from django.conf import settings
from django.core.management import CommandError

from core.tests.helpers import put_in_import_dir, run_command
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.tests.factories import DisbursementPackageFactory
from disbursements.models import Disbursement, MonthlyFee
from disbursements.tests.factories import DisbursementFactory
from merchants.tests.factories import MerchantFactory
from orders.models import Order
from orders.tests.factories import OrderFactory

pytestmark = pytest.mark.django_db

# CSVs de prueba, con el mismo formato que los del challenge.
MERCHANTS_DATA_DIR = settings.BASE_DIR / "merchants" / "tests" / "data"
ORDERS_DATA_DIR = settings.BASE_DIR / "orders" / "tests" / "data"


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


def test_backfill_monthly_fees_for_range(loaded):
    run_command("calculate_monthly_fees_for_range", "--from", "2023-02", "--to", "2023-02")

    # padberg_group tiene minimum 0: no se le cobra.
    assert MonthlyFee.objects.count() == 1
    fee = MonthlyFee.objects.get(merchant__reference="deckow_gibson", month=date(2023, 2, 1))
    assert fee.commissions_amount == Decimal("0.11")
    assert fee.minimum_monthly_fee == Decimal("29.00")
    assert fee.amount == Decimal("28.89")


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
