"""Consultas sobre orders que usan otras apps, con nombres de negocio."""

from django.db import models
from django.db.models import Sum


class OrderQuerySet(models.QuerySet):
    def commissions_by_merchant(self, date_from, date_to) -> dict:
        """Una sola query: suma de commission_fee por merchant de las orders creadas en el rango (inclusive).

        Cuentan todas las orders creadas en el rango, estén pagadas o no.
        """
        rows = (
            self.filter(order_creation_date__range=(date_from, date_to))
            .order_by()
            .values("merchant_id")
            .annotate(commissions=Sum("commission_fee"))
            .values_list("merchant_id", "commissions")
        )
        return dict(rows)
