"""Reprocess manual de disbursements por id, sin volver a correr el día ni el paquete entero."""

from disbursements.data_classes import ReprocessResult


def reprocess_disbursements(disbursement_ids: list[int]) -> ReprocessResult:
    """Agrupa los ids por paquete y procesa cada paquete solo con esos disbursements.

    Usa process_disbursement_package(package_id, disbursement_ids): misma toma atómica, misma
    transacción y misma validación que el proceso normal.
    """
    raise NotImplementedError
