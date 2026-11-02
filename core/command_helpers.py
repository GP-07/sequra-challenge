"""Lo que comparten load_merchants y load_orders: ubicar el archivo e informar el resultado."""

from pathlib import Path

from django.conf import settings
from django.core.management import CommandError


def import_file_path(file_name: str) -> Path:
    """El archivo tiene que estar en IMPORT_DIR (en Docker, la carpeta montada)."""
    import_dir = Path(settings.IMPORT_DIR)
    if Path(file_name).name != file_name:
        raise CommandError(f"Pass only the file name; the file is read from {import_dir}.")
    path = import_dir / file_name
    if not path.is_file():
        raise CommandError(f"File '{file_name}' not found in {import_dir}. Put it in that folder and run the command again.")
    return path


def write_import_result(stdout, label: str, result) -> None:
    stdout.write(f"{label} created: {result.created}")
    stdout.write(f"{label} already loaded (skipped): {result.skipped_existing}")
    stdout.write(f"Invalid rows (skipped): {len(result.invalid)}")
    for line_number, reason in sorted(result.invalid):
        stdout.write(f"  line {line_number}: {reason}")
