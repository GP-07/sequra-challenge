from datetime import date

from django.conf import settings
from django.db import transaction

from disbursement_packages.data_classes import PackagingResult
from disbursement_packages.models import DisbursementPackage
from disbursements.alerts import alert
from disbursements.models import Disbursement


def create_disbursement_packages(date_from: date, date_to: date | None = None, max_orders: int | None = None) -> PackagingResult:
    """Arma paquetes con los disbursements PENDING sin paquete cuya fecha de pago está en el rango.

    - Cada paquete tiene hasta max_orders orders (PACKAGE_MAX_ORDERS por defecto) y un disbursement
      nunca se parte entre paquetes.
    - Orden determinístico: fecha de pago e id (de la DB) del merchant, sin join a merchants. Los
      mismos datos dan los mismos paquetes.
    - Un disbursement con más de max_orders orders no entra en ningún paquete: queda
      REQUIRES_ATTENTION y se alerta (CRITICAL) para procesarlo a mano.

    Los disbursements se leen bloqueados (FOR UPDATE): si dos corridas arman paquetes a la vez, la
    segunda espera a la primera y ya no ve los disbursements que quedaron con paquete.
    """
    date_to = date_to or date_from
    max_orders = max_orders or settings.PACKAGE_MAX_ORDERS
    result = PackagingResult()

    with transaction.atomic():
        disbursements = list(Disbursement.objects.to_package(date_from, date_to))
        order_counts = Disbursement.objects.order_counts([d.id for d in disbursements])

        groups = []
        current, current_orders = [], 0
        for disbursement in disbursements:
            order_count = order_counts[disbursement.id]
            if order_count > max_orders:
                result.requires_attention.append(disbursement)
                continue
            if current and current_orders + order_count > max_orders:
                groups.append(current)
                current, current_orders = [], 0
            current.append(disbursement)
            current_orders += order_count
        if current:
            groups.append(current)

        result.packages = DisbursementPackage.objects.bulk_create(
            [DisbursementPackage(order_count=sum(order_counts[d.id] for d in group)) for group in groups]
        )
        # Una query por paquete: ~1 por día y ~260 en el backfill completo.
        for package, group in zip(result.packages, groups):
            Disbursement.objects.assign_to_package([d.id for d in group], package)

        if result.requires_attention:
            Disbursement.objects.mark_as_requires_attention([d.id for d in result.requires_attention])

    for disbursement in result.requires_attention:
        alert(
            f"Disbursement {disbursement.reference} has {order_counts[disbursement.id]} orders, more than the "
            f"{max_orders} allowed per package. It requires manual processing.",
            critical=True,
        )
    return result
