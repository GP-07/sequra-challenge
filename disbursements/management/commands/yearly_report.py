import csv

from django.core.management import BaseCommand

from core.constants import CSV_DELIMITER
from disbursements.services.reports import yearly_report

COLUMNS = (
    "year",
    "disbursements_count",
    "disbursed_amount",
    "order_fees_amount",
    "monthly_fees_count",
    "monthly_fees_amount",
)


class Command(BaseCommand):
    help = (
        "Prints the yearly table of the README as CSV (';' separated): COMPLETED disbursements by year of "
        "their payment date, and monthly fees by year of the month they cover."
    )

    def handle(self, *args, **options):
        writer = csv.DictWriter(self.stdout, fieldnames=COLUMNS, delimiter=CSV_DELIMITER, lineterminator="\n")
        writer.writeheader()
        writer.writerows(yearly_report())
