"""chicken_nuggets -- atomic knowledge extraction and representation.

A `Nugget` is the smallest unit of extracted knowledge: one
subject/predicate/object fact, e.g. ("Benjamin Franklin", "BORN_IN",
"Boston"). `extract_nuggets` is where raw text (or other raw information)
will eventually be broken down into nuggets -- entity extraction,
relationship extraction, and coreference resolution are future design
work (see PROJECT.md), not implemented here yet.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Nugget:
    """A single atomic fact: subject, predicate, and object."""

    subject: str
    predicate: str
    object: Any


def extract_nuggets(text: str) -> list[Nugget]:
    """Break raw text into atomic `Nugget` facts.

    This is a design placeholder. It raises rather than returning a fake
    or trivial result that could be mistaken for real extraction.
    """

    raise NotImplementedError(
        "extract_nuggets() is a design placeholder -- ChickenTruck's "
        "extraction pipeline has not been implemented yet."
    )
