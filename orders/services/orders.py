from datetime import date
from decimal import Decimal


def create_order(*, order_id: str, merchant_reference: str, amount: Decimal, order_creation_date: date):
    """Guarda una order con su commission_fee calculada al ingresar."""
    raise NotImplementedError
