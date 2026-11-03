"""Consultas sobre merchants que usan otras apps, con nombres de negocio."""

from django.db import models


class MerchantQuerySet(models.QuerySet):
    def subject_to_monthly_fee(self, month_end):
        """Live a más tardar el último día del mes y con minimum_monthly_fee mayor a 0.

        Un merchant que pasa a estar live a mitad de mes paga el mes completo (no se prorratea).
        """
        return self.filter(live_on__lte=month_end, minimum_monthly_fee__gt=0)
