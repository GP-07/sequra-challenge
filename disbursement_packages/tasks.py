"""Package tasks: packaging (enqueued by the daily creation), processing and checks."""

from django.conf import settings
from django.utils import timezone
from huey import crontab
from huey.contrib.djhuey import db_periodic_task, db_task

from disbursement_packages.services.package_checks import check_disbursement_packages
from disbursement_packages.services.package_creation import create_disbursement_packages
from disbursement_packages.services.package_processing import (
    process_disbursement_package as process_disbursement_package_service,
)


def now():
    return timezone.now()


@db_task()
def process_disbursement_package(package_id):
    process_disbursement_package_service(package_id)


@db_task()
def create_disbursement_packages_task():
    """Builds the packages of the day and enqueues one process_disbursement_package per package."""
    result = create_disbursement_packages(now().date())
    for package in result.packages:
        process_disbursement_package(package.id)


@db_periodic_task(crontab(minute="0", hour=",".join(str(hour) for hour in settings.CHECK_PACKAGES_HOURS)))
def check_disbursement_packages_task():
    """Re-enqueues the packages that should be retried. The last run of the day only alerts."""
    current = now()
    result = check_disbursement_packages(current.date(), is_last_run=current.hour == max(settings.CHECK_PACKAGES_HOURS))
    for package_id in result.to_retry:
        process_disbursement_package(package_id)
