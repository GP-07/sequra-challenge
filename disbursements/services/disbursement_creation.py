from datetime import date

from disbursements.data_classes import CreationResult


def natural_key_hash(merchant_id, payment_date: date) -> str:
    """sha256 (hex, 64 caracteres) de (merchant, fecha de pago).

    Siempre da lo mismo para los mismos datos, así que el constraint único de la DB impide crear dos
    veces el mismo disbursement aunque el proceso corra dos veces a la vez.
    """
    raise NotImplementedError


def create_disbursements(payment_date: date, frequency: str) -> CreationResult:
    """create_disbursements_daily / weekly para una fecha de pago."""
    raise NotImplementedError


def create_disbursements_for_range(date_from: date, date_to: date) -> CreationResult:
    """Backfill: misma lógica, para cada fecha de pago del rango (inclusive)."""
    raise NotImplementedError
