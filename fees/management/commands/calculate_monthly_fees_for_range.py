from datetime import datetime

from django.core.management import BaseCommand, CommandError

from fees.services.monthly_fees import calculate_monthly_fees_for_range


class Command(BaseCommand):
    help = (
        "Calculates the monthly fees of every month from --from to --to, both included (backfill). "
        "Monthly fees already calculated are left untouched."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="month_from", required=True, help="First month to cover, YYYY-MM")
        parser.add_argument("--to", dest="month_to", required=True, help="Last month to cover, YYYY-MM")

    def handle(self, *args, month_from, month_to, **options):
        first_month = parse_month(month_from)
        last_month = parse_month(month_to)
        if first_month > last_month:
            raise CommandError(f"--from {month_from} is after --to {month_to}.")

        fees = calculate_monthly_fees_for_range(first_month, last_month)

        self.stdout.write(f"Monthly fees created: {len(fees)}")


def parse_month(value):
    try:
        return datetime.strptime(value, "%Y-%m").date()
    except ValueError:
        raise CommandError(f"Invalid month '{value}': use YYYY-MM.")
