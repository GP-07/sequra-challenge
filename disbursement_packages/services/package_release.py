"""Releasing packages stuck in PROCESSING (the worker died in the middle of the processing).

A package is stuck if it has been in PROCESSING for more than PACKAGE_STUCK_AFTER_MINUTES and nobody
holds the lock on its row. While a live worker processes it, the calculation transaction keeps that
lock (lock_package_while_processing); if the worker dies, Postgres releases it when the connection drops.

They are searched with FOR UPDATE SKIP LOCKED, so a package being processed is never touched (nor
waited for). When it is released, the package and its unfinished disbursements become FAILED
retryable, ready for retry_disbursement_package.
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
        # Rows locked by a live worker are not returned: SKIP LOCKED skips them without waiting.
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
