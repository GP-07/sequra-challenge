"""Daily disbursement creation task.

At 00:05 UTC it creates the DAILY and WEEKLY disbursements of the day and, when it finishes, enqueues
the packaging: this way packaging always runs after creation, without a schedule of its own.
"""

from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task

from disbursement_packages.tasks import create_disbursement_packages_task
from disbursements.alerts import alert
from disbursements.constants import CREATION_TASK_RETRIES, CREATION_TASK_RETRY_DELAY_SECONDS
from disbursements.services.disbursement_creation import create_disbursements
from merchants.models import Merchant


def now():
    return timezone.now()


@db_periodic_task(
    crontab(minute="5", hour="0"),
    retries=CREATION_TASK_RETRIES,
    retry_delay=CREATION_TASK_RETRY_DELAY_SECONDS,
    context=True,
)
def create_disbursements_task(task=None):
    """If it fails, huey retries it; it is idempotent, so it does not duplicate what was already created.

    On the last failed attempt it alerts (CRITICAL) and no package is built.
    """
    payment_date = now().date()
    try:
        for frequency in (Merchant.Frequency.DAILY, Merchant.Frequency.WEEKLY):
            create_disbursements(payment_date, frequency)
    except Exception as error:
        if task is None or task.retries == 0:
            alert(f"Disbursements of {payment_date} could not be created: {error}", critical=True)
        raise
    create_disbursement_packages_task()
