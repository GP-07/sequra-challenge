"""Operations on disbursements used by other apps (packages), with business names.

The other apps call these methods instead of filtering or updating the model directly.
"""

from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import ExtractYear
from django.utils import timezone

from core.constants import ZERO_AMOUNT
from disbursements.constants import DISBURSEMENT_UPDATE_BATCH_SIZE
from disbursements.data_classes import DisbursementTotals, YearlyDisbursementTotals


class DisbursementQuerySet(models.QuerySet):
    # --- packaging ---

    def to_package(self, date_from, date_to):
        """PENDING without a package and with a payment date in the range, in a deterministic order and locked (FOR UPDATE).

        Used inside a transaction: if two runs build packages at the same time, the second one waits and
        no longer sees the ones that got a package.
        """
        return (
            self.select_for_update(of=("self",))
            .filter(status=self.model.Status.PENDING, package__isnull=True, payment_date__range=(date_from, date_to))
            .order_by("payment_date", "merchant_id")
            .only("id", "reference")
        )

    def order_counts(self, disbursement_ids) -> dict[int, int]:
        """A single query: {disbursement_id: number of orders}. Separate from to_package because
        Postgres does not allow FOR UPDATE with GROUP BY.
        """
        rows = self.filter(id__in=disbursement_ids).order_by().annotate(orders_found=Count("orders"))
        return dict(rows.values_list("id", "orders_found"))

    def assign_to_package(self, disbursement_ids, package):
        return self.filter(id__in=disbursement_ids).update(package=package, updated_at=timezone.now())

    def mark_as_requires_attention(self, disbursement_ids):
        return self.filter(id__in=disbursement_ids).update(
            status=self.model.Status.REQUIRES_ATTENTION, updated_at=timezone.now()
        )

    # --- package processing ---

    def unfinished_in_package(self, package_id, disbursement_ids=None):
        """The ones of a package still to be processed (PENDING or FAILED); with disbursement_ids, only those."""
        queryset = self.filter(package_id=package_id, status__in=[self.model.Status.PENDING, self.model.Status.FAILED])
        if disbursement_ids is not None:
            queryset = queryset.filter(id__in=disbursement_ids)
        return queryset

    def totals(self) -> dict[int, DisbursementTotals]:
        """A single query: gross amount and commissions of each disbursement of the queryset."""
        rows = self.order_by().annotate(
            gross=Sum("orders__amount"),
            fees=Sum("orders__commission_fee"),
        ).values_list("id", "gross", "fees")
        return {
            disbursement_id: DisbursementTotals(disbursement_id, gross or ZERO_AMOUNT, fees or ZERO_AMOUNT)
            for disbursement_id, gross, fees in rows
        }

    def mark_as_completed(self, totals: list[DisbursementTotals]) -> None:
        now = timezone.now()
        disbursements = [
            self.model(
                id=disbursement_totals.disbursement_id,
                status=self.model.Status.COMPLETED,
                gross_amount=disbursement_totals.gross_amount,
                commission_fee_amount=disbursement_totals.commission_fee_amount,
                disbursed_amount=disbursement_totals.gross_amount - disbursement_totals.commission_fee_amount,
                error="",
                is_retryable=None,
                updated_at=now,
            )
            for disbursement_totals in totals
        ]
        self.bulk_update(
            disbursements,
            ["status", "gross_amount", "commission_fee_amount", "disbursed_amount", "error", "is_retryable", "updated_at"],
            batch_size=DISBURSEMENT_UPDATE_BATCH_SIZE,
        )

    def mark_as_failed_with_errors(self, failures: list[tuple[int, str]], *, is_retryable: bool) -> None:
        """Each one with its own error (data failure of a disbursement)."""
        now = timezone.now()
        disbursements = [
            self.model(
                id=disbursement_id,
                status=self.model.Status.FAILED,
                error=error,
                is_retryable=is_retryable,
                gross_amount=None,
                commission_fee_amount=None,
                disbursed_amount=None,
                updated_at=now,
            )
            for disbursement_id, error in failures
        ]
        self.bulk_update(
            disbursements,
            ["status", "error", "is_retryable", "gross_amount", "commission_fee_amount", "disbursed_amount", "updated_at"],
            batch_size=DISBURSEMENT_UPDATE_BATCH_SIZE,
        )

    def mark_as_failed(self, error: str, *, is_retryable: bool) -> int:
        """All of the queryset with the same error (infrastructure or unexpected failure)."""
        return self.update(
            status=self.model.Status.FAILED,
            error=error,
            is_retryable=is_retryable,
            gross_amount=None,
            commission_fee_amount=None,
            disbursed_amount=None,
            updated_at=timezone.now(),
        )

    # --- package checks ---

    def packaged_for_payment_date(self, payment_date):
        return self.filter(payment_date=payment_date, package__isnull=False)

    def package_ids_for_payment_dates(self, date_from, date_to) -> set[int]:
        """A single query: ids of the packages of the disbursements with a payment date in the range."""
        rows = self.filter(payment_date__range=(date_from, date_to), package__isnull=False).order_by()
        return set(rows.values_list("package_id", flat=True).distinct())

    def failed(self):
        return self.filter(status=self.model.Status.FAILED)

    # --- reporting ---

    def completed_totals_by_year(self) -> dict[int, YearlyDisbursementTotals]:
        """A single query: count, paid amount and commissions of the COMPLETED ones by year of their payment date."""
        rows = (
            self.filter(status=self.model.Status.COMPLETED)
            .order_by()
            .annotate(year=ExtractYear("payment_date"))
            .values("year")
            .annotate(count=Count("id"), disbursed=Sum("disbursed_amount"), fees=Sum("commission_fee_amount"))
            .values_list("year", "count", "disbursed", "fees")
        )
        return {year: YearlyDisbursementTotals(count, disbursed, fees) for year, count, disbursed, fees in rows}
