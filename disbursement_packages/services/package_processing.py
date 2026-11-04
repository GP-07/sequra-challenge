"""Processing of a package: totals per disbursement with a few queries per package.

1. mark_package_as_processing: takes the package (its own transaction).
2. In a single transaction:
   - lock_package_while_processing: locks the package row until the end of the transaction and sets
     a statement_timeout. The lock says "a live worker is processing it": if the worker dies,
     Postgres releases it and the package can be detected as stuck (package_release).
   - aggregate_package_totals: one aggregated query with the totals of each non-COMPLETED disbursement.
   - validate_totals: in Python, without the DB. An invalid disbursement becomes FAILED (not
     retryable) with its error and does not stop the others.
   - save_disbursement_results: bulk updates of the COMPLETED and the FAILED ones.
   - final package status: COMPLETED if all its disbursements are; otherwise, FAILED.
3. Infrastructure or unexpected error: the whole transaction is rolled back and the non-COMPLETED
   disbursements of the package become FAILED with the error, retryable or not depending on the error.

Reprocessing only touches the disbursements that are not COMPLETED, so it is idempotent.
With disbursement_ids only those disbursements of the package are processed (manual reprocess by
id); the package status is calculated with all its disbursements.
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
    """Takes the package with a single atomic UPDATE: PENDING/FAILED → PROCESSING. True if it took it.

    It is safe with two workers at the same time: the status condition is in the UPDATE's WHERE. In
    Postgres, the second UPDATE waits for the row lock, re-evaluates the WHERE with the status already
    PROCESSING and affects 0 rows, so only one of the two takes the package.
    """
    taken = DisbursementPackage.objects.filter(
        id=package_id, status__in=[DisbursementPackage.Status.PENDING, DisbursementPackage.Status.FAILED]
    ).update(status=DisbursementPackage.Status.PROCESSING, attempts=F("attempts") + 1, updated_at=timezone.now())
    return taken == 1


def lock_package_while_processing(package_id: int) -> None:
    """Locks the package row (FOR UPDATE) and limits each query of the transaction.

    Only the worker that took the package gets here, so nobody else waits for this lock: the stuck
    package check asks for it with SKIP LOCKED. set_config(..., true) applies to this transaction only.
    """
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT set_config('statement_timeout', %s, true)", [f"{settings.PACKAGE_STATEMENT_TIMEOUT_SECONDS}s"]
        )
    DisbursementPackage.objects.select_for_update().only("id").get(id=package_id)


def aggregate_package_totals(package_id: int, disbursement_ids: list[int] | None = None) -> dict[int, DisbursementTotals]:
    """A single query: gross amount and commissions of each non-COMPLETED disbursement of the package.

    With disbursement_ids, only of those.
    """
    return Disbursement.objects.unfinished_in_package(package_id, disbursement_ids).totals()


def validate_totals(totals: DisbursementTotals) -> str | None:
    """None if the totals are valid; otherwise, the reason.

    Neither the gross amount nor the commissions are negative, and the commissions do not exceed the
    gross amount (a negative amount is never paid). Orders are already validated when they come in;
    this protects against data fixed by hand.
    """
    if totals.gross_amount < 0 or totals.commission_fee_amount < 0:
        return f"Negative amounts: gross {totals.gross_amount}, commission fees {totals.commission_fee_amount}."
    if totals.commission_fee_amount > totals.gross_amount:
        return f"Commission fees {totals.commission_fee_amount} are greater than the gross amount {totals.gross_amount}."
    return None


def save_disbursement_results(completed: list[DisbursementTotals], failed: list[tuple[int, str]]) -> None:
    """Bulk updates (in batches) of the COMPLETED disbursements (with totals) and FAILED ones (with their error)."""
    Disbursement.objects.mark_as_completed(completed)
    Disbursement.objects.mark_as_failed_with_errors(failed, is_retryable=False)


def process_disbursement_package(package_id: int, disbursement_ids: list[int] | None = None) -> bool:
    """Returns False if it could not take the package (another worker has it, or it is not PENDING/FAILED).

    With disbursement_ids it only processes those. The package becomes COMPLETED if all its
    disbursements are; otherwise, FAILED. is_retryable of each FAILED disbursement depends on the error:
    - infrastructure error (RETRYABLE_ERRORS): True;
    - data failure or unexpected error: False.
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
