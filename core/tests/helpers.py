"""Helpers generales para los tests de todas las apps."""

import shutil
from io import StringIO
from pathlib import Path

from django.core.management import call_command


def put_in_import_dir(import_dir: Path, source: Path, name: str) -> None:
    """Copia un CSV de prueba a la carpeta de importación con el nombre que espera el comando."""
    shutil.copy(source, import_dir / name)


def run_command(*args) -> str:
    """Corre un management command y devuelve lo que escribió en stdout."""
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()
