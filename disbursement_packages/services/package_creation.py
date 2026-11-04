from datetime import date

from django.conf import settings
from django.db import transaction

from disbursement_packages.data_classes import PackagingResult
from disbursement_packages.models import DisbursementPackage
from disbursements.alerts import alert
from disbursements.models import Disbursement


def create_disbursement_packages(date_from: date, date_to: date | None = None, max_orders: int | None = None) -> PackagingResult:
    """Builds packages with the PENDING disbursements without a package whose payment date is in the range.

    - Each package has up to max_orders orders (PACKAGE_MAX_ORDERS by default) and a disbursement is
      never split across packages.
    - Deterministic order: payment date and the merchant's (DB) id, without a join to merchants. The
      same data gives the same packages.
    - A disbursement with more than max_orders orders goes into no package: it becomes
      REQUIRES_ATTENTION and raises a (CRITICAL) alert, to be processed by hand.

    The disbursements are read locked (FOR UPDATE): if two runs build packages at the same time, the
    second one waits for the first and no longer sees the disbursements that got a package.
    """
    date_to = date_to or date_from
    max_orders = max_orders or settings.PACKAGE_MAX_ORDERS
    result = PackagingResult()

    with transaction.atomic():
        disbursements = list(Disbursement.objects.to_package(date_from, date_to))
        order_counts = Disbursement.objects.order_counts([disbursement.id for disbursement in disbursements])

        groups = []
        current, current_orders = [], 0
        for disbursement in disbursements:
            order_count = order_counts[disbursement.id]
            if order_count > max_orders:
                result.requires_attention.append(disbursement)
                continue
            if current and current_orders + order_count > max_orders:
                groups.append(current)
                current, current_orders = [], 0
            current.append(disbursement)
            current_orders += order_count
        if current:
            groups.append(current)

        result.packages = DisbursementPackage.objects.bulk_create(
            [DisbursementPackage(order_count=sum(order_counts[disbursement.id] for disbursement in group)) for group in groups]
        )
        # One query per package: ~1 per day and ~260 in the whole backfill.
        for package, group in zip(result.packages, groups):
            Disbursement.objects.assign_to_package([disbursement.id for disbursement in group], package)

        if result.requires_attention:
            Disbursement.objects.mark_as_requires_attention([disbursement.id for disbursement in result.requires_attention])

    for disbursement in result.requires_attention:
        alert(
            f"Disbursement {disbursement.reference} has {order_counts[disbursement.id]} orders, more than the "
            f"{max_orders} allowed per package. It requires manual processing.",
            critical=True,
        )
    return result
