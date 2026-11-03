"""Cómo se enganchan las tasks de huey. La lógica de negocio se prueba en los servicios."""

from datetime import date, datetime, timezone
from unittest import mock

import pytest

from disbursement_packages.data_classes import CheckResult, PackagingResult
from disbursements import tasks

NOW = datetime(2023, 2, 8, 0, 5, tzinfo=timezone.utc)


def test_packages_task_enqueues_one_process_per_package_at_the_end():
    packages = [mock.Mock(id=1), mock.Mock(id=2)]
    with mock.patch.object(tasks, "now", return_value=NOW), mock.patch.object(
        tasks, "create_disbursement_packages", return_value=PackagingResult(packages=packages)
    ) as create, mock.patch.object(tasks, "process_disbursement_package") as process:
        tasks.create_disbursement_packages_task.call_local()

    create.assert_called_once_with(date(2023, 2, 8))
    process.assert_has_calls([mock.call(1), mock.call(2)])


@pytest.mark.parametrize(
    ("hour", "is_last_run"),
    (
        (2, False),
        (4, False),
        (6, True)
    )
)
def test_check_task_retries_and_knows_when_it_is_the_last_run(hour, is_last_run):
    with mock.patch.object(tasks, "now", return_value=NOW.replace(hour=hour)), mock.patch.object(
        tasks, "check_disbursement_packages", return_value=CheckResult(to_retry=[7])
    ) as check, mock.patch.object(tasks, "process_disbursement_package") as process:
        tasks.check_disbursement_packages_task.call_local()

    check.assert_called_once_with(date(2023, 2, 8), is_last_run=is_last_run)
    process.assert_called_once_with(7)


def test_monthly_fees_task_calculates_the_previous_month():
    with mock.patch.object(tasks, "now", return_value=datetime(2023, 3, 1, 0, 30, tzinfo=timezone.utc)), mock.patch.object(
        tasks, "calculate_monthly_fees"
    ) as calculate:
        tasks.calculate_monthly_fees_task.call_local()

    calculate.assert_called_once_with(date(2023, 2, 1))
