from dataclasses import dataclass, field


@dataclass
class PackagingResult:
    packages: list = field(default_factory=list)
    requires_attention: list = field(default_factory=list)


@dataclass
class CheckResult:
    to_retry: list = field(default_factory=list)


@dataclass
class ReleaseResult:
    # Pasaron de PROCESSING a FAILED: el worker que los tenía ya no está.
    released: list = field(default_factory=list)
    # Un worker vivo los está procesando (tienen el lock): no se tocan.
    being_processed: list = field(default_factory=list)
    # En PROCESSING hace menos de PACKAGE_STUCK_AFTER_MINUTES: todavía no se consideran trabados.
    too_recent: list = field(default_factory=list)
    # No están en PROCESSING: (id, estado).
    not_processing: list = field(default_factory=list)
    not_found: list = field(default_factory=list)
