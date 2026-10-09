"""chicken_stock -- the store for accepted knowledge.

Chicken stock is the base other dishes build on; `ChickenStock` is the
base for accepted knowledge. It only takes `Fact`s (or accepted
`GrillResult`s), and it keeps two timelines: each fact's validity (when
it is true in the world) and when the stock recorded or superseded it
(what was believed at a given moment). Nothing is ever deleted --
losing facts are marked superseded.

`StockBackend` is the interface every backend implements. The rules
(merging, conflict detection, querying) live once in `StockLogic`;
backends only supply storage primitives. `ChickenStock` keeps everything
in memory; `SqliteStock` persists to a SQLite file. Backends also
persist entities, so a `ChickenCoop` can live in the same store.

Conflicts: when the schema marks a predicate single-valued (cardinality
``"one"``), two active facts with the same subject, different objects,
and overlapping validity conflict. The default policy, `keep_both`,
records the `Conflict` and leaves both facts active; a reviewer settles
it with `resolve_conflict`. Other policies pick a winner automatically.
"""

from __future__ import annotations

import dataclasses
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterator, List, Optional, Protocol, Set, Tuple, Union

from ._temporal import TimeLike, contains, overlaps, parse_time
from .coop import Entity, Ref
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

    schema: Optional[Schema]

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

    def sources(self) -> List[Source]:
        ...

    def conflicts(self, open_only: bool = False) -> List[Conflict]:
        ...

    def resolve_conflict(self, conflict_id: str, winner: str) -> Conflict:
        ...

    def put_entity(self, entity: Entity) -> None:
        ...

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        ...

    def entities(self) -> List[Entity]:
        ...

    def __len__(self) -> int:
        ...


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class StockLogic:
    """The rules every backend shares, written against storage primitives.

    A backend sets ``schema``, ``policy``, ``combine``, and ``clock`` and
    implements the underscore methods below. Adding a fact whose
    ``fact_id`` is already stored merges the new evidence into it and
    recomputes confidence. Merged evidence is current-state only:
    ``as_of`` queries see which facts were believed at a moment, with
    the evidence they hold now.
    """

    schema: Optional[Schema]
    policy: Policy
    combine: ConfidenceCombiner
    clock: Callable[[], datetime]

    # -- storage primitives -------------------------------------------------

    def _load(self, fact_id: str) -> Optional[Fact]:
        raise NotImplementedError

    def _save(self, fact: Fact, new: bool) -> None:
        raise NotImplementedError

    def _match(
        self, subject_id: Optional[str], predicate: Optional[str], object_key: Optional[str]
    ) -> List[Fact]:
        """Stored facts matching the pattern (``None`` = any), in insertion order."""

        raise NotImplementedError

    def _load_conflicts(self) -> List[Conflict]:
        raise NotImplementedError

    def _save_conflict(self, conflict: Conflict, new: bool) -> None:
        raise NotImplementedError

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        yield

    # -- shared behavior ----------------------------------------------------

    def add(self, item: Union[Fact, GrillResult]) -> Fact:
        """Store an accepted fact and return the stored version."""

        fact = _as_fact(item)
        with self._transaction():
            now = self.clock()
            existing = self._load(fact.fact_id)
            if existing is not None:
                evidence = tuple(dict.fromkeys(existing.evidence + fact.evidence))
                merged = dataclasses.replace(
                    existing, evidence=evidence, confidence=self.combine(evidence)
                )
                self._save(merged, new=False)
                return merged

            fact = dataclasses.replace(
                fact, status=ACTIVE, recorded_at=fact.recorded_at or now, superseded_at=None
            )
            self._save(fact, new=True)
            self._detect_conflicts(fact, now)
            return self._load(fact.fact_id)

    def get(self, fact_id: str) -> Optional[Fact]:
        return self._load(fact_id)

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

        subject_id = subject.id if isinstance(subject, Ref) else subject
        object_key = None if object is None else value_key(object)
        point = parse_time(valid_at)
        results = []
        for fact in self._match(subject_id, predicate, object_key):
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

        return self._match(None, None, None)

    def __iter__(self) -> Iterator[Fact]:
        return iter(self.all())

    def sources(self) -> List[Source]:
        seen: Dict[str, Source] = {}
        for fact in self.all():
            for source in fact.sources:
                seen.setdefault(source.id, source)
        return list(seen.values())

    def conflicts(self, open_only: bool = False) -> List[Conflict]:
        return [c for c in self._load_conflicts() if c.open or not open_only]

    def resolve_conflict(self, conflict_id: str, winner: str) -> Conflict:
        """Settle a conflict: ``winner`` stays, the other fact is superseded."""

        with self._transaction():
            matches = [c for c in self._load_conflicts() if c.conflict_id == conflict_id]
            if not matches:
                raise KeyError(conflict_id)
            conflict = matches[0]
            if winner not in conflict.fact_ids:
                raise ValueError(f"{winner!r} is not part of conflict {conflict_id!r}")
            a, b = conflict.fact_ids
            self._supersede(b if a == winner else a, self.clock())
            settled = dataclasses.replace(conflict, winner=winner)
            self._save_conflict(settled, new=False)
            return settled

    def _detect_conflicts(self, fact: Fact, now: datetime) -> None:
        if self.schema is None:
            return
        predicate = self.schema.predicate(fact.predicate)
        if predicate is None or predicate.cardinality != ONE:
            return
        for rival in self._match(fact.subject.id, fact.predicate, None):
            if rival.fact_id == fact.fact_id or not rival.active:
                continue
            if value_key(rival.object) == value_key(fact.object):
                continue
            if not overlaps(fact.valid_from, fact.valid_to, rival.valid_from, rival.valid_to):
                continue
            winner = self.policy(self._load(fact.fact_id), rival)
            conflict = Conflict(
                conflict_id=f"conflict:{len(self._load_conflicts()) + 1}",
                fact_ids=(rival.fact_id, fact.fact_id),
                subject=fact.subject,
                predicate=fact.predicate,
                detected_at=now,
                policy=getattr(self.policy, "__name__", repr(self.policy)),
                winner=winner.fact_id if winner is not None else None,
            )
            self._save_conflict(conflict, new=True)
            if winner is None:
                continue
            loser = rival.fact_id if winner.fact_id == fact.fact_id else fact.fact_id
            self._supersede(loser, now)
            if loser == fact.fact_id:
                break

    def _supersede(self, fact_id: str, now: datetime) -> None:
        fact = self._load(fact_id)
        if fact is not None and fact.active:
            self._save(dataclasses.replace(fact, status=SUPERSEDED, superseded_at=now), new=False)


