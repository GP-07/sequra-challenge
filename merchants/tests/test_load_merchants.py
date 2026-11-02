"""load_merchants: carga de merchants desde un CSV de la carpeta de importación."""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest
from django.core.management import CommandError

from core.tests.helpers import put_in_import_dir, run_command
from merchants.models import Merchant

pytestmark = pytest.mark.django_db

# CSVs de prueba, con el mismo formato que los del challenge.
DATA_DIR = Path(__file__).parent / "data"


@pytest.fixture
def merchants_csv(import_dir):
    put_in_import_dir(import_dir, DATA_DIR / "merchants.csv", "merchants.csv")


def test_load_merchants_missing_file_asks_to_put_it_in_the_import_folder(import_dir):
    with pytest.raises(CommandError) as error:
        run_command("load_merchants", "merchants.csv")
    assert str(import_dir) in str(error.value)


def test_load_merchants_loads_the_csv_from_the_import_folder(merchants_csv):
    output = run_command("load_merchants", "merchants.csv")

    merchant = Merchant.objects.get(reference="deckow_gibson")
    assert merchant.disbursement_frequency == Merchant.Frequency.WEEKLY
    assert merchant.live_on == date(2023, 2, 1)
    assert merchant.minimum_monthly_fee == Decimal("29.00")
    assert "2" in output


def test_load_merchants_is_idempotent_by_id(merchants_csv):
    run_command("load_merchants", "merchants.csv")
    run_command("load_merchants", "merchants.csv")

    assert Merchant.objects.count() == 2


def test_load_merchants_invalid_rows_are_skipped_and_reported(import_dir):
    # Uuid, frecuencia, fecha y minimum negativo inválidos.
    put_in_import_dir(import_dir, DATA_DIR / "merchants_with_invalid_rows.csv", "merchants.csv")

    output = run_command("load_merchants", "merchants.csv")

    # padberg_group tiene minimum 0.0: es válido y se carga.
    assert set(Merchant.objects.values_list("reference", flat=True)) == {"padberg_group", "deckow_gibson"}
    assert "invalid" in output.lower()


def test_load_merchants_missing_minimum_is_loaded_as_zero(import_dir):
    put_in_import_dir(import_dir, DATA_DIR / "merchants_with_missing_minimum.csv", "merchants.csv")

    run_command("load_merchants", "merchants.csv")

    merchant = Merchant.objects.get(reference="no_minimum")
    assert merchant.minimum_monthly_fee == Decimal("0.00")
