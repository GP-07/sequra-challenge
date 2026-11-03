"""Monthly fees: lo que le falta a cada merchant para llegar a su minimum_monthly_fee en un mes.

amount = minimum_monthly_fee - comisiones de las orders creadas en el mes (pagadas o no). Solo se
guarda una fila si amount > 0. Queda registrada en MonthlyFee y no se descuenta de ningún
disbursement.
"""

import calendar
from datetime import date

from django.db import transaction

from core.constants import ZERO_AMOUNT
from fees.models import MonthlyFee
from merchants.models import Merchant
from orders.models import Order


def calculate_monthly_fees(month: date) -> list:
    """Calcula las monthly fees del mes que empieza en `month` (primer día del mes).

    Tres queries por mes: merchants alcanzados, comisiones por merchant y fees ya calculadas. Las fees
    que ya existen no se recalculan ni se tocan, así que correrlo dos veces no duplica nada.
    Devuelve las fees creadas.
    """
    month_start = month.replace(day=1)
    month_end = month_start.replace(day=calendar.monthrange(month_start.year, month_start.month)[1])

    merchants = Merchant.objects.subject_to_monthly_fee(month_end).values_list("id", "minimum_monthly_fee")
    commissions = Order.objects.commissions_by_merchant(month_start, month_end)
    already_calculated = set(MonthlyFee.objects.filter(month=month_start).values_list("merchant_id", flat=True))

    fees = []
    for merchant_id, minimum_monthly_fee in merchants:
        if merchant_id in already_calculated:
            continue
        merchant_commissions = commissions.get(merchant_id, ZERO_AMOUNT)
        amount = minimum_monthly_fee - merchant_commissions
        if amount > 0:
            fees.append(
                MonthlyFee(
                    merchant_id=merchant_id,
                    month=month_start,
                    commissions_amount=merchant_commissions,
                    minimum_monthly_fee=minimum_monthly_fee,
                    amount=amount,
                )
            )
    with transaction.atomic():
        MonthlyFee.objects.bulk_create(fees)
    return fees


def calculate_monthly_fees_for_range(month_from: date, month_to: date) -> list:
    """Calcula los meses de `month_from` a `month_to`, ambos incluidos (primer día de cada mes).

    Los parámetros son los meses que se cubren, no las fechas de corrida: para cubrir enero y febrero
    se pasa 2023-01-01 → 2023-02-01 (la corrida de febrero sería el 01/03).
    """
    month = month_from.replace(day=1)
    last_month = month_to.replace(day=1)
    if month > last_month:
        raise ValueError(f"month_from {month_from} is after month_to {month_to}")
    fees = []
    while month <= last_month:
        fees.extend(calculate_monthly_fees(month))
        month = date(month.year + month.month // 12, month.month % 12 + 1, 1)
    return fees
