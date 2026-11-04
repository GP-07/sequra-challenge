"""Disbursement creation (option A: the run of day D pays closed days).

- DAILY: orders of day D-1.
- WEEKLY: only on the weekday of the merchant's live_on; orders from D-7 to D-1.

Delayed orders are included too: without a disbursement and from before the window (they arrived
late). In that case the disbursement gets has_processed_delayed_orders and a WARNING is logged.

Exactly once: the natural_key_hash (merchant, payment date) is unique in the DB. If the disbursement
already exists it is not touched, and the orders that arrived later wait for the next payment.

Two strategies with the same result:
- create_disbursements (daily run): one merchant per transaction. If one fails, the others go on.
- create_disbursements_in_bulk (historical backfill): one transaction and a few queries per day,
  whatever the number of merchants. If anything fails the whole day is rolled back, and if another
  run creates any of the same disbursements at the same time, the unique constraint stops the day
  with an IntegrityError (there are never duplicates). Accepted because the backfill is run by hand,
  once, and it is idempotent: running it again skips what already exists.
"""

import hashlib
import logging
from datetime import date, timedelta

from django.db import transaction

from disbursements.data_classes import CreationResult
from disbursements.exceptions import DayCreationFailed
from disbursements.models import Disbursement
from merchants.models import Merchant
from orders.models import Order

logger = logging.getLogger(__name__)


def natural_key_hash(merchant_id, payment_date: date) -> str:
    """sha256 (hex, 64 characters) of (merchant, payment date).

    It is always the same for the same data, so the DB unique constraint prevents creating the same
    disbursement twice even if the process runs twice at the same time.
    """
    return hashlib.sha256(f"{merchant_id}:{payment_date.isoformat()}".encode()).hexdigest()


def payment_window(payment_date: date, frequency: str) -> tuple[date, date]:
    """First and last day (inclusive) of the orders paid by the run of payment_date."""
    window_end = payment_date - timedelta(days=1)
    if frequency == Merchant.Frequency.WEEKLY:
        return payment_date - timedelta(days=7), window_end
    return window_end, window_end


def disbursement_reference(merchant_reference: str, window_start: date, window_end: date) -> str:
    if window_start == window_end:
        return f"{merchant_reference}_for_{window_end:%Y%m%d}"
    return f"{merchant_reference}_from_{window_start:%Y%m%d}_to_{window_end:%Y%m%d}"


def disbursement_fields(merchant_id, merchant_reference: str, payment_date: date, frequency: str, oldest_order_date: date) -> dict:
    """Fields of a new disbursement, except natural_key_hash."""
    window_start, window_end = payment_window(payment_date, frequency)
    return {
        "merchant_id": merchant_id,
        "payment_date": payment_date,
        "reference": disbursement_reference(merchant_reference, window_start, window_end),
        "has_processed_delayed_orders": oldest_order_date < window_start,
    }


def log_delayed_orders(disbursement: Disbursement, merchant_reference: str, oldest_order_date: date) -> None:
    if disbursement.has_processed_delayed_orders:
        logger.warning(
            "Disbursement %s of %s includes delayed orders (oldest from %s).",
            disbursement.reference,
            merchant_reference,
            oldest_order_date,
        )


def create_disbursements(payment_date: date, frequency: str) -> CreationResult:
    """create_disbursements_daily / weekly for a payment date (daily run).

    Two queries for the whole day (merchants and pending orders per merchant) and a few for each
    created disbursement, each one in its own transaction.
    """
    result = CreationResult()
    _, window_end = payment_window(payment_date, frequency)
    merchants = dict(Merchant.objects.to_disburse_on(payment_date, frequency).values_list("id", "reference"))
    oldest_pending = Order.objects.pending_disbursement_by_merchant(merchants, window_end)

    for merchant_id, oldest_order_date in oldest_pending.items():
        with transaction.atomic():
            disbursement, created = Disbursement.objects.get_or_create(
                natural_key_hash=natural_key_hash(merchant_id, payment_date),
                defaults=disbursement_fields(merchant_id, merchants[merchant_id], payment_date, frequency, oldest_order_date),
            )
            if not created:
                result.skipped_existing += 1
                continue
            Order.objects.assign_to_disbursement(merchant_id, window_end, disbursement.id)
        result.created.append(disbursement)
        log_delayed_orders(disbursement, merchants[merchant_id], oldest_order_date)
    return result


def create_disbursements_in_bulk(payment_date: date, frequency: str) -> CreationResult:
    """The same as create_disbursements, in bulk and in a single transaction (historical backfill).

    Five queries per day, whatever the number of merchants: merchants, pending orders, existing
    disbursements, insert of the new ones and assignment of orders.
    """
    result = CreationResult()
    _, window_end = payment_window(payment_date, frequency)
    merchants = dict(Merchant.objects.to_disburse_on(payment_date, frequency).values_list("id", "reference"))
    oldest_pending = Order.objects.pending_disbursement_by_merchant(merchants, window_end)
    if not oldest_pending:
        return result

    with transaction.atomic():
        hashes = {merchant_id: natural_key_hash(merchant_id, payment_date) for merchant_id in oldest_pending}
        existing = set(Disbursement.objects.filter(natural_key_hash__in=hashes.values()).values_list("natural_key_hash", flat=True))
        to_create = [
            Disbursement(
                natural_key_hash=hashes[merchant_id],
                **disbursement_fields(merchant_id, merchants[merchant_id], payment_date, frequency, oldest_order_date),
            )
            for merchant_id, oldest_order_date in oldest_pending.items()
            if hashes[merchant_id] not in existing
        ]
        result.skipped_existing = len(existing)
        created = Disbursement.objects.bulk_create(to_create)

        Order.objects.assign_to_disbursements({disbursement.merchant_id: disbursement.id for disbursement in created}, window_end)

    result.created = created
    for disbursement in created:
        log_delayed_orders(disbursement, merchants[disbursement.merchant_id], oldest_pending[disbursement.merchant_id])
    return result


def create_disbursements_for_range(date_from: date, date_to: date) -> CreationResult:
    """Historical backfill: for each payment date of the range (inclusive), DAILY and WEEKLY, in bulk.

    If a day fails, it stops: the previous days are already saved and DayCreationFailed is raised
    with the date. Running it again is safe, because it skips what already exists.
    """
    result = CreationResult()
    payment_date = date_from
    while payment_date <= date_to:
        for frequency in (Merchant.Frequency.DAILY, Merchant.Frequency.WEEKLY):
            try:
                day = create_disbursements_in_bulk(payment_date, frequency)
            except Exception as error:
                raise DayCreationFailed(payment_date, frequency, len(result.created)) from error
            result.created.extend(day.created)
            result.skipped_existing += day.skipped_existing
        payment_date += timedelta(days=1)
    return result
