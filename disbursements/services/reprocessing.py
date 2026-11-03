"""Reprocess manual de disbursements por id, sin volver a correr el día ni el paquete entero."""

from collections import defaultdict

from disbursement_packages.services.package_processing import process_disbursement_package
from disbursements.data_classes import ReprocessResult
from disbursements.models import Disbursement


def reprocess_disbursements(disbursement_ids: list[int]) -> ReprocessResult:
    """Agrupa los ids por paquete y procesa cada paquete solo con esos disbursements.

    Usa process_disbursement_package(package_id, disbursement_ids): misma toma atómica, misma
    transacción y misma validación que el proceso normal. Se saltean e informan los COMPLETED, los que
    todavía no tienen paquete y los de un paquete que está procesando otro worker.
    """
    result = ReprocessResult()
    found = {
        disbursement_id: (status, package_id)
        for disbursement_id, status, package_id in Disbursement.objects.filter(id__in=disbursement_ids).values_list(
            "id", "status", "package_id"
        )
    }
    by_package = defaultdict(list)
    for disbursement_id in dict.fromkeys(disbursement_ids):
        if disbursement_id not in found:
            result.not_found.append(disbursement_id)
            continue
        status, package_id = found[disbursement_id]
        if status == Disbursement.Status.COMPLETED:
            result.skipped_completed.append(disbursement_id)
        elif package_id is None:
            result.skipped_without_package.append(disbursement_id)
        else:
            by_package[package_id].append(disbursement_id)

    for package_id, ids in by_package.items():
        if process_disbursement_package(package_id, ids):
            result.processed.extend(ids)
        else:
            result.skipped_in_progress.extend(ids)
    return result
