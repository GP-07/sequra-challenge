from datetime import date

from disbursements.data_classes import PackagingResult


def create_disbursement_packages(date_from: date, date_to: date | None = None, max_orders: int | None = None) -> PackagingResult:
    """Arma paquetes con los disbursements PENDING sin paquete cuya fecha de pago está en el rango."""
    raise NotImplementedError
