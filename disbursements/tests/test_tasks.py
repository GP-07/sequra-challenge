"""How the daily creation task is wired. The business logic is tested in the services."""

import logging
from datetime import date, datetime, timezone
from unittest import mock

import pytest
from django.db import OperationalError

from disbursements import tasks
from merchants.models import Merchant

NOW = datetime(2023, 2, 8, 0, 5, tzinfo=timezone.utc)


def test_creates_daily_and_weekly_disbursements_and_then_enqueues_the_packaging():
    calls = mock.Mock()
    with mock.patch.object(tasks, "now", return_value=NOW), mock.patch.object(
        tasks, "create_disbursements", calls.create
    ), mock.patch.object(tasks, "create_disbursement_packages_task", calls.package):
        tasks.create_disbursements_task.call_local()

    assert calls.mock_calls == [
        mock.call.create(date(2023, 2, 8), Merchant.Frequency.DAILY),
        mock.call.create(date(2023, 2, 8), Merchant.Frequency.WEEKLY),
        mock.call.package(),
    ]


@pytest.mark.parametrize(
    ("retries_left", "alerted"),
    (
        # Huey will still retry it: no alert.
        (1, False),
        # Last attempt: CRITICAL alert.
        (0, True),
    ),
)
def test_failed_creation_does_not_enqueue_the_packaging(caplog, retries_left, alerted):
    with mock.patch.object(tasks, "now", return_value=NOW), mock.patch.object(
        tasks, "create_disbursements", side_effect=OperationalError("connection lost")
    ), mock.patch.object(tasks, "create_disbursement_packages_task") as package, caplog.at_level(logging.CRITICAL):
        with pytest.raises(OperationalError):
            tasks.create_disbursements_task.call_local(task=mock.Mock(retries=retries_left))

    package.assert_not_called()
    critical = [record.getMessage() for record in caplog.records if record.levelno == logging.CRITICAL]
    assert critical == (["Disbursements of 2023-02-08 could not be created: connection lost"] if alerted else [])
