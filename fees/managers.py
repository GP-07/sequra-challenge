"""Consultas sobre monthly fees que usan otras apps, con nombres de negocio."""

from django.db import models
from django.db.models import Count, Sum
from django.db.models.functions import ExtractYear

from fees.data_classes import MonthlyFeesTotals


class MonthlyFeeQuerySet(models.QuerySet):
    def totals_by_year(self) -> dict[int, MonthlyFeesTotals]:
        """Una sola query: cantidad y monto de las monthly fees por año del mes que cubren.

        La de diciembre se calcula en enero, pero cuenta en el año de diciembre.
        """
        rows = (
            self.order_by()
            .annotate(year=ExtractYear("month"))
            .values("year")
            .annotate(count=Count("id"), amount=Sum("amount"))
            .values_list("year", "count", "amount")
        )
        return {year: MonthlyFeesTotals(count, amount) for year, count, amount in rows}
