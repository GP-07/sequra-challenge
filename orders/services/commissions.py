from decimal import ROUND_HALF_UP, Decimal

from core.constants import CENTS
from orders.constants import COMMISSION_TIERS


def calculate_commission_fee(amount: Decimal) -> Decimal:
    """seQura's commission according to the amount tier, rounded half-up to 2 decimals."""
    if amount < 0:
        raise ValueError(f"Negative amount: {amount}")
    for minimum, rate in COMMISSION_TIERS:
        if amount >= minimum:
            return (amount * rate).quantize(CENTS, rounding=ROUND_HALF_UP)
