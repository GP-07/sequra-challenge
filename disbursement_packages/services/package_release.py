"""Liberar paquetes trabados en PROCESSING (el worker murió a mitad del procesamiento).

Un paquete está trabado si está en PROCESSING hace más de PACKAGE_STUCK_AFTER_MINUTES y nadie tiene
el lock de su fila. Mientras un worker vivo lo procesa, la transacción de cálculo mantiene ese lock
(lock_package_while_processing); si el worker muere, Postgres lo libera al cortarse la conexión.

Se buscan con FOR UPDATE SKIP LOCKED, así que un paquete que se está procesando nunca se toca (ni se
espera). Al liberarlo, el paquete y sus disbursements sin terminar quedan FAILED retryable, listos
para retry_disbursement_package.
"""

from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from disbursement_packages.constants import STUCK_PACKAGE_ERROR
from disbursement_packages.data_classes import ReleaseResult
from disbursement_packages.models import DisbursementPackage
from disbursements.models import Disbursement


def release_stuck_packages(package_ids: list[int]) -> ReleaseResult:
    result = ReleaseResult()
    packages = DisbursementPackage.objects.in_bulk(package_ids)
    cutoff = timezone.now() - timedelta(minutes=settings.PACKAGE_STUCK_AFTER_MINUTES)
    candidates = []
    for package_id in package_ids:
        package = packages.get(package_id)
        if package is None:
            result.not_found.append(package_id)
        elif package.status != DisbursementPackage.Status.PROCESSING:
            result.not_processing.append((package_id, package.status))
        elif package.updated_at > cutoff:
            result.too_recent.append(package_id)
        else:
            candidates.append(package_id)
    if not candidates:
        return result

    with transaction.atomic():
        # Las filas bloqueadas por un worker vivo no vuelven: SKIP LOCKED las saltea sin esperar.
        stuck = set(
            DisbursementPackage.objects.select_for_update(skip_locked=True)
            .filter(id__in=candidates, status=DisbursementPackage.Status.PROCESSING, updated_at__lte=cutoff)
            .values_list("id", flat=True)
        )
        for package_id in sorted(stuck):
            Disbursement.objects.unfinished_in_package(package_id).mark_as_failed(STUCK_PACKAGE_ERROR, is_retryable=True)
        DisbursementPackage.objects.filter(id__in=stuck).update(
            status=DisbursementPackage.Status.FAILED, updated_at=timezone.now()
        )
    result.released = sorted(stuck)
    result.being_processed = [package_id for package_id in candidates if package_id not in stuck]
    return result
