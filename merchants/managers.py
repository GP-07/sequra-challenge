"""Queries on merchants used by other apps, with business names."""

from django.db import models


class MerchantQuerySet(models.QuerySet):
    def to_disburse_on(self, payment_date, frequency):
        """Merchants of that frequency that are due to be paid on payment_date (already live before that day).

        - DAILY: every day.
        - WEEKLY: only on the weekday of their live_on.
        """
        queryset = self.filter(disbursement_frequency=frequency, live_on__lt=payment_date)
        if frequency == self.model.Frequency.WEEKLY:
            # Django's week_day: 1 = Sunday ... 7 = Saturday.
            queryset = queryset.filter(live_on__week_day=payment_date.isoweekday() % 7 + 1)
        return queryset

    def subject_to_monthly_fee(self, month_end):
        """Live on the last day of the month at the latest, and with a minimum_monthly_fee greater than 0.

        A merchant that goes live in the middle of the month pays the whole month (it is not prorated).
        """
        return self.filter(live_on__lte=month_end, minimum_monthly_fee__gt=0)
