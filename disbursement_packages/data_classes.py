from dataclasses import dataclass, field


@dataclass
class PackagingResult:
    packages: list = field(default_factory=list)
    requires_attention: list = field(default_factory=list)


@dataclass
class CheckResult:
    to_retry: list = field(default_factory=list)
