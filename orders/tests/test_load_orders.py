"""load_orders: carga de orders desde un CSV de la carpeta de importación."""

from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import CommandError

from core.tests.helpers import put_in_import_dir, run_command
from merchants.tests.factories import MerchantFactory
from orders.models import Order

pytestmark = pytest.mark.django_db

# CSVs de prueba, con el mismo formato que los del challenge.
DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def merchants():
    # Los merchants a los que apuntan los CSV de orders.
    MerchantFactory(reference="padberg_group")
    MerchantFactory(reference="deckow_gibson")


@pytest.fixture
def orders_csv(import_dir):
    put_in_import_dir(import_dir, DATA_DIR / "orders.csv", "orders.csv")


def test_load_orders_missing_file_asks_to_put_it_in_the_import_folder(merchants, import_dir):
    with pytest.raises(CommandError) as error:
        run_command("load_orders", "orders.csv")
    assert str(import_dir) in str(error.value)


def test_load_orders_loads_orders_with_their_commission(merchants, orders_csv):
    run_command("load_orders", "orders.csv")

    assert Order.objects.count() == 3
    assert Order.objects.get(id="e653f3e14bc4").commission_fee == Decimal("0.97")
    assert Order.objects.get(id="0f2f0a1c5b1a").commission_fee == Decimal("0.11")
    assert not Order.objects.filter(disbursement__isnull=False).exists()


def test_load_orders_is_idempotent_by_id(merchants, orders_csv):
    run_command("load_orders", "orders.csv")
    run_command("load_orders", "orders.csv")

    assert Order.objects.count() == 3


def test_load_orders_invalid_rows_are_skipped_and_reported(merchants, import_dir):
    # Merchant desconocido, monto negativo, monto no numérico y fecha inválidos.
    put_in_import_dir(import_dir, DATA_DIR / "orders_with_invalid_rows.csv", "orders.csv")

    output = run_command("load_orders", "orders.csv")

    assert Order.objects.count() == 3
    assert "invalid" in output.lower()
