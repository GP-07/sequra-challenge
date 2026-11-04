"""Procesamiento de un paquete: totales por disbursement con pocas queries por paquete.

1. mark_package_as_processing: toma el paquete (transacción propia).
2. En una sola transacción:
   - lock_package_while_processing: bloquea la fila del paquete hasta el final de la transacción y fija
     un statement_timeout. El lock dice "un worker vivo lo está procesando": si el worker muere,
     Postgres lo libera y el paquete puede detectarse como trabado (package_release).
   - aggregate_package_totals: una query agregada con los totales de cada disbursement no COMPLETED.
   - validate_totals: en Python, sin DB. Un disbursement inválido queda FAILED (no retryable) con su
     error y no corta a los demás.
   - save_disbursement_results: bulk updates de los COMPLETED y de los FAILED.
   - estado final del paquete: COMPLETED si todos sus disbursements lo están; si no, FAILED.
3. Error de infraestructura o inesperado: se revierte toda la transacción y los disbursements no
   COMPLETED del paquete quedan FAILED con el error, retryable o no según el tipo de error.

Reprocesar solo toca los disbursements que no están COMPLETED, así que es idempotente.
Con disbursement_ids se procesan solo esos disbursements del paquete (reprocess manual por id); el
estado del paquete se calcula con todos sus disbursements.
"""

import logging

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone

from disbursement_packages.constants import RETRYABLE_ERRORS
from disbursement_packages.models import DisbursementPackage
from disbursements.data_classes import DisbursementTotals
from disbursements.models import Disbursement

logger = logging.getLogger(__name__)


def mark_package_as_processing(package_id: int) -> bool:
    """Toma el paquete con un solo UPDATE atómico: PENDING/FAILED → PROCESSING. True si lo tomó.

    Es seguro con dos workers a la vez: la condición de estado va en el WHERE del UPDATE. En Postgres,
    el segundo UPDATE espera el lock de la fila, re-evalúa el WHERE con el estado ya en PROCESSING y
    afecta 0 filas, así que solo uno de los dos toma el paquete.
    """
    taken = DisbursementPackage.objects.filter(
        id=package_id, status__in=[DisbursementPackage.Status.PENDING, DisbursementPackage.Status.FAILED]
    ).update(status=DisbursementPackage.Status.PROCESSING, attempts=F("attempts") + 1, updated_at=timezone.now())
    return taken == 1


def lock_package_while_processing(package_id: int) -> None:
    """Bloquea la fila del paquete (FOR UPDATE) y limita cada query de la transacción.

    Solo llega acá el worker que tomó el paquete, así que nadie más espera este lock: el control de
    paquetes trabados lo consulta con SKIP LOCKED. set_config(..., true) vale solo para esta transacción.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)", [f"{settings.PACKAGE_STATEMENT_TIMEOUT_SECONDS}s"]
        )
    DisbursementPackage.objects.select_for_update().only("id").get(id=package_id)


def aggregate_package_totals(package_id: int, disbursement_ids: list[int] | None = None) -> dict[int, DisbursementTotals]:
    """Una sola query: bruto y comisiones de cada disbursement no COMPLETED del paquete.

    Con disbursement_ids, solo de esos.
    """
    return Disbursement.objects.unfinished_in_package(package_id, disbursement_ids).totals()


def validate_totals(totals: DisbursementTotals) -> str | None:
    """None si los totales son válidos; si no, el motivo.

    Ni el bruto ni las comisiones son negativos, y las comisiones no superan al bruto (no se paga un
    monto negativo). Las orders ya se validan al ingresar; esto protege ante un dato corregido a mano.
    """
    if totals.gross_amount < 0 or totals.commission_fee_amount < 0:
        return f"Negative amounts: gross {totals.gross_amount}, commission fees {totals.commission_fee_amount}."
    if totals.commission_fee_amount > totals.gross_amount:
        return f"Commission fees {totals.commission_fee_amount} are greater than the gross amount {totals.gross_amount}."
    return None


def save_disbursement_results(completed: list[DisbursementTotals], failed: list[tuple[int, str]]) -> None:
    """Bulk updates (por lotes) de los disbursements COMPLETED (con totales) y FAILED (con su error)."""
    Disbursement.objects.mark_as_completed(completed)
    Disbursement.objects.mark_as_failed_with_errors(failed, is_retryable=False)


def process_disbursement_package(package_id: int, disbursement_ids: list[int] | None = None) -> bool:
    """Devuelve False si no pudo tomar el paquete (otro worker lo tiene o no está PENDING/FAILED).

    Con disbursement_ids solo procesa esos. El paquete queda COMPLETED si todos sus disbursements lo
    están; si no, queda FAILED. is_retryable de cada disbursement FAILED depende del tipo de error:
    - error de infraestructura (RETRYABLE_ERRORS): True;
    - falla de datos o error inesperado: False.
    """
    if not mark_package_as_processing(package_id):
        return False
    try:
        with transaction.atomic():
            lock_package_while_processing(package_id)
            completed, failed = [], []
            for totals in aggregate_package_totals(package_id, disbursement_ids).values():
                error = validate_totals(totals)
                if error:
                    failed.append((totals.disbursement_id, error))
                else:
                    completed.append(totals)
            save_disbursement_results(completed, failed)
            finish_package(package_id)
    except Exception as error:
        logger.exception("Package %s failed while processing", package_id)
        with transaction.atomic():
            Disbursement.objects.unfinished_in_package(package_id, disbursement_ids).mark_as_failed(
                str(error), is_retryable=isinstance(error, RETRYABLE_ERRORS)
            )
            set_package_status(package_id, DisbursementPackage.Status.FAILED)
    return True


def finish_package(package_id: int) -> None:
    has_unfinished = Disbursement.objects.unfinished_in_package(package_id).exists()
    set_package_status(
        package_id, DisbursementPackage.Status.FAILED if has_unfinished else DisbursementPackage.Status.COMPLETED
    )


def set_package_status(package_id: int, status: str) -> None:
    DisbursementPackage.objects.filter(id=package_id).update(status=status, updated_at=timezone.now())
