from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class MonthlyFeesTotals:
    count: int
    amount: Decimal
