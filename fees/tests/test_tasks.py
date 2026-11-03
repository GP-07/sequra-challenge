"""Cómo se engancha la task mensual. La lógica de negocio se prueba en el servicio."""

from datetime import date, datetime, timezone
from unittest import mock

import pytest

from fees import tasks


@pytest.mark.parametrize(
    ("run_at", "previous_month"),
    (
        (datetime(2023, 3, 1, 0, 30, tzinfo=timezone.utc), date(2023, 2, 1)),
        # Enero calcula diciembre del año anterior.
        (datetime(2023, 1, 1, 0, 30, tzinfo=timezone.utc), date(2022, 12, 1)),
    ),
)
def test_monthly_fees_task_calculates_the_previous_month(run_at, previous_month):
    with mock.patch.object(tasks, "now", return_value=run_at), mock.patch.object(
        tasks, "calculate_monthly_fees"
    ) as calculate:
        tasks.calculate_monthly_fees_task.call_local()

    calculate.assert_called_once_with(previous_month)
