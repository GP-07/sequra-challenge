"""Check of the packages of a payment day: runs at several hours and decides what to retry.

First it releases the day's packages stuck in PROCESSING (release_stuck_packages): they become FAILED
retryable and go through the same check, so they are retried in this run, or alert if it is the last.

Then it looks at the FAILED disbursements with that payment date, grouped by package:
- FAILED not retryable: ERROR alert, not retried (data or code has to be fixed).
- FAILED retryable on the last run or without retries left: CRITICAL alert, not retried.
- FAILED retryable: its package is retried.

PENDING packages, and PROCESSING ones that a worker is processing (or for less than
PACKAGE_STUCK_AFTER_MINUTES), are not touched.
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

    # Only the packages that ended FAILED; the ones in PROCESSING are being retried right now.
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
    """Releases the day's PROCESSING packages whose worker is gone. Returns the released ids."""
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
    """Ids of the PENDING or FAILED packages of the disbursements with a payment date in the range.

    Used by the backfill to report unfinished packages of a previous run; it does not re-enqueue them.
    """
    package_ids = Disbursement.objects.package_ids_for_payment_dates(date_from, date_to) - set(exclude_ids)
    unfinished = DisbursementPackage.objects.filter(
        id__in=package_ids, status__in=[DisbursementPackage.Status.PENDING, DisbursementPackage.Status.FAILED]
    )
    return sorted(unfinished.values_list("id", flat=True))
