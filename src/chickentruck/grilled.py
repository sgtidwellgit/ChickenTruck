"""grilled_chicken -- knowledge validation.

Before a candidate assertion (`ChickenTender`) becomes accepted
knowledge, it is "put on the grill": checked for structure, resolved
entities, provenance, temporal sanity, schema constraints, custom rules,
and confidence thresholds.

`grill` has no side effects. It returns a `GrillResult` whose status is
ACCEPTED, REJECTED, or NEEDS_REVIEW, along with every `Finding` that led
there. Only an accepted result carries a `Fact` -- and only a `Fact`
can go into `ChickenStock`. Rejected tenders are handed back to the
caller, never silently dropped.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple

from ._temporal import TimePoint
from .coop import ChickenCoop, Mention, Ref
from .recipe import MOMENT, Predicate, Schema
from .tenders import ChickenTender, ConfidenceCombiner, Evidence, Source, noisy_or

ERROR = "error"
WARNING = "warning"
INFO = "info"

ACCEPTED = "accepted"
REJECTED = "rejected"
NEEDS_REVIEW = "needs_review"

ACTIVE = "active"
SUPERSEDED = "superseded"


@dataclass(frozen=True)
class Finding:
    """One observation from the grill.

    Any ``error`` rejects the tender; any ``warning`` sends it to review;
    ``info`` is recorded but does not change the outcome.
    """

    rule: str
    severity: str
    message: str


Rule = Callable[[ChickenTender], Iterable[Finding]]


@dataclass(frozen=True)
class Fact:
    """Accepted knowledge.

    ``fact_id`` is derived from the claim itself (subject, predicate,
    object, validity, qualifiers), so the same fact arriving from two
    sources gets the same ID and `ChickenStock` merges the evidence.
    ``recorded_at`` and ``superseded_at`` are set by the stock.
    """

    fact_id: str
    subject: Ref
    predicate: str
    object: Any
    evidence: Tuple[Evidence, ...] = ()
    confidence: Optional[float] = None
    valid_from: Optional[TimePoint] = None
    valid_to: Optional[TimePoint] = None
    qualifiers: Dict[str, Any] = field(default_factory=dict)
    status: str = ACTIVE
    recorded_at: Optional[datetime] = None
    superseded_at: Optional[datetime] = None

    @property
    def sources(self) -> Tuple[Source, ...]:
        seen: Dict[str, Source] = {}
        for item in self.evidence:
            seen.setdefault(item.source.id, item.source)
        return tuple(seen.values())

    @property
    def active(self) -> bool:
        return self.status == ACTIVE


@dataclass(frozen=True)
class GrillResult:
    """Outcome of running a `ChickenTender` through `grill`."""

    tender: ChickenTender
    status: str
    findings: Tuple[Finding, ...] = ()
    fact: Optional[Fact] = None

    @property
    def accepted(self) -> bool:
        return self.status == ACCEPTED

    @property
    def reasons(self) -> List[str]:
        """Messages for every error and warning, in the order found."""

        return [f.message for f in self.findings if f.severity != INFO]


def grill(
    tender: ChickenTender,
    *,
    schema: Optional[Schema] = None,
    coop: Optional[ChickenCoop] = None,
    rules: Iterable[Rule] = (),
    accept_at: float = 0.5,
    reject_below: float = 0.2,
    require_evidence: bool = True,
    combine: ConfidenceCombiner = noisy_or,
) -> GrillResult:
    """Validate a candidate assertion before it becomes accepted knowledge.

    - ``schema`` enables predicate, domain, range, and moment checks.
    - ``coop`` lets domain and range checks look up entity types.
    - ``rules`` are extra checks, each returning zero or more findings.
    - Confidence below ``reject_below`` rejects; below ``accept_at``
      sends to review. Unknown confidence is noted but not penalized.
    """

    if reject_below > accept_at:
        raise ValueError("reject_below must not exceed accept_at")

    findings: List[Finding] = []
    findings += _structure(tender, require_evidence)
    findings += _temporal(tender)
    if schema is not None:
        findings += _schema(tender, schema, coop)
    for rule in rules:
        findings += list(rule(tender))

    confidence = combine(tender.evidence)
    if confidence is None:
        findings.append(Finding("confidence.unknown", INFO, "no evidence states a confidence"))
    elif confidence < reject_below:
        findings.append(
            Finding(
                "confidence.too_low",
                ERROR,
                f"confidence {confidence:.2f} is below the rejection threshold {reject_below:.2f}",
            )
        )
    elif confidence < accept_at:
        findings.append(
            Finding(
                "confidence.below_accept",
                WARNING,
                f"confidence {confidence:.2f} is below the acceptance threshold {accept_at:.2f}",
            )
        )

    severities = {f.severity for f in findings}
    if ERROR in severities:
        return GrillResult(tender, REJECTED, tuple(findings))
    if WARNING in severities:
        return GrillResult(tender, NEEDS_REVIEW, tuple(findings))
    fact = Fact(
        fact_id=fact_id_for(tender),
        subject=tender.subject,
        predicate=tender.predicate,
        object=tender.object,
        evidence=tender.evidence,
        confidence=confidence,
        valid_from=tender.valid_from,
        valid_to=tender.valid_to,
        qualifiers=dict(tender.qualifiers),
    )
    return GrillResult(tender, ACCEPTED, tuple(findings), fact)


def fact_id_for(tender: ChickenTender) -> str:
    """A stable ID for the claim a tender makes, independent of its evidence."""

    parts = [
        value_key(tender.subject),
        tender.predicate,
        value_key(tender.object),
        value_key(tender.valid_from),
        value_key(tender.valid_to),
        *(f"{k}={value_key(v)}" for k, v in sorted(tender.qualifiers.items())),
    ]
    digest = hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()
    return f"fact:{digest[:16]}"


def value_key(value: Any) -> str:
    """A canonical string for comparing and hashing claim values."""

    if value is None:
        return "none"
    if isinstance(value, Ref):
        return f"ref:{value.id}"
    if isinstance(value, TimePoint):
        return f"time:{value.precision}:{value.isoformat()}"
    if isinstance(value, (date, datetime)):
        return f"time:{value.isoformat()}"
    return f"{type(value).__name__}:{value!r}"


def _structure(tender: ChickenTender, require_evidence: bool) -> List[Finding]:
    found = []
    if not isinstance(tender.predicate, str) or not tender.predicate.strip():
        found.append(Finding("predicate.empty", ERROR, "predicate is empty"))
    if not isinstance(tender.subject, Ref):
        found.append(
            Finding(
                "subject.unresolved",
                WARNING,
                f"subject {str(tender.subject)!r} is not resolved to an entity",
            )
        )
    if tender.object is None:
        found.append(Finding("object.missing", ERROR, "object is missing"))
    elif isinstance(tender.object, Mention):
        found.append(
            Finding(
                "object.unresolved",
                WARNING,
                f"object {tender.object.text!r} is not resolved to an entity",
            )
        )
    if require_evidence and not tender.evidence:
        found.append(Finding("provenance.missing", ERROR, "tender has no evidence"))
    return found


def _temporal(tender: ChickenTender) -> List[Finding]:
    found = []
    for name in ("valid_from", "valid_to"):
        point = getattr(tender, name)
        if point is not None and point.is_naive:
            found.append(Finding("time.naive", ERROR, f"{name} has no timezone"))
    start, end = tender.valid_from, tender.valid_to
    if found or start is None or end is None:
        return found
    if end.earliest() <= start.earliest():
        found.append(
            Finding("time.empty_interval", ERROR, f"valid_to {end} is not after valid_from {start}")
        )
    return found


_LITERAL_CHECKS: Dict[str, Callable[[Any], bool]] = {
    "string": lambda v: isinstance(v, str),
    "integer": lambda v: isinstance(v, int) and not isinstance(v, bool),
    "number": lambda v: isinstance(v, (int, float)) and not isinstance(v, bool),
    "boolean": lambda v: isinstance(v, bool),
    "time": lambda v: isinstance(v, (TimePoint, date, datetime)),
}


def _schema(
    tender: ChickenTender, schema: Schema, coop: Optional[ChickenCoop]
) -> List[Finding]:
    predicate = schema.predicate(tender.predicate)
    if predicate is None:
        if schema.strict:
            return [
                Finding(
                    "schema.unknown_predicate",
                    ERROR,
                    f"predicate {tender.predicate!r} is not defined in the schema",
                )
            ]
        return [
            Finding(
                "schema.unknown_predicate",
                INFO,
                f"predicate {tender.predicate!r} is not in the schema; schema checks skipped",
            )
        ]

    found = []
    if predicate.temporal == MOMENT and tender.valid_to is not None:
        found.append(
            Finding(
                "schema.moment_with_end",
                ERROR,
                f"{predicate.name} is a moment predicate and cannot have valid_to",
            )
        )
    if predicate.domain and isinstance(tender.subject, Ref):
        found += _type_check(
            tender.subject, predicate.domain, schema, coop, "schema.domain", "subject"
        )
    found += _range_check(tender.object, predicate, schema, coop)
    return found


def _range_check(
    obj: Any, predicate: Predicate, schema: Schema, coop: Optional[ChickenCoop]
) -> List[Finding]:
    if predicate.range is None or obj is None or isinstance(obj, Mention):
        return []
    if predicate.range_is_literal:
        if isinstance(obj, Ref) or not _LITERAL_CHECKS[predicate.range](obj):
            return [
                Finding(
                    "schema.range",
                    ERROR,
                    f"{predicate.name} expects a {predicate.range} value, got {obj!r}",
                )
            ]
        return []
    if isinstance(obj, Ref):
        return _type_check(obj, (predicate.range,), schema, coop, "schema.range", "object")
    if isinstance(obj, str):
        return [
            Finding(
                "object.unresolved",
                WARNING,
                f"{predicate.name} expects a {predicate.range} entity; "
                f"{obj!r} is not resolved",
            )
        ]
    return [
        Finding(
            "schema.range",
            ERROR,
            f"{predicate.name} expects a {predicate.range} entity, got {obj!r}",
        )
    ]


def _type_check(
    ref: Ref,
    allowed: Tuple[str, ...],
    schema: Schema,
    coop: Optional[ChickenCoop],
    rule: str,
    role: str,
) -> List[Finding]:
    expected = " or ".join(allowed)
    if coop is None:
        return [Finding(rule, INFO, f"{role} type not checked (no coop given)")]
    entity = coop.get(ref.id)
    if entity is None:
        return [Finding(f"{role}.unknown_entity", WARNING, f"{role} {ref.id!r} is not in the coop")]
    if entity.type is None:
        return [
            Finding(rule, WARNING, f"{role} {ref.id!r} has no type; expected {expected}")
        ]
    if not schema.is_any(entity.type, allowed):
        return [
            Finding(rule, ERROR, f"{role} {ref.id!r} is a {entity.type}; expected {expected}")
        ]
    return []
