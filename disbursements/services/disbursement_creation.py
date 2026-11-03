"""Creación de disbursements (opción A: la corrida del día D paga días cerrados).

- DAILY: orders del día D-1.
- WEEKLY: solo el día de la semana del live_on del merchant; orders de D-7 a D-1.

Además entran las orders atrasadas: sin disbursement y de antes de la ventana (llegaron tarde). En ese
caso el disbursement queda con has_processed_delayed_orders y se loguea un WARNING.

Exactly once: el natural_key_hash (merchant, fecha de pago) es único en la DB. Si el disbursement ya
existe no se toca, y las orders que llegaron después esperan al próximo pago.
"""

import hashlib
import logging
from datetime import date, timedelta

from django.db import transaction

from disbursements.data_classes import CreationResult
from disbursements.models import Disbursement
from merchants.models import Merchant
from orders.models import Order

logger = logging.getLogger(__name__)


def natural_key_hash(merchant_id, payment_date: date) -> str:
    """sha256 (hex, 64 caracteres) de (merchant, fecha de pago).

    Siempre da lo mismo para los mismos datos, así que el constraint único de la DB impide crear dos
    veces el mismo disbursement aunque el proceso corra dos veces a la vez.
    """
    return hashlib.sha256(f"{merchant_id}:{payment_date.isoformat()}".encode()).hexdigest()


def payment_window(payment_date: date, frequency: str) -> tuple[date, date]:
    """Primer y último día (inclusive) de las orders que paga la corrida de payment_date."""
    window_end = payment_date - timedelta(days=1)
    if frequency == Merchant.Frequency.WEEKLY:
        return payment_date - timedelta(days=7), window_end
    return window_end, window_end


def disbursement_reference(merchant_reference: str, window_start: date, window_end: date) -> str:
    if window_start == window_end:
        return f"{merchant_reference}_for_{window_end:%Y%m%d}"
    return f"{merchant_reference}_from_{window_start:%Y%m%d}_to_{window_end:%Y%m%d}"


def create_disbursements(payment_date: date, frequency: str) -> CreationResult:
    """create_disbursements_daily / weekly para una fecha de pago.

    Dos queries para todo el día (merchants y orders pendientes por merchant) y unas pocas por cada
    disbursement creado, cada uno en su propia transacción.
    """
    result = CreationResult()
    window_start, window_end = payment_window(payment_date, frequency)
    merchants = dict(Merchant.objects.to_disburse_on(payment_date, frequency).values_list("id", "reference"))
    oldest_pending = Order.objects.pending_disbursement_by_merchant(merchants, window_end)

    for merchant_id, oldest_order_date in oldest_pending.items():
        with transaction.atomic():
            disbursement, created = Disbursement.objects.get_or_create(
                natural_key_hash=natural_key_hash(merchant_id, payment_date),
                defaults={
                    "merchant_id": merchant_id,
                    "payment_date": payment_date,
                    "reference": disbursement_reference(merchants[merchant_id], window_start, window_end),
                    "has_processed_delayed_orders": oldest_order_date < window_start,
                },
            )
            if not created:
                result.skipped_existing += 1
                continue
            disbursement.order_count = Order.objects.assign_to_disbursement(merchant_id, window_end, disbursement.id)
            disbursement.save(update_fields=["order_count", "updated_at"])
        result.created.append(disbursement)
        if disbursement.has_processed_delayed_orders:
            logger.warning(
                "Disbursement %s of %s includes delayed orders (oldest from %s).",
                disbursement.reference,
                merchants[merchant_id],
                oldest_order_date,
            )
    return result


def create_disbursements_for_range(date_from: date, date_to: date) -> CreationResult:
    """Backfill: misma lógica, para cada fecha de pago del rango (inclusive), DAILY y WEEKLY."""
    result = CreationResult()
    payment_date = date_from
    while payment_date <= date_to:
        for frequency in (Merchant.Frequency.DAILY, Merchant.Frequency.WEEKLY):
            day = create_disbursements(payment_date, frequency)
            result.created.extend(day.created)
            result.skipped_existing += day.skipped_existing
        payment_date += timedelta(days=1)
    return result
