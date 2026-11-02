from dataclasses import dataclass, field
from datetime import date


@dataclass
class PackagingResult:
    packages: list = field(default_factory=list)
    requires_attention: list = field(default_factory=list)


def create_disbursement_packages(date_from: date, date_to: date | None = None, max_orders: int | None = None) -> PackagingResult:
    """Arma paquetes con los disbursements PENDING sin paquete cuya fecha de pago está en el rango."""
    raise NotImplementedError
