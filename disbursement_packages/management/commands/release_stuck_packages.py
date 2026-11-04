from django.conf import settings
from django.core.management import BaseCommand

from disbursement_packages.services.package_release import release_stuck_packages


class Command(BaseCommand):
    help = (
        "Moves to FAILED the given packages that are stuck in PROCESSING: in PROCESSING for more than "
        "PACKAGE_STUCK_AFTER_MINUTES and not locked by a worker (the worker that had them is gone). Packages "
        "a live worker is processing are never touched. Released packages can then be retried with "
        "retry_disbursement_package."
    )

    def add_arguments(self, parser):
        parser.add_argument("package_ids", nargs="+", type=int, help="Ids of the packages to check")

    def handle(self, *args, package_ids, **options):
        result = release_stuck_packages(package_ids)

        self.stdout.write(f"Released (now FAILED, retryable): {len(result.released)}")
        self.stdout.write(f"Still being processed by a worker: {len(result.being_processed)}")
        self.stdout.write(
            f"In PROCESSING for less than {settings.PACKAGE_STUCK_AFTER_MINUTES} minutes: {len(result.too_recent)}"
        )
        self.stdout.write(f"Not in PROCESSING: {len(result.not_processing)}")
        self.stdout.write(f"Not found: {len(result.not_found)}")
        for label, ids in (
            ("released", result.released),
            ("still being processed", result.being_processed),
            ("too recent", result.too_recent),
            ("not in PROCESSING", [f"{package_id} ({status})" for package_id, status in result.not_processing]),
            ("not found", result.not_found),
        ):
            if ids:
                self.stdout.write(f"  {label}: {', '.join(map(str, ids))}")
        if result.released:
            self.stdout.write("Retry them with retry_disbursement_package.")
