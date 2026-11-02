"""Procesamiento de un paquete: totales por disbursement con pocas queries por paquete.

1. mark_package_as_processing: toma el paquete (transacción propia).
2. En una sola transacción:
   - aggregate_package_totals: una query agregada con los totales de cada disbursement no COMPLETED.
   - validate_totals: en Python, sin DB. Un disbursement inválido queda FAILED con su error y
     no corta a los demás.
   - save_disbursement_results: bulk updates de los COMPLETED y de los FAILED.
   - estado final del paquete: COMPLETED, o FAILED no retryable si algún disbursement es inválido
     (reintentar no sirve hasta que alguien corrija los datos).
3. Error de infraestructura o inesperado: se revierte toda la transacción y el paquete y sus
   disbursements no COMPLETED quedan FAILED, retryable o no según el error.

Reprocesar solo toca los disbursements que no están COMPLETED, así que es idempotente.
Con disbursement_ids se procesan solo esos disbursements del paquete (reprocess manual por id); el
estado del paquete se calcula con todos sus disbursements.
"""

from disbursements.data_classes import DisbursementTotals


def mark_package_as_processing(package_id: int) -> bool:
    """Toma el paquete con un solo UPDATE atómico: PENDING/FAILED → PROCESSING. True si lo tomó.

    Es seguro con dos workers a la vez: la condición de estado va en el WHERE del UPDATE. En Postgres,
    el segundo UPDATE espera el lock de la fila, re-evalúa el WHERE con el estado ya en PROCESSING y
    afecta 0 filas, así que solo uno de los dos toma el paquete.
    """
    raise NotImplementedError


def aggregate_package_totals(package_id: int, disbursement_ids: list[int] | None = None) -> dict[int, DisbursementTotals]:
    """Una sola query: cantidad de orders, bruto y comisiones de cada disbursement no COMPLETED del paquete.

    Con disbursement_ids, solo de esos.
    """
    raise NotImplementedError


def validate_totals(disbursement, totals: DisbursementTotals | None) -> str | None:
    """None si los totales son válidos; si no, el motivo (p. ej. no coincide la cantidad de orders)."""
    raise NotImplementedError


def save_disbursement_results(completed: list, failed: list) -> None:
    """Bulk updates de los disbursements COMPLETED (con totales) y FAILED (con su error).

    PENDIENTE al implementar: hacerlo por lotes (o con otra forma de agrupar) para que no sea pesado
    con muchas filas.
    """
    raise NotImplementedError


def process_disbursement_package(package_id: int, disbursement_ids: list[int] | None = None) -> bool:
    """Devuelve False si no pudo tomar el paquete (otro worker lo tiene o no está PENDING/FAILED).

    Con disbursement_ids solo procesa esos. El paquete queda COMPLETED si todos sus disbursements lo
    están; si no, queda FAILED. is_retryable depende siempre del tipo de error, también en un reproceso:
    - error de infraestructura en esta corrida (OperationalError, TimeoutError): True;
    - falla de datos o error inesperado en esta corrida: False;
    - sin error en esta corrida pero con otros disbursements FAILED que no se pidieron: se mantiene
      el is_retryable que tenía el paquete.
    """
    raise NotImplementedError
