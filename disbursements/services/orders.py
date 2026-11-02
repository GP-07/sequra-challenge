from datetime import date
from decimal import Decimal


def create_order(*, order_id: str, merchant_reference: str, amount: Decimal, created_at: date):
    """Guarda una order con su commission_fee calculada al ingresar."""
    raise NotImplementedError
