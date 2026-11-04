"""Reading of the imported CSV files and parsing of the common fields."""

import csv
import uuid
from datetime import date
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

from core.constants import CSV_DELIMITER
from core.exceptions import InvalidFile, InvalidRow


def read_rows(path: Path, columns: set):
    """(line number, row) for each row of the CSV. Line 1 is the header."""
    with path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file, delimiter=CSV_DELIMITER)
        missing = columns - set(reader.fieldnames or [])
        if missing:
            raise InvalidFile(f"Missing columns: {', '.join(sorted(missing))}")
        for line_number, row in enumerate(reader, start=2):
            yield line_number, row


def parse_uuid(value):
    try:
        return uuid.UUID((value or "").strip())
    except ValueError:
        raise InvalidRow(f"invalid id '{value}'")


def parse_required(value, name):
    value = (value or "").strip()
    if not value:
        raise InvalidRow(f"missing {name}")
    return value


def parse_email(value):
    value = parse_required(value, "email")
    try:
        validate_email(value)
    except ValidationError:
        raise InvalidRow(f"invalid email '{value}'")
    return value


def parse_date(value, name):
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        raise InvalidRow(f"invalid {name} '{value}'")
