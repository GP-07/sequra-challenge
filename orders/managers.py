"""Queries on orders used by other apps, with business names."""

from django.db import models
from django.db.models import Case, Min, Sum, Value, When


class OrderQuerySet(models.QuerySet):
    def pending_disbursement_by_merchant(self, merchant_ids, up_to) -> dict:
        """A single query: orders without a disbursement created up to up_to (inclusive), per merchant.

        Returns {merchant_id: date of the oldest order}; a merchant without pending orders is not included.
        """
        rows = (
            self.filter(merchant_id__in=merchant_ids, disbursement__isnull=True, order_creation_date__lte=up_to)
            .order_by()
            .values("merchant_id")
            .annotate(oldest=Min("order_creation_date"))
            .values_list("merchant_id", "oldest")
        )
        return dict(rows)

    def assign_to_disbursement(self, merchant_id, up_to, disbursement_id) -> int:
        """Assigns to the disbursement the merchant's orders without a disbursement created up to up_to. Returns how many."""
        return self.filter(
            merchant_id=merchant_id, disbursement__isnull=True, order_creation_date__lte=up_to
        ).update(disbursement_id=disbursement_id)

    def assign_to_disbursements(self, disbursement_by_merchant: dict, up_to) -> int:
        """assign_to_disbursement for several merchants at once, with a single UPDATE. Returns how many it assigned.

        disbursement_by_merchant is {merchant_id: disbursement_id}.
        """
        if not disbursement_by_merchant:
            return 0
        return self.filter(
            merchant_id__in=disbursement_by_merchant, disbursement__isnull=True, order_creation_date__lte=up_to
        ).update(
            disbursement_id=Case(
                *[When(merchant_id=merchant_id, then=Value(disbursement_id))
                  for merchant_id, disbursement_id in disbursement_by_merchant.items()]
            )
        )

    def commissions_by_merchant(self, date_from, date_to) -> dict:
        """A single query: sum of commission_fee per merchant of the orders created in the range (inclusive).

        Every order created in the range counts, whether it is paid or not.
        """
        rows = (
            self.filter(order_creation_date__range=(date_from, date_to))
            .order_by()
            .values("merchant_id")
            .annotate(commissions=Sum("commission_fee"))
            .values_list("merchant_id", "commissions")
        )
        return dict(rows)
