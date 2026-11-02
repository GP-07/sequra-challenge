from django.core.management import BaseCommand, CommandError

from core.command_helpers import import_file_path, write_import_result
from core.exceptions import InvalidFile
from orders.services.csv_import import import_orders


class Command(BaseCommand):
    help = (
        "Loads the orders of a CSV file in IMPORT_DIR, with their commission fee. "
        "Orders that already exist (by id) are left untouched. Merchants must be loaded first."
    )

    def add_arguments(self, parser):
        parser.add_argument("file_name", help="Name of the CSV file inside IMPORT_DIR, e.g. orders.csv")

    def handle(self, *args, file_name, **options):
        path = import_file_path(file_name)
        try:
            result = import_orders(path)
        except InvalidFile as error:
            raise CommandError(f"{file_name}: {error}")
        write_import_result(self.stdout, "Orders", result)
