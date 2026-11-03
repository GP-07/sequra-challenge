from django.core.management import BaseCommand, CommandError

from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_processing import process_disbursement_package
from disbursements.models import Disbursement


class Command(BaseCommand):
    help = (
        "Reprocesses a disbursement package by hand, after fixing what made it fail. Only its disbursements "
        "that are not COMPLETED are processed, whether they are retryable or not."
    )

    def add_arguments(self, parser):
        parser.add_argument("package_id", type=int, help="Id of the disbursement package to reprocess")

    def handle(self, *args, package_id, **options):
        package = DisbursementPackage.objects.filter(id=package_id).first()
        if package is None:
            raise CommandError(f"Package {package_id} not found.")
        if package.status == DisbursementPackage.Status.COMPLETED:
            self.stdout.write(f"Package {package_id} is already completed: nothing to reprocess.")
            return
        if package.status == DisbursementPackage.Status.PROCESSING:
            self.stdout.write(f"Package {package_id} is being processed right now: skipped.")
            return

        process_disbursement_package(package_id)

        package.refresh_from_db()
        self.stdout.write(f"Package {package_id}: {package.status} (attempts: {package.attempts})")
        for reference, error in Disbursement.objects.unfinished_in_package(package_id).failed().values_list("reference", "error"):
            self.stdout.write(f"  {reference}: {error}")
