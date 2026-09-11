"""grilled_chicken -- knowledge validation.

Before a candidate assertion (`ChickenTender`) becomes accepted knowledge,
it is "put on the grill": checked against subject/predicate/object type
rules, ontology constraints, required provenance, temporal validity, and
confidence thresholds. That rule engine is future design work (see
PROJECT.md) -- this module only scaffolds the shape validation will
eventually take.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .tenders import ChickenTender

ValidationRule = Callable[[ChickenTender], bool]


@dataclass
class GrillResult:
    """Outcome of running a `ChickenTender` through `grill`."""

    tender: ChickenTender
    accepted: bool
    reasons: list[str]


def grill(
    tender: ChickenTender, rules: list[ValidationRule] | None = None
) -> GrillResult:
    """Validate a candidate assertion before it becomes accepted knowledge.

    This is a design placeholder. It always raises so callers cannot
    mistake "no rules failed" for "this was actually validated" --
    ChickenTruck's validation rule engine has not been designed yet.
    """

    raise NotImplementedError(
        "grill() is a design placeholder -- ChickenTruck's validation "
        "rule engine has not been implemented yet."
    )
