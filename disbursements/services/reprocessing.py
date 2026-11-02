"""Reprocess manual de disbursements por id, sin volver a correr el día ni el paquete entero."""

from dataclasses import dataclass, field


@dataclass
class ReprocessResult:
    processed: list = field(default_factory=list)
    # Ya estaban COMPLETED: no se tocan.
    skipped_completed: list = field(default_factory=list)
    # Su paquete lo está procesando otro worker.
    skipped_in_progress: list = field(default_factory=list)
    # Todavía no tiene paquete: lo va a tomar el flujo normal.
    skipped_without_package: list = field(default_factory=list)
    not_found: list = field(default_factory=list)


def reprocess_disbursements(disbursement_ids: list[int]) -> ReprocessResult:
    """Agrupa los ids por paquete y procesa cada paquete solo con esos disbursements.

    Usa process_disbursement_package(package_id, disbursement_ids): misma toma atómica, misma
    transacción y misma validación que el proceso normal.
    """
    raise NotImplementedError
