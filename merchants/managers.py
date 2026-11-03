"""Consultas sobre merchants que usan otras apps, con nombres de negocio."""

from django.db import models


class MerchantQuerySet(models.QuerySet):
    def to_disburse_on(self, payment_date, frequency):
        """Merchants de esa frecuencia a los que les toca cobrar en payment_date (ya live antes de ese día).

        - DAILY: todos los días.
        - WEEKLY: solo el día de la semana de su live_on.
        """
        queryset = self.filter(disbursement_frequency=frequency, live_on__lt=payment_date)
        if frequency == self.model.Frequency.WEEKLY:
            # week_day de Django: 1 = domingo ... 7 = sábado.
            queryset = queryset.filter(live_on__week_day=payment_date.isoweekday() % 7 + 1)
        return queryset

    def subject_to_monthly_fee(self, month_end):
        """Live a más tardar el último día del mes y con minimum_monthly_fee mayor a 0.

        Un merchant que pasa a estar live a mitad de mes paga el mes completo (no se prorratea).
        """
        return self.filter(live_on__lte=month_end, minimum_monthly_fee__gt=0)
