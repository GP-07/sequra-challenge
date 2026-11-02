from django.core.management import BaseCommand, CommandError

from core.exceptions import InvalidFile
from core.command_helpers import import_file_path, write_import_result
from merchants.services.csv_import import import_merchants


class Command(BaseCommand):
    help = "Loads the merchants of a CSV file in IMPORT_DIR. Merchants that already exist (by id) are left untouched."

    def add_arguments(self, parser):
        parser.add_argument("file_name", help="Name of the CSV file inside IMPORT_DIR, e.g. merchants.csv")

    def handle(self, *args, file_name, **options):
        path = import_file_path(file_name)
        try:
            result = import_merchants(path)
        except InvalidFile as error:
            raise CommandError(f"{file_name}: {error}")
        write_import_result(self.stdout, "Merchants", result)
