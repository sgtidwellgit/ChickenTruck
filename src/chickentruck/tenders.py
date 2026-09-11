"""chicken_tenders -- candidate assertions awaiting validation.

A `ChickenTender` is a proposed assertion "tendered" for consideration: it
carries the same subject/predicate/object shape as a `Nugget`, plus the
metadata (source, confidence, temporal range, extraction details) that
`grilled_chicken` will eventually use to decide whether it becomes
accepted knowledge. Extracted knowledge is never automatically
authoritative -- it passes through this candidate stage first.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .nuggets import Nugget


@dataclass
class ChickenTender:
    """A candidate assertion, not yet validated as accepted knowledge."""

    subject: str
    predicate: str
    object: Any
    source: str | None = None
    confidence: float | None = None
    valid_from: str | None = None
    valid_to: str | None = None
    extraction_metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_nugget(cls, nugget: Nugget, **metadata: Any) -> "ChickenTender":
        """Wrap an extracted `Nugget` as a candidate assertion."""

        return cls(
            subject=nugget.subject,
            predicate=nugget.predicate,
            object=nugget.object,
            **metadata,
        )
