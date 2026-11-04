from datetime import datetime, timedelta

from django.core.management import BaseCommand, CommandError
from django.utils import timezone

from orders.constants import GENERATED_ORDERS_DEFAULT_COUNT, GENERATED_ORDERS_MAX_COUNT, GENERATED_ORDERS_MIN_COUNT
from orders.services.order_generation import generate_testing_orders


def now():
    return timezone.now()


class Command(BaseCommand):
    help = (
        "Test data: creates 2 new DAILY merchants and orders for them, with random amounts covering the "
        "three commission tiers, to exercise the daily flow. Each merchant gets at least one order. In "
        "production orders would come in through a REST API."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--count",
            type=int,
            default=GENERATED_ORDERS_DEFAULT_COUNT,
            help=f"Number of orders, from {GENERATED_ORDERS_MIN_COUNT} to {GENERATED_ORDERS_MAX_COUNT} "
            f"(default {GENERATED_ORDERS_DEFAULT_COUNT})",
        )
        parser.add_argument("--date", dest="order_date", help="Order date, YYYY-MM-DD, at most today (default: yesterday)")

    def handle(self, *args, count, order_date, **options):
        today = now().date()
        order_date = parse_date(order_date) if order_date else today - timedelta(days=1)
        if not GENERATED_ORDERS_MIN_COUNT <= count <= GENERATED_ORDERS_MAX_COUNT:
            raise CommandError(f"--count must be from {GENERATED_ORDERS_MIN_COUNT} to {GENERATED_ORDERS_MAX_COUNT}.")
        if order_date > today:
            raise CommandError(f"--date {order_date} is after today ({today}).")

        result = generate_testing_orders(count, order_date)

        orders_by_merchant = {merchant.id: 0 for merchant in result.created_merchants}
        for order in result.orders:
            orders_by_merchant[order.merchant_id] += 1
        self.stdout.write(f"Orders created: {len(result.orders)}, dated {order_date}")
        for merchant in result.created_merchants:
            self.stdout.write(f"  {merchant.reference} (DAILY): {orders_by_merchant[merchant.id]} orders")
        self.stdout.write(f"They are paid by the disbursement run of {order_date + timedelta(days=1)}.")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"Invalid date '{value}': use YYYY-MM-DD.")
