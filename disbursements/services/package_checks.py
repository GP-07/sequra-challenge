from dataclasses import dataclass, field
from datetime import date


@dataclass
class CheckResult:
    to_retry: list = field(default_factory=list)


def check_disbursement_packages(run_date: date, *, is_last_run: bool) -> CheckResult:
    raise NotImplementedError
