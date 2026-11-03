from datetime import datetime

from django.core.management import BaseCommand, CommandError
from django.utils import timezone

from disbursement_packages.services.package_checks import unfinished_packages_for_range
from disbursement_packages.services.package_creation import create_disbursement_packages
from disbursement_packages.tasks import process_disbursement_package
from disbursements.exceptions import DayCreationFailed
from disbursements.services.disbursement_creation import create_disbursements_for_range


class Command(BaseCommand):
    help = (
        "Backfill: creates the DAILY and WEEKLY disbursements of every payment date from --from to --to "
        "(both included, --to at most today), packs them and enqueues the processing of each package in "
        "huey. It does not wait for the processing. Disbursements that already exist are skipped, so it is "
        "safe to run it again."
    )

    def add_arguments(self, parser):
        parser.add_argument("--from", dest="date_from", required=True, help="First payment date, YYYY-MM-DD")
        parser.add_argument("--to", dest="date_to", required=True, help="Last payment date, YYYY-MM-DD")

    def handle(self, *args, date_from, date_to, **options):
        first_date = parse_date(date_from)
        last_date = parse_date(date_to)
        if first_date > last_date:
            raise CommandError(f"--from {date_from} is after --to {date_to}.")
        today = timezone.now().date()
        if last_date > today:
            raise CommandError(f"--to {date_to} is after today ({today}): those days are not closed yet.")

        try:
            creation = create_disbursements_for_range(first_date, last_date)
        except DayCreationFailed as error:
            raise CommandError(
                f"{error} Cause: {error.__cause__}. Disbursements created before it: {error.created_before}. "
                "No package was created. Running the command again is safe: existing disbursements are skipped."
            ) from error

        packaging = create_disbursement_packages(first_date, last_date)
        new_package_ids = [package.id for package in packaging.packages]
        for package_id in new_package_ids:
            process_disbursement_package(package_id)
        unfinished = unfinished_packages_for_range(first_date, last_date, exclude_ids=new_package_ids)

        self.stdout.write(f"Disbursements created: {len(creation.created)}")
        self.stdout.write(f"Disbursements already existing (skipped): {creation.skipped_existing}")
        self.stdout.write(f"Packages enqueued: {len(new_package_ids)}")
        self.stdout.write(f"Requires attention (too many orders for a package): {len(packaging.requires_attention)}")
        for disbursement in packaging.requires_attention:
            self.stdout.write(f"  {disbursement.reference}")
        if unfinished:
            self.stdout.write(
                f"Packages from previous runs not completed (PENDING or FAILED): {len(unfinished)}. "
                "Retry them with retry_disbursement_package."
            )
            self.stdout.write(f"  {', '.join(map(str, unfinished))}")
        self.stdout.write("The packages are being processed in background by the huey workers.")


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise CommandError(f"Invalid date '{value}': use YYYY-MM-DD.")
