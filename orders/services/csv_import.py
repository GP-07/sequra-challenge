from decimal import Decimal, InvalidOperation
from pathlib import Path

from core.constants import CENTS
from core.csv_utils import parse_date, parse_required, read_rows
from core.data_classes import ImportResult
from core.exceptions import InvalidRow
from merchants.models import Merchant
from orders.constants import ORDER_CSV_COLUMNS, ORDER_IMPORT_BATCH_SIZE
from orders.models import Order
from orders.services.commissions import calculate_commission_fee


def import_orders(path: Path, batch_size: int = ORDER_IMPORT_BATCH_SIZE) -> ImportResult:
    """Loads the new orders of the CSV, with their commission_fee. The existing ones (by CSV id, external_id) are not touched.

    It works in batches so as not to keep the whole file in memory: per batch, one query to see which
    ids already exist and one bulk_create with the new ones. Each batch is saved on its own; if the
    load is interrupted, running it again skips what was already loaded.

    Invalid rows are skipped and reported with their line number. An id repeated within the same
    batch is invalid; if it is repeated in another batch, it counts as already loaded.
    """
    result = ImportResult()
    # 50 merchants: loaded once in memory instead of one query per row.
    merchant_ids = dict(Merchant.objects.values_list("reference", "id"))
    batch = {}
    for line_number, row in read_rows(path, ORDER_CSV_COLUMNS):
        try:
            order = parse_order(row, merchant_ids)
            if order.external_id in batch:
                raise InvalidRow(f"id '{order.external_id}' repeated in the file")
        except InvalidRow as error:
            result.invalid.append((line_number, str(error)))
            continue
        batch[order.external_id] = order
        if len(batch) >= batch_size:
            save_batch(batch, result)
            batch = {}
    save_batch(batch, result)
    return result


def save_batch(batch: dict, result: ImportResult) -> None:
    if not batch:
        return
    existing_ids = set(Order.objects.filter(external_id__in=batch).values_list("external_id", flat=True))
    new_orders = [order for order_id, order in batch.items() if order_id not in existing_ids]
    Order.objects.bulk_create(new_orders)
    result.created += len(new_orders)
    result.skipped_existing += len(existing_ids)


def parse_order(row: dict, merchant_ids: dict) -> Order:
    reference = parse_required(row["merchant_reference"], "merchant_reference")
    if reference not in merchant_ids:
        raise InvalidRow(f"unknown merchant '{reference}'")
    amount = parse_amount(row["amount"])
    return Order(
        external_id=parse_order_id(row["id"]),
        merchant_id=merchant_ids[reference],
        amount=amount,
        commission_fee=calculate_commission_fee(amount),
        order_creation_date=parse_date(row["created_at"], "created_at"),
    )


def parse_order_id(value):
    value = parse_required(value, "id")
    if len(value) > Order._meta.get_field("external_id").max_length:
        raise InvalidRow(f"invalid id '{value}'")
    return value


def parse_amount(value):
    """Non-negative amount with up to 2 decimals; an amount that comes with more is not rounded."""
    value = parse_required(value, "amount")
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise InvalidRow(f"invalid amount '{value}'")
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise InvalidRow(f"invalid amount '{value}'")
    return amount.quantize(CENTS)
