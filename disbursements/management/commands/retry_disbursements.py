from django.core.management import BaseCommand

from disbursements.services.reprocessing import reprocess_disbursements


class Command(BaseCommand):
    help = (
        "Reprocesses disbursements by id, after fixing what made them fail. Each one is processed within "
        "its package; COMPLETED disbursements are skipped and reported."
    )

    def add_arguments(self, parser):
        parser.add_argument("disbursement_ids", nargs="+", type=int, help="Ids of the disbursements to reprocess")

    def handle(self, *args, disbursement_ids, **options):
        result = reprocess_disbursements(disbursement_ids)

        self.stdout.write(f"Reprocessed: {len(result.processed)}")
        self.stdout.write(f"Skipped (already completed): {len(result.skipped_completed)}")
        self.stdout.write(f"Skipped (package in progress): {len(result.skipped_in_progress)}")
        self.stdout.write(f"Skipped (without package yet): {len(result.skipped_without_package)}")
        self.stdout.write(f"Not found: {len(result.not_found)}")
        for label, ids in (
            ("already completed", result.skipped_completed),
            ("package in progress", result.skipped_in_progress),
            ("without package yet", result.skipped_without_package),
            ("not found", result.not_found),
        ):
            if ids:
                self.stdout.write(f"  {label}: {', '.join(map(str, ids))}")
