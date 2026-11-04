"""Status of a set of packages (for example, the ones a backfill enqueued)."""

from collections import defaultdict
from datetime import date

from disbursement_packages.models import DisbursementPackage
from disbursements.models import Disbursement


def package_ids_for_payment_dates(date_from: date, date_to: date) -> list[int]:
    return sorted(Disbursement.objects.package_ids_for_payment_dates(date_from, date_to))


def package_statuses(package_ids: list[int]) -> dict[str, list[int]]:
    """A single query: {status: ids}, with every status (empty ones included) and "NOT_FOUND"."""
    found = dict(DisbursementPackage.objects.filter(id__in=package_ids).values_list("id", "status"))
    statuses = defaultdict(list, {status: [] for status in DisbursementPackage.Status.values})
    for package_id in sorted(set(package_ids)):
        statuses[found.get(package_id, "NOT_FOUND")].append(package_id)
    return dict(statuses)
