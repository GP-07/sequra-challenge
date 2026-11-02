from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class CreationResult:
    created: list = field(default_factory=list)
    skipped_existing: int = 0


@dataclass
class PackagingResult:
    packages: list = field(default_factory=list)
    requires_attention: list = field(default_factory=list)


@dataclass(frozen=True)
class DisbursementTotals:
    disbursement_id: int
    order_count: int
    gross_amount: Decimal
    commission_fee_amount: Decimal


@dataclass
class CheckResult:
    to_retry: list = field(default_factory=list)


@dataclass
class ReprocessResult:
    processed: list = field(default_factory=list)
    # Ya estaban COMPLETED: no se tocan.
    skipped_completed: list = field(default_factory=list)
    # Su paquete lo está procesando otro worker.
    skipped_in_progress: list = field(default_factory=list)
    # Todavía no tiene paquete: lo va a tomar el flujo normal.
    skipped_without_package: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
