"""Monthly task for monthly fees: on day 1 at 00:30 UTC it calculates the previous month."""

from datetime import timedelta

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from fees.services.monthly_fees import calculate_monthly_fees


def now():
    return timezone.now()


@db_periodic_task(crontab(day="1", hour="0", minute="30"))
def calculate_monthly_fees_task():
    previous_month = (now().date().replace(day=1) - timedelta(days=1)).replace(day=1)
    calculate_monthly_fees(previous_month)
