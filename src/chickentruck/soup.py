"""chicken_soup -- knowledge prepared for RAG systems and agents.

- `render_facts` turns facts into short, cited sentences ready to drop
  into a prompt as retrieval context.
- `check_claim` answers whether the stock supports, contradicts, or
  disputes a claim (or knows nothing about it), with the facts and
  evidence behind the answer -- a grounding check an agent can call
  before stating something as true.

Both work with any `StockBackend`. Entity labels come from a
`ChickenCoop` when given, otherwise from the stock's entity store.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple, Union

from ._temporal import TimeLike
from .coop import ChickenCoop, Entity, Mention, Ref
from .grilled import Fact, value_key
from .platter import json_value
from .recipe import ONE
from .stock import StockBackend
from .tenders import Evidence, Source

SUPPORTED = "supported"
CONTRADICTED = "contradicted"
DISPUTED = "disputed"
UNKNOWN = "unknown"


def _labeler(coop: Optional[ChickenCoop], stock: Optional[StockBackend]):
    def label(entity_id: str) -> str:
        entity: Optional[Entity] = None
        if coop is not None:
            entity = coop.get(entity_id)
        elif stock is not None:
            entity = stock.get_entity(entity_id)
        return entity.label if entity is not None else entity_id

    return label


def humanize_predicate(predicate: str) -> str:
    """``"BORN_IN"`` -> ``"born in"``."""

    return predicate.replace("_", " ").strip().lower()


def render_facts(
    facts: Iterable[Fact],
    *,
    coop: Optional[ChickenCoop] = None,
    stock: Optional[StockBackend] = None,
    humanize: bool = True,
    cite: bool = True,
) -> str:
    """Render facts as cited, prompt-ready lines.

    Each fact becomes one line such as::

        - Benjamin Franklin born in Boston (from 1706-01-17; confidence 0.86) [1]

    followed by a numbered ``Sources:`` list when ``cite`` is true.
    Returns an empty string when there are no facts.
    """

    label = _labeler(coop, stock)
    citations: Dict[str, int] = {}
    cited_sources: List[Source] = []
    lines = []
    for fact in facts:
        obj = label(fact.object.id) if isinstance(fact.object, Ref) else _plain(fact.object)
        predicate = humanize_predicate(fact.predicate) if humanize else fact.predicate
        details = [f"{k}: {_plain(v)}" for k, v in sorted(fact.qualifiers.items())]
        if fact.valid_from and fact.valid_to:
            details.append(f"from {fact.valid_from} to {fact.valid_to}")
        elif fact.valid_from:
            details.append(f"from {fact.valid_from}")
        elif fact.valid_to:
            details.append(f"until {fact.valid_to}")
        if fact.confidence is not None:
            details.append(f"confidence {fact.confidence:.2f}")
        if not fact.active:
            details.append("superseded")

        line = f"- {label(fact.subject.id)} {predicate} {obj}"
        if details:
            line += f" ({'; '.join(details)})"
        if cite and fact.sources:
            numbers = []
            for source in fact.sources:
                if source.id not in citations:
                    citations[source.id] = len(citations) + 1
                    cited_sources.append(source)
                numbers.append(str(citations[source.id]))
            line += f" [{', '.join(numbers)}]"
        lines.append(line)

    if not lines:
        return ""
    if cite and cited_sources:
        lines.append("")
        lines.append("Sources:")
        for source in cited_sources:
            name = source.title or source.id
            lines.append(f"[{citations[source.id]}] {name}" + (f" - {source.uri}" if source.uri else ""))
    return "\n".join(lines)


def _plain(value: Any) -> str:
    plain = json_value(value)
    return plain if isinstance(plain, str) else str(plain)


@dataclass(frozen=True)
class ClaimCheck:
    """The stock's answer about one claim.

    - ``supported``: an active fact states the claim.
    - ``contradicted``: the predicate is single-valued and an active fact
      states a different value.
    - ``disputed``: both of the above (an open conflict, typically).
    - ``unknown``: the stock has nothing either way.
    """

    verdict: str
    supporting: Tuple[Fact, ...] = ()
    contradicting: Tuple[Fact, ...] = ()

    @property
    def supported(self) -> bool:
        return self.verdict == SUPPORTED

    @property
    def confidence(self) -> Optional[float]:
        """Highest confidence among supporting facts."""

        values = [f.confidence for f in self.supporting if f.confidence is not None]
        return max(values) if values else None

    @property
    def evidence(self) -> Tuple[Evidence, ...]:
        return tuple(e for f in self.supporting for e in f.evidence)


def check_claim(
    stock: StockBackend,
    subject: Union[Ref, Mention, str],
    predicate: str,
    object: Any,
    *,
    at: Optional[TimeLike] = None,
    coop: Optional[ChickenCoop] = None,
) -> ClaimCheck:
    """Check a claim against stocked knowledge.

    ``subject`` is a `Ref`, an entity ID, or -- when a ``coop`` is given
    -- a name to resolve (never creating entities). ``object`` may be a
    `Ref`, a literal, or a string; a string matches as a literal, as an
    entity ID, and -- with a coop -- as the entity it names. ``at`` limits the check
    to facts valid at that time.

    Contradiction needs the stock's schema to mark the predicate
    single-valued; without that, a different value is not evidence
    against the claim.
    """

    subject_id = _subject_id(subject, coop)
    if subject_id is None:
        return ClaimCheck(UNKNOWN)

    wanted = _object_keys(object, coop)
    facts = stock.find(subject_id, predicate, valid_at=at)
    supporting = tuple(f for f in facts if value_key(f.object) in wanted)

    contradicting: Tuple[Fact, ...] = ()
    definition = stock.schema.predicate(predicate) if stock.schema is not None else None
    if definition is not None and definition.cardinality == ONE:
        contradicting = tuple(f for f in facts if value_key(f.object) not in wanted)

    if supporting and contradicting:
        verdict = DISPUTED
    elif supporting:
        verdict = SUPPORTED
    elif contradicting:
        verdict = CONTRADICTED
    else:
        verdict = UNKNOWN
    return ClaimCheck(verdict, supporting, contradicting)


def _subject_id(subject: Union[Ref, Mention, str], coop: Optional[ChickenCoop]) -> Optional[str]:
    if isinstance(subject, Ref):
        return subject.id
    text = subject.text if isinstance(subject, Mention) else subject
    hint = subject.type if isinstance(subject, Mention) else None
    if coop is None:
        return text
    if text in coop:
        return text
    return coop.resolve(text, hint, create=False).entity_id


def _object_keys(obj: Any, coop: Optional[ChickenCoop]) -> Set[str]:
    if isinstance(obj, Ref):
        return {value_key(obj)}
    if isinstance(obj, Mention):
        if coop is None:
            return {value_key(Ref(obj.text))}
        resolved = coop.resolve(obj.text, obj.type, create=False).entity_id
        return {value_key(Ref(resolved))} if resolved else set()
    keys = {value_key(obj)}
    if isinstance(obj, str):
        keys.add(value_key(Ref(obj)))  # an entity ID given as a string
    if isinstance(obj, str) and coop is not None:
        resolved = coop.resolve(obj, create=False).entity_id
        if resolved:
            keys.add(value_key(Ref(resolved)))
    return keys
