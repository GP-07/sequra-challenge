"""Monthly fees: what each merchant is missing to reach its minimum_monthly_fee in a month.

amount = minimum_monthly_fee - commissions of the orders created in the month (paid or not). A row
is only saved if amount > 0. It is recorded in MonthlyFee and is not deducted from any
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
    """Calculates the monthly fees of the month starting on `month` (first day of the month).

    Three queries per month: merchants in scope, commissions per merchant and fees already calculated.
    Existing fees are neither recalculated nor touched, so running it twice duplicates nothing.
    Returns the created fees.
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
    """Calculates the months from `month_from` to `month_to`, both included (first day of each month).

    The parameters are the months covered, not the run dates: to cover January and February, pass
    2023-01-01 → 2023-02-01 (February's run would be on 03/01).
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
