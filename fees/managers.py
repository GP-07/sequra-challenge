"""Queries on monthly fees used by other apps, with business names."""

from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import ExtractYear

from fees.data_classes import MonthlyFeesTotals


class MonthlyFeeQuerySet(models.QuerySet):
    def totals_by_year(self) -> dict[int, MonthlyFeesTotals]:
        """A single query: count and amount of the monthly fees by the year of the month they cover.

        December's fee is calculated in January, but it counts in December's year.
        """
        rows = (
            self.order_by()
            .annotate(year=ExtractYear("month"))
            .values("year")
            .annotate(count=Count("id"), amount=Sum("amount"))
            .values_list("year", "count", "amount")
        )
        return {year: MonthlyFeesTotals(count, amount) for year, count, amount in rows}
