from datetime import datetime

from django.core.management import BaseCommand, CommandError

from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_status import package_ids_for_payment_dates, package_statuses


class Command(BaseCommand):
    help = (
        "Shows how many of the given packages are pending, processing, failed or completed: by package id "
        "(as printed by create_disbursements_for_range) or by the payment dates of their disbursements "
        "(--from and --to, the same range as the backfill)."
    )

    def add_arguments(self, parser):
        parser.add_argument("package_ids", nargs="*", type=int, help="Ids of the packages")
        parser.add_argument("--from", dest="date_from", help="First payment date, YYYY-MM-DD")
        parser.add_argument("--to", dest="date_to", help="Last payment date, YYYY-MM-DD")

    def handle(self, *args, package_ids, date_from, date_to, **options):
        by_dates = date_from is not None or date_to is not None
        if by_dates and package_ids:
            raise CommandError("Give either package ids or --from and --to, not both.")
        if by_dates:
            if date_from is None or date_to is None:
                raise CommandError("--from and --to go together.")
            package_ids = package_ids_for_payment_dates(parse_date(date_from), parse_date(date_to))
        elif not package_ids:
            raise CommandError("Give package ids, or --from and --to.")

        statuses = package_statuses(package_ids)

        self.stdout.write(f"Packages: {len(set(package_ids))}")
        for status in DisbursementPackage.Status.values:
            self.stdout.write(f"{status.capitalize()}: {len(statuses[status])}")
        if statuses.get("NOT_FOUND"):
            self.stdout.write(f"Not found: {len(statuses['NOT_FOUND'])}")
        for label, status in (("failed", "FAILED"), ("processing", "PROCESSING"), ("not found", "NOT_FOUND")):
            if statuses.get(status):
                self.stdout.write(f"  {label}: {', '.join(map(str, statuses[status]))}")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"Invalid date '{value}': use YYYY-MM-DD.")
