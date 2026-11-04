from dataclasses import dataclass, field
from decimal import Decimal


@dataclass
class CreationResult:
    created: list = field(default_factory=list)
    skipped_existing: int = 0


@dataclass
class ReprocessResult:
    processed: list = field(default_factory=list)
    # Already COMPLETED: not touched.
    skipped_completed: list = field(default_factory=list)
    # Another worker is processing their package.
    skipped_in_progress: list = field(default_factory=list)
    # No package yet: the normal flow will take it.
    skipped_without_package: list = field(default_factory=list)
    not_found: list = field(default_factory=list)


@dataclass(frozen=True)
class YearlyDisbursementTotals:
    count: int
    disbursed_amount: Decimal
    order_fees_amount: Decimal


@dataclass(frozen=True)
class DisbursementTotals:
    disbursement_id: int
    gross_amount: Decimal
    commission_fee_amount: Decimal
