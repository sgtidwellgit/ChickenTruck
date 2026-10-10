"""chicken_nuggets -- atomic knowledge, stripped to the bone.

A `Nugget` is the smallest unit of extracted knowledge: one
subject/predicate/object fact, e.g. ("Benjamin Franklin", "BORN_IN",
"Boston"), with no evidence, time, or confidence attached.
`extract_nuggets` runs an extractor (see `chicken_fryer`) and returns
just those bare facts; use the extractor directly to keep provenance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, List, Optional

if TYPE_CHECKING:
    from .fryer import Extractor
    from .tenders import Source


@dataclass(frozen=True)
class Nugget:
    """A single atomic fact: subject, predicate, and object."""

    subject: str
    predicate: str
    object: Any


def extract_nuggets(
    text: str, extractor: "Extractor", *, source: Optional["Source"] = None
) -> List[Nugget]:
    """Break raw text into atomic `Nugget` facts using ``extractor``.

    Entity mentions become their text; literal values are kept as-is.
    ``source`` defaults to an anonymous ``Source("text")``.
    """

    from .coop import Mention, Ref
    from .tenders import Source

    def bare(value: Any) -> Any:
        return str(value) if isinstance(value, (Mention, Ref)) else value

    tenders = extractor.extract(text, source=source or Source("text"))
    return [Nugget(str(bare(t.subject)), t.predicate, bare(t.object)) for t in tenders]