def _as_fact(item: Union[Fact, GrillResult]) -> Fact:
    if isinstance(item, GrillResult):
        if not item.accepted or item.fact is None:
            raise ValueError(f"only accepted results can be stocked (status: {item.status})")
        return item.fact
    if isinstance(item, Fact):
        return item
    raise TypeError(f"stocks hold Facts, not {type(item).__name__}")


@dataclass
class ChickenStock(StockLogic):
    """In-memory, indexed store for accepted knowledge (`StockBackend`)."""

    schema: Optional[Schema] = None
    policy: Policy = keep_both
    combine: ConfidenceCombiner = noisy_or
    clock: Callable[[], datetime] = _utc_now
    _facts: Dict[str, Fact] = field(default_factory=dict, repr=False)
    _by_subject: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _by_predicate: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _by_object: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _conflicts: Dict[str, Conflict] = field(default_factory=dict, repr=False)
    _entities: Dict[str, Entity] = field(default_factory=dict, repr=False)

    def __len__(self) -> int:
        return len(self._facts)

    def put_entity(self, entity: Entity) -> None:
        self._entities[entity.id] = entity

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def entities(self) -> List[Entity]:
        return list(self._entities.values())

    def _load(self, fact_id: str) -> Optional[Fact]:
        return self._facts.get(fact_id)

    def _save(self, fact: Fact, new: bool) -> None:
        self._facts[fact.fact_id] = fact
        if new:
            self._by_subject.setdefault(fact.subject.id, set()).add(fact.fact_id)
            self._by_predicate.setdefault(fact.predicate, set()).add(fact.fact_id)
            self._by_object.setdefault(value_key(fact.object), set()).add(fact.fact_id)

    def _match(
        self, subject_id: Optional[str], predicate: Optional[str], object_key: Optional[str]
    ) -> List[Fact]:
        ids: Optional[Set[str]] = None
        for index, key in (
            (self._by_subject, subject_id),
            (self._by_predicate, predicate),
            (self._by_object, object_key),
        ):
            if key is not None:
                matches = index.get(key, set())
                ids = set(matches) if ids is None else ids & matches
        if ids is None:
            return list(self._facts.values())
        return [f for i, f in self._facts.items() if i in ids]

    def _load_conflicts(self) -> List[Conflict]:
        return list(self._conflicts.values())

    def _save_conflict(self, conflict: Conflict, new: bool) -> None:
        self._conflicts[conflict.conflict_id] = conflict
