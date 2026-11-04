"""Orders with random data, for testing the daily flow (generate_testing_orders command).

In production, orders would come in through a REST API, with serializers validating the input; this
is only a way to feed the daily flow with fresh data.
"""

import random
import uuid
from datetime import date, timedelta
from decimal import Decimal

from django.db import transaction

from merchants.services.merchant_generation import create_random_merchant
from orders.constants import GENERATED_MERCHANTS_COUNT, GENERATED_ORDER_AMOUNT_RANGES
from orders.data_classes import GenerationResult
from orders.models import Order
from orders.services.commissions import calculate_commission_fee


def generate_testing_orders(count: int, order_date: date) -> GenerationResult:
    """Creates GENERATED_MERCHANTS_COUNT new DAILY merchants and `count` orders for them, in one transaction.

    The merchants are live since the day before `order_date`, so the run of the next day pays them.
    Each merchant gets at least one order, and the rest are spread at random. Amounts are random,
    taking the commission tiers in turns, so with 3 orders or more every tier is covered.
    """
    result = GenerationResult()
    with transaction.atomic():
        result.created_merchants = [
            create_random_merchant(order_date - timedelta(days=1)) for _ in range(GENERATED_MERCHANTS_COUNT)
        ]
        merchant_ids = [merchant.id for merchant in result.created_merchants]
        result.orders = Order.objects.bulk_create(
            [random_order(merchant_for_order(merchant_ids, index), order_date, index) for index in range(count)]
        )
    return result


def merchant_for_order(merchant_ids: list[int], index: int) -> int:
    """The first orders go one to each merchant, so none is left without orders; the rest at random."""
    if index < len(merchant_ids):
        return merchant_ids[index]
    return random.choice(merchant_ids)


def random_order(merchant_id: int, order_date: date, index: int) -> Order:
    amount = random_amount(*GENERATED_ORDER_AMOUNT_RANGES[index % len(GENERATED_ORDER_AMOUNT_RANGES)])
    return Order(
        external_id=uuid.uuid4().hex[:12],
        merchant_id=merchant_id,
        amount=amount,
        commission_fee=calculate_commission_fee(amount),
        order_creation_date=order_date,
    )


def random_amount(minimum: Decimal, maximum: Decimal) -> Decimal:
    """Random amount in cents between minimum and maximum, both included."""
    cents = random.randint(int(minimum * 100), int(maximum * 100))
    return Decimal(cents) / 100
