from dataclasses import dataclass, field


@dataclass
class GenerationResult:
    orders: list = field(default_factory=list)
    created_merchants: list = field(default_factory=list)
