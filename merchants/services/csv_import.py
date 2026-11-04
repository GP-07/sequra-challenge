from decimal import Decimal, InvalidOperation
from pathlib import Path

from django.db import transaction

from core.constants import CENTS
from core.csv_utils import parse_date, parse_email, parse_required, parse_uuid, read_rows
from core.data_classes import ImportResult
from core.exceptions import InvalidRow
from merchants.constants import MERCHANT_CSV_COLUMNS
from merchants.models import Merchant


def import_merchants(path: Path) -> ImportResult:
    """Loads the new merchants of the CSV. The existing ones (by CSV id, external_id) are not touched.

    Invalid rows are skipped and reported with their line number; they do not stop loading the rest.
    """
    result = ImportResult()
    parsed = {}  # external_id → (line number, merchant)
    references = set()
    for line_number, row in read_rows(path, MERCHANT_CSV_COLUMNS):
        try:
            merchant = parse_merchant(row)
            if merchant.external_id in parsed or merchant.reference in references:
                raise InvalidRow("id or reference repeated in the file")
        except InvalidRow as error:
            result.invalid.append((line_number, str(error)))
            continue
        parsed[merchant.external_id] = (line_number, merchant)
        references.add(merchant.reference)

    # Two queries for the whole file, not one per row.
    existing_ids = set(Merchant.objects.filter(external_id__in=parsed).values_list("external_id", flat=True))
    used_references = set(Merchant.objects.filter(reference__in=references).values_list("reference", flat=True))
    new_merchants = []
    for line_number, merchant in parsed.values():
        if merchant.external_id in existing_ids:
            result.skipped_existing += 1
        elif merchant.reference in used_references:
            result.invalid.append((line_number, f"reference '{merchant.reference}' already used by another merchant"))
        else:
            new_merchants.append(merchant)

    with transaction.atomic():
        Merchant.objects.bulk_create(new_merchants)
    result.created = len(new_merchants)
    return result


def parse_merchant(row: dict) -> Merchant:
    return Merchant(
        external_id=parse_uuid(row["id"]),
        reference=parse_required(row["reference"], "reference"),
        email=parse_email(row["email"]),
        live_on=parse_date(row["live_on"], "live_on"),
        disbursement_frequency=parse_frequency(row["disbursement_frequency"]),
        minimum_monthly_fee=parse_minimum_monthly_fee(row["minimum_monthly_fee"]),
    )


def parse_frequency(value):
    value = (value or "").strip()
    if value not in Merchant.Frequency.values:
        raise InvalidRow(f"invalid disbursement_frequency '{value}'")
    return value


def parse_minimum_monthly_fee(value):
    """Empty is loaded as 0; negative is invalid."""
    value = (value or "").strip()
    if not value:
        return Decimal("0.00")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise InvalidRow(f"invalid minimum_monthly_fee '{value}'")
    if not amount.is_finite() or amount < 0:
        raise InvalidRow(f"invalid minimum_monthly_fee '{value}'")
    return amount.quantize(CENTS)
