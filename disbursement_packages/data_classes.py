from dataclasses import dataclass, field


@dataclass
class PackagingResult:
    packages: list = field(default_factory=list)
    requires_attention: list = field(default_factory=list)


@dataclass
class CheckResult:
    to_retry: list = field(default_factory=list)
    # Packages stuck in PROCESSING that the check released before deciding.
    released: list = field(default_factory=list)


@dataclass
class ReleaseResult:
    # Moved from PROCESSING to FAILED: the worker that had them is gone.
    released: list = field(default_factory=list)
    # A live worker is processing them (they hold the lock): not touched.
    being_processed: list = field(default_factory=list)
    # In PROCESSING for less than PACKAGE_STUCK_AFTER_MINUTES: not considered stuck yet.
    too_recent: list = field(default_factory=list)
    # Not in PROCESSING: (id, status).
    not_processing: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
