"""chicken_tenders -- candidate assertions awaiting validation.

A `ChickenTender` is a proposed assertion "tendered" for consideration:
a subject/predicate/object claim plus the `Evidence` behind it, its
temporal validity, and any qualifiers. Extracted knowledge is never
automatically authoritative -- it passes through this candidate stage
and `grill` before it is accepted.

Provenance is structured: each piece of `Evidence` points at a `Source`
and records where in it the claim was found, by which extractor, and
with what confidence.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Dict, Iterable, Optional, Tuple, Union

from ._temporal import TimeLike, TimePoint, parse_time
from .coop import Mention, Ref
from .nuggets import Nugget

DOCUMENT = "document"
API = "api"
HUMAN = "human"
MODEL = "model"
SOURCE_KINDS = (DOCUMENT, API, HUMAN, MODEL)


def _check_unit(name: str, value: Optional[float]) -> None:
    if value is not None and not 0.0 <= value <= 1.0:
        raise ValueError(f"{name} must be between 0 and 1, got {value!r}")


@dataclass(frozen=True)
class Source:
    """Where information came from.

    ``authority`` (0..1, optional) is how much this source is trusted; it
    weights the confidence of every piece of evidence drawn from it.
    """

    id: str
    kind: str = DOCUMENT
    uri: Optional[str] = None
    title: Optional[str] = None
    retrieved_at: Optional[datetime] = None
    authority: Optional[float] = None

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("source id must not be empty")
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"unknown source kind {self.kind!r}")
        _check_unit("authority", self.authority)


@dataclass(frozen=True)
class Evidence:
    """One sighting of a claim in a source.

    ``locator`` says where in the source (a span, page, or row);
    ``confidence`` (0..1, optional) is how strongly this evidence
    suggests the claim is true.
    """

    source: Source
    locator: Optional[str] = None
    quote: Optional[str] = None
    confidence: Optional[float] = None
    extractor: Optional[str] = None
    extracted_at: Optional[datetime] = None

    def __post_init__(self) -> None:
        _check_unit("confidence", self.confidence)

    @property
    def weighted_confidence(self) -> Optional[float]:
        """Confidence scaled by the source's authority (unknown authority = 1)."""

        if self.confidence is None:
            return None
        authority = 1.0 if self.source.authority is None else self.source.authority
        return self.confidence * authority


ConfidenceCombiner = Callable[[Iterable[Evidence]], Optional[float]]


def noisy_or(evidence: Iterable[Evidence]) -> Optional[float]:
    """Combine independent evidence as ``1 - prod(1 - c_i * a_i)``.

    Evidence with unknown confidence is skipped; if none is known, the
    result is ``None``.
    """

    known = [e.weighted_confidence for e in evidence if e.confidence is not None]
    if not known:
        return None
    disbelief = 1.0
    for value in known:
        disbelief *= 1.0 - value
    return 1.0 - disbelief


Subject = Union[str, Mention, Ref]


@dataclass(frozen=True)
class ChickenTender:
    """A candidate assertion, not yet validated as accepted knowledge.

    ``subject`` is an entity: a plain string or `Mention` before
    resolution, a `Ref` after. ``object`` is either an entity (`Mention`
    or `Ref`) or a literal value. ``valid_from`` / ``valid_to`` accept
    anything `parse_time` does and are stored as `TimePoint`s.
    """

    subject: Subject
    predicate: str
    object: Any
    evidence: Tuple[Evidence, ...] = ()
    valid_from: Optional[TimeLike] = None
    valid_to: Optional[TimeLike] = None
    qualifiers: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "evidence", tuple(self.evidence))
        object.__setattr__(self, "valid_from", parse_time(self.valid_from))
        object.__setattr__(self, "valid_to", parse_time(self.valid_to))

    @property
    def confidence(self) -> Optional[float]:
        """Combined confidence of this tender's evidence (noisy-OR)."""

        return noisy_or(self.evidence)

    @property
    def sources(self) -> Tuple[Source, ...]:
        seen: Dict[str, Source] = {}
        for item in self.evidence:
            seen.setdefault(item.source.id, item.source)
        return tuple(seen.values())

    @classmethod
    def from_nugget(cls, nugget: Nugget, **fields: Any) -> "ChickenTender":
        """Wrap an extracted `Nugget` as a candidate assertion."""

        return cls(
            subject=nugget.subject,
            predicate=nugget.predicate,
            object=nugget.object,
            **fields,
        )

