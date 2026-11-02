from dataclasses import dataclass, field


@dataclass
class ImportResult:
    created: int = 0
    skipped_existing: int = 0
    invalid: list = field(default_factory=list)  # (número de línea, motivo)
