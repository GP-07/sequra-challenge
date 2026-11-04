"""Control de los paquetes de un día de pago: corre en varios horarios y decide qué reintentar.

Primero libera los paquetes del día trabados en PROCESSING (release_stuck_packages): quedan FAILED
retryable y entran en el mismo control, así se reintentan en esta corrida, o alertan si es la última.

Después mira los disbursements FAILED con esa fecha de pago, agrupados por paquete:
- FAILED no retryable: alerta ERROR, no se reintenta (hay que corregir datos o código).
- FAILED retryable en el último horario o sin reintentos disponibles: alerta CRITICAL, no se reintenta.
- FAILED retryable: se reintenta su paquete.

Los paquetes PENDING y los PROCESSING que un worker está procesando (o desde hace menos de
PACKAGE_STUCK_AFTER_MINUTES) no se tocan.
"""

import logging
from collections import defaultdict
from datetime import date

from django.conf import settings

from disbursement_packages.data_classes import CheckResult
from disbursement_packages.models import DisbursementPackage
from disbursement_packages.services.package_release import release_stuck_packages
from disbursements.alerts import alert
from disbursements.models import Disbursement

logger = logging.getLogger(__name__)


def check_disbursement_packages(run_date: date, *, is_last_run: bool) -> CheckResult:
    result = CheckResult(released=release_stuck_packages_of_the_day(run_date))
    of_the_day = Disbursement.objects.packaged_for_payment_date(run_date)
    failures = list(of_the_day.failed().values_list("package_id", "reference", "is_retryable"))
    if not failures:
        return result

    # Solo los paquetes que terminaron FAILED; los que están PROCESSING se están reintentando ahora.
    failed_packages = DisbursementPackage.objects.filter(
        id__in={package_id for package_id, _, _ in failures}, status=DisbursementPackage.Status.FAILED
    ).in_bulk()
    retryable = defaultdict(list)
    non_retryable = defaultdict(list)
    for package_id, reference, is_retryable in failures:
        if package_id not in failed_packages:
            continue
        if is_retryable:
            retryable[package_id].append(reference)
        else:
            non_retryable[package_id].append(reference)

    for package_id, references in sorted(non_retryable.items()):
        alert(f"Package {package_id}: disbursements failed and cannot be retried: {', '.join(sorted(references))}.")

    if not retryable:
        return result
    if is_last_run:
        for package_id, references in sorted(retryable.items()):
            alert(
                f"Package {package_id}: disbursements still failed on the last check: {', '.join(sorted(references))}.",
                critical=True,
            )
        return result

    # attempts cuenta ejecuciones: 1 original + PACKAGE_MAX_RETRIES reintentos.
    max_attempts = 1 + settings.PACKAGE_MAX_RETRIES
    for package_id, references in sorted(retryable.items()):
        if failed_packages[package_id].attempts < max_attempts:
            result.to_retry.append(package_id)
        else:
            alert(
                f"Package {package_id}: no retries left for failed disbursements: {', '.join(sorted(references))}.",
                critical=True,
            )
    return result


def release_stuck_packages_of_the_day(run_date: date) -> list[int]:
    """Libera los paquetes PROCESSING del día cuyo worker ya no está. Devuelve los ids liberados."""
    package_ids = Disbursement.objects.package_ids_for_payment_dates(run_date, run_date)
    processing = DisbursementPackage.objects.filter(id__in=package_ids, status=DisbursementPackage.Status.PROCESSING)
    processing_ids = sorted(processing.values_list("id", flat=True))
    if not processing_ids:
        return []
    released = release_stuck_packages(processing_ids).released
    for package_id in released:
        logger.warning("Package %s was stuck in PROCESSING and was released as FAILED (retryable).", package_id)
    return released


def unfinished_packages_for_range(date_from: date, date_to: date, *, exclude_ids=()) -> list[int]:
    """Ids de los paquetes PENDING o FAILED de los disbursements con fecha de pago en el rango.

    Lo usa el backfill para informar paquetes de una corrida anterior que no terminaron; no los re-encola.
    """
    package_ids = Disbursement.objects.package_ids_for_payment_dates(date_from, date_to) - set(exclude_ids)
    unfinished = DisbursementPackage.objects.filter(
        id__in=package_ids, status__in=[DisbursementPackage.Status.PENDING, DisbursementPackage.Status.FAILED]
    )
    return sorted(unfinished.values_list("id", flat=True))
