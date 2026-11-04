"""General helpers for the tests of every app."""

import shutil
from io import StringIO
from pathlib import Path

from django.core.management import call_command


def put_in_import_dir(import_dir: Path, source: Path, name: str) -> None:
    """Copies a test CSV to the import folder with the name the command expects."""
    shutil.copy(source, import_dir / name)


def run_command(*args) -> str:
    """Runs a management command and returns what it wrote to stdout."""
    out = StringIO()
    call_command(*args, stdout=out)
    return out.getvalue()
