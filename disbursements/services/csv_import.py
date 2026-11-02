from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ImportResult:
    created: int = 0
    skipped_existing: int = 0
    invalid: list = field(default_factory=list)  # (número de línea, motivo)


def import_merchants(path: Path) -> ImportResult:
    raise NotImplementedError


def import_orders(path: Path) -> ImportResult:
    raise NotImplementedError
