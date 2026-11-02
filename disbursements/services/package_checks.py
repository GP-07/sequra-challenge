from datetime import date

from disbursements.data_classes import CheckResult


def check_disbursement_packages(run_date: date, *, is_last_run: bool) -> CheckResult:
    raise NotImplementedError
