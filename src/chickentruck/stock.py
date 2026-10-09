"""chicken_stock -- the store for accepted knowledge.

Chicken stock is the base other dishes build on; `ChickenStock` is the
base for accepted knowledge. It only takes `Fact`s (or accepted
`GrillResult`s), and it keeps two timelines: each fact's validity (when
it is true in the world) and when the stock recorded or superseded it
(what was believed at a given moment). Nothing is ever deleted --
losing facts are marked superseded.

`StockBackend` is the interface every backend implements. `ChickenStock`
is the in-memory reference implementation; other backends (SQLite,
PostgreSQL, Neo4j, ...) come later as adapters against the same
interface.

Conflicts: when the schema marks a predicate single-valued (cardinality
``"one"``), two active facts with the same subject, different objects,
and overlapping validity conflict. The default policy, `keep_both`,
records the `Conflict` and leaves both facts active; a reviewer settles
it with `resolve_conflict`. Other policies pick a winner automatically.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Set, Tuple, Union

from ._temporal import TimeLike, contains, overlaps, parse_time
from .coop import Ref
from .grilled import ACTIVE, SUPERSEDED, Fact, GrillResult, value_key
from .recipe import ONE, Schema
from .tenders import ConfidenceCombiner, Source, noisy_or

Policy = Callable[[Fact, Fact], Optional[Fact]]
"""Given a new fact and a conflicting existing one, return the winner, or None to keep both."""


def keep_both(new: Fact, existing: Fact) -> Optional[Fact]:
    """Never pick a winner; the conflict is recorded for review."""

    return None


def highest_confidence(new: Fact, existing: Fact) -> Optional[Fact]:
    """The fact with higher combined confidence wins; ties or unknowns keep both."""

    return _pick(new, existing, lambda f: f.confidence)


def highest_authority(new: Fact, existing: Fact) -> Optional[Fact]:
    """The fact backed by the most authoritative source wins."""

    def authority(fact: Fact) -> Optional[float]:
        values = [s.authority for s in fact.sources if s.authority is not None]
        return max(values) if values else None

    return _pick(new, existing, authority)


def most_recent_evidence(new: Fact, existing: Fact) -> Optional[Fact]:
    """The fact with the most recently extracted evidence wins."""

    def latest(fact: Fact) -> Optional[datetime]:
        values = [e.extracted_at for e in fact.evidence if e.extracted_at is not None]
        return max(values) if values else None

    return _pick(new, existing, latest)


def _pick(new: Fact, existing: Fact, score: Callable[[Fact], Any]) -> Optional[Fact]:
    a, b = score(new), score(existing)
    if a is None or b is None or a == b:
        return None
    return new if a > b else existing


@dataclass(frozen=True)
class Conflict:
    """Two facts that cannot both be true.

    ``winner`` is the surviving fact's ID once settled (by policy or by
    `resolve_conflict`), ``None`` while the conflict is open.
    """

    conflict_id: str
    fact_ids: Tuple[str, str]
    subject: Ref
    predicate: str
    detected_at: datetime
    policy: str
    winner: Optional[str] = None

    @property
    def open(self) -> bool:
        return self.winner is None


class StockBackend(Protocol):
    """What every knowledge store must provide."""

    def add(self, item: Union[Fact, GrillResult]) -> Fact:
        ...

    def get(self, fact_id: str) -> Optional[Fact]:
        ...

    def find(
        self,
        subject: Union[Ref, str, None] = None,
        predicate: Optional[str] = None,
        object: Any = None,
        *,
        valid_at: Optional[TimeLike] = None,
        as_of: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        include_superseded: bool = False,
    ) -> List[Fact]:
        ...

    def all(self) -> List[Fact]:
        ...

    def conflicts(self, open_only: bool = False) -> List[Conflict]:
        ...

    def resolve_conflict(self, conflict_id: str, winner: str) -> Conflict:
        ...

    def __len__(self) -> int:
        ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class ChickenStock:
    """In-memory, indexed store for accepted knowledge (`StockBackend`).

    Adding a fact whose ``fact_id`` is already stored merges the new
    evidence into it and recomputes confidence. Merged evidence is
    current-state only: ``as_of`` queries see which facts were believed
    at a moment, with the evidence they hold now.
    """

    schema: Optional[Schema] = None
    policy: Policy = keep_both
    combine: ConfidenceCombiner = noisy_or
    clock: Callable[[], datetime] = _utc_now
    _facts: Dict[str, Fact] = field(default_factory=dict, repr=False)
    _by_subject: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _by_predicate: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _by_object: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _conflicts: Dict[str, Conflict] = field(default_factory=dict, repr=False)

    def add(self, item: Union[Fact, GrillResult]) -> Fact:
        """Store an accepted fact and return the stored version."""

        fact = self._as_fact(item)
        now = self.clock()
        existing = self._facts.get(fact.fact_id)
        if existing is not None:
            evidence = tuple(dict.fromkeys(existing.evidence + fact.evidence))
            merged = dataclasses.replace(
                existing, evidence=evidence, confidence=self.combine(evidence)
            )
            self._facts[fact.fact_id] = merged
            return merged

        fact = dataclasses.replace(
            fact, status=ACTIVE, recorded_at=fact.recorded_at or now, superseded_at=None
        )
        self._facts[fact.fact_id] = fact
        self._index(fact)
        self._detect_conflicts(fact, now)
        return self._facts[fact.fact_id]

    def get(self, fact_id: str) -> Optional[Fact]:
        return self._facts.get(fact_id)

    def find(
        self,
        subject: Union[Ref, str, None] = None,
        predicate: Optional[str] = None,
        object: Any = None,
        *,
        valid_at: Optional[TimeLike] = None,
        as_of: Optional[datetime] = None,
        min_confidence: Optional[float] = None,
        include_superseded: bool = False,
    ) -> List[Fact]:
        """Facts matching a subject/predicate/object pattern plus filters.

        - ``subject``: a `Ref` or entity ID. ``object``: a `Ref` or literal.
        - ``valid_at``: only facts true in the world at that time.
        - ``as_of``: only facts the stock believed at that moment
          (recorded by then, not yet superseded).
        - ``include_superseded``: without ``as_of``, also return
          superseded facts.
        """

        ids: Optional[Set[str]] = None
        if subject is not None:
            subject_id = subject.id if isinstance(subject, Ref) else subject
            ids = self._narrow(ids, self._by_subject.get(subject_id, set()))
        if predicate is not None:
            ids = self._narrow(ids, self._by_predicate.get(predicate, set()))
        if object is not None:
            ids = self._narrow(ids, self._by_object.get(value_key(object), set()))

        point = parse_time(valid_at)
        results = []
        for fact_id, fact in self._facts.items():
            if ids is not None and fact_id not in ids:
                continue
            if as_of is not None:
                if fact.recorded_at is None or fact.recorded_at > as_of:
                    continue
                if fact.superseded_at is not None and fact.superseded_at <= as_of:
                    continue
            elif not include_superseded and not fact.active:
                continue
            if point is not None and not contains(fact.valid_from, fact.valid_to, point):
                continue
            if min_confidence is not None and (
                fact.confidence is None or fact.confidence < min_confidence
            ):
                continue
            results.append(fact)
        return results

    def all(self) -> List[Fact]:
        """Every stored fact, superseded included, in insertion order."""

        return list(self._facts.values())

    def __len__(self) -> int:
        return len(self._facts)

    def __iter__(self) -> Iterator[Fact]:
        return iter(self.all())

    def sources(self) -> List[Source]:
        seen: Dict[str, Source] = {}
        for fact in self._facts.values():
            for source in fact.sources:
                seen.setdefault(source.id, source)
        return list(seen.values())

    def conflicts(self, open_only: bool = False) -> List[Conflict]:
        return [c for c in self._conflicts.values() if c.open or not open_only]

    def resolve_conflict(self, conflict_id: str, winner: str) -> Conflict:
        """Settle a conflict: ``winner`` stays, the other fact is superseded."""

        conflict = self._conflicts[conflict_id]
        if winner not in conflict.fact_ids:
            raise ValueError(f"{winner!r} is not part of conflict {conflict_id!r}")
        loser = conflict.fact_ids[1] if conflict.fact_ids[0] == winner else conflict.fact_ids[0]
        self._supersede(loser, self.clock())
        settled = dataclasses.replace(conflict, winner=winner)
        self._conflicts[conflict_id] = settled
        return settled

    def _as_fact(self, item: Union[Fact, GrillResult]) -> Fact:
        if isinstance(item, GrillResult):
            if not item.accepted or item.fact is None:
                raise ValueError(f"only accepted results can be stocked (status: {item.status})")
            return item.fact
        if isinstance(item, Fact):
            return item
        raise TypeError(f"ChickenStock stores Facts, not {type(item).__name__}")

    def _detect_conflicts(self, fact: Fact, now: datetime) -> None:
        if self.schema is None:
            return
        predicate = self.schema.predicate(fact.predicate)
        if predicate is None or predicate.cardinality != ONE:
            return
        rivals = self._by_subject.get(fact.subject.id, set()) & self._by_predicate.get(
            fact.predicate, set()
        )
        for rival_id in [i for i in self._facts if i in rivals]:
            rival = self._facts[rival_id]
            if rival_id == fact.fact_id or not rival.active:
                continue
            if value_key(rival.object) == value_key(fact.object):
                continue
            if not overlaps(fact.valid_from, fact.valid_to, rival.valid_from, rival.valid_to):
                continue
            winner = self.policy(self._facts[fact.fact_id], rival)
            conflict = Conflict(
                conflict_id=f"conflict:{len(self._conflicts) + 1}",
                fact_ids=(rival_id, fact.fact_id),
                subject=fact.subject,
                predicate=fact.predicate,
                detected_at=now,
                policy=getattr(self.policy, "__name__", repr(self.policy)),
                winner=winner.fact_id if winner is not None else None,
            )
            self._conflicts[conflict.conflict_id] = conflict
            if winner is None:
                continue
            loser = rival_id if winner.fact_id == fact.fact_id else fact.fact_id
            self._supersede(loser, now)
            if loser == fact.fact_id:
                break

    def _supersede(self, fact_id: str, now: datetime) -> None:
        fact = self._facts[fact_id]
        if fact.active:
            self._facts[fact_id] = dataclasses.replace(
                fact, status=SUPERSEDED, superseded_at=now
            )

    def _index(self, fact: Fact) -> None:
        self._by_subject.setdefault(fact.subject.id, set()).add(fact.fact_id)
        self._by_predicate.setdefault(fact.predicate, set()).add(fact.fact_id)
        self._by_object.setdefault(value_key(fact.object), set()).add(fact.fact_id)

    @staticmethod
    def _narrow(ids: Optional[Set[str]], matches: Set[str]) -> Set[str]:
        return set(matches) if ids is None else ids & matches
