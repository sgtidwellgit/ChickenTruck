"""chicken_coop -- entities and entity resolution.

The coop is where entities live. Extracted text only ever names things
("Ben Franklin", "Benjamin Franklin"); resolution decides which entity
in the coop a mention refers to, and turns the mention into a `Ref`.

Resolution here is deliberately conservative: an exact label/alias
match first, then a normalized match (case, whitespace, and punctuation
ignored). Ambiguous mentions are left unresolved rather than guessed.
Other strategies (fuzzy, embedding) plug in through the `Resolver`
protocol.
"""

from __future__ import annotations

import dataclasses
import re
import unicodedata
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Dict, FrozenSet, List, Optional, Protocol, Set, Tuple

if TYPE_CHECKING:
    from .recipe import Schema
    from .tenders import ChickenTender

EXACT_SCORE = 1.0
NORMALIZED_SCORE = 0.9

_WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    """Case-fold, drop punctuation, and collapse whitespace."""

    folded = unicodedata.normalize("NFKC", text).casefold()
    stripped = "".join(
        " " if unicodedata.category(ch).startswith("P") else ch for ch in folded
    )
    return _WHITESPACE.sub(" ", stripped).strip()


def make_entity_id(label: str, type: Optional[str] = None) -> str:
    """A readable ID such as ``"person:benjamin-franklin"``."""

    slug = normalize(label).replace(" ", "-") or "entity"
    return f"{normalize(type).replace(' ', '-')}:{slug}" if type else slug


@dataclass(frozen=True)
class Ref:
    """A reference to a resolved entity by its stable ID."""

    id: str

    def __str__(self) -> str:
        return self.id


@dataclass(frozen=True)
class Mention:
    """Text that names an entity but has not been resolved yet."""

    text: str
    type: Optional[str] = None

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True)
class Entity:
    """A real-world thing knowledge can be about.

    ``provisional`` marks entities the coop created on its own for an
    unmatched mention, so they can be reviewed and confirmed later.
    """

    id: str
    label: str
    type: Optional[str] = None
    aliases: FrozenSet[str] = frozenset()
    provisional: bool = False

    def __post_init__(self) -> None:
        if not self.id:
            raise ValueError("entity id must not be empty")
        object.__setattr__(self, "aliases", frozenset(self.aliases))

    @property
    def ref(self) -> Ref:
        return Ref(self.id)

    @property
    def names(self) -> Tuple[str, ...]:
        return (self.label, *sorted(self.aliases))


@dataclass(frozen=True)
class Resolution:
    """The outcome of resolving one mention.

    ``entity_id`` is ``None`` when the mention matched nothing (and
    nothing was created) or matched several entities equally well; the
    candidates are listed either way.
    """

    mention: str
    entity_id: Optional[str]
    candidates: Tuple[str, ...] = ()
    score: float = 0.0
    created: bool = False

    @property
    def resolved(self) -> bool:
        return self.entity_id is not None

    @property
    def ambiguous(self) -> bool:
        return self.entity_id is None and len(self.candidates) > 1


class Resolver(Protocol):
    """Anything that can map a mention to an entity ID."""

    def resolve(self, mention: str, type: Optional[str] = None) -> Resolution:
        ...


@dataclass
class ChickenCoop:
    """An in-memory entity registry with exact and normalized-alias resolution.

    Pass a `Schema` so type hints honor subtypes: with ``Scientist`` a
    subtype of ``Person``, a ``Person`` hint also matches scientists.
    """

    schema: Optional["Schema"] = None
    _entities: Dict[str, Entity] = field(default_factory=dict, repr=False)
    _exact: Dict[str, Set[str]] = field(default_factory=dict, repr=False)
    _normalized: Dict[str, Set[str]] = field(default_factory=dict, repr=False)

    def add(self, entity: Entity) -> Entity:
        """Register an entity. Its ID must be new to the coop."""

        if entity.id in self._entities:
            raise ValueError(f"entity {entity.id!r} already exists")
        self._entities[entity.id] = entity
        self._index(entity)
        return entity

    def get(self, entity_id: str) -> Optional[Entity]:
        return self._entities.get(entity_id)

    def entities(self) -> List[Entity]:
        return list(self._entities.values())

    def __len__(self) -> int:
        return len(self._entities)

    def __contains__(self, entity_id: object) -> bool:
        return entity_id in self._entities

    def add_alias(self, entity_id: str, alias: str) -> Entity:
        entity = self._require(entity_id)
        updated = dataclasses.replace(entity, aliases=entity.aliases | {alias})
        self._entities[entity_id] = updated
        self._index(updated)
        return updated

    def confirm(self, entity_id: str) -> Entity:
        """Clear the provisional flag on an entity after review."""

        entity = self._require(entity_id)
        updated = dataclasses.replace(entity, provisional=False)
        self._entities[entity_id] = updated
        return updated

    def provisional(self) -> List[Entity]:
        return [e for e in self._entities.values() if e.provisional]

    def candidates(self, mention: str, type: Optional[str] = None) -> Tuple[Tuple[str, ...], float]:
        """IDs matching ``mention`` at the best available score."""

        for index, key, score in (
            (self._exact, mention.strip(), EXACT_SCORE),
            (self._normalized, normalize(mention), NORMALIZED_SCORE),
        ):
            ids = [i for i in sorted(index.get(key, ())) if self._type_fits(i, type)]
            if ids:
                return tuple(ids), score
        return (), 0.0

    def resolve(
        self, mention: str, type: Optional[str] = None, create: bool = True
    ) -> Resolution:
        """Resolve a mention to one entity.

        One match resolves. Several matches are ambiguous and stay
        unresolved. No match creates a provisional entity when ``create``
        is true.
        """

        ids, score = self.candidates(mention, type)
        if len(ids) == 1:
            return Resolution(mention, ids[0], ids, score)
        if ids:
            return Resolution(mention, None, ids, score)
        if not create or not mention.strip():
            return Resolution(mention, None)
        entity = self.add(
            Entity(
                id=self._unique_id(make_entity_id(mention, type)),
                label=mention.strip(),
                type=type,
                provisional=True,
            )
        )
        return Resolution(mention, entity.id, (entity.id,), EXACT_SCORE, created=True)

    def resolve_tender(
        self,
        tender: "ChickenTender",
        resolver: Optional[Resolver] = None,
        create: bool = True,
    ) -> "ChickenTender":
        """Return a copy of ``tender`` with its entity mentions resolved to `Ref`s.

        The subject is always an entity. The object is treated as an
        entity when it is a `Mention`, or when it is a string and the
        schema says the predicate's range is an entity type; otherwise it
        is a literal and left alone. Unresolvable mentions stay as
        `Mention`s, which `grill` sends to review.
        """

        predicate = self.schema.predicate(tender.predicate) if self.schema else None

        subject_hint = None
        if predicate is not None and len(predicate.domain) == 1:
            subject_hint = predicate.domain[0]
        subject = self._resolve_value(tender.subject, subject_hint, resolver, create)

        object_is_entity = isinstance(tender.object, Mention) or (
            isinstance(tender.object, str)
            and predicate is not None
            and predicate.range_is_entity
        )
        obj = tender.object
        if object_is_entity:
            object_hint = predicate.range if predicate and predicate.range_is_entity else None
            obj = self._resolve_value(tender.object, object_hint, resolver, create)

        return dataclasses.replace(tender, subject=subject, object=obj)

    def _resolve_value(self, value, hint, resolver, create):
        if isinstance(value, Ref):
            return value
        if isinstance(value, Mention):
            text, hint = value.text, value.type or hint
        else:
            text = str(value)
        if resolver is not None:
            result = resolver.resolve(text, hint)
        else:
            result = self.resolve(text, hint, create=create)
        if result.entity_id is None:
            return value if isinstance(value, Mention) else Mention(text, hint)
        return Ref(result.entity_id)

    def _type_fits(self, entity_id: str, type: Optional[str]) -> bool:
        if type is None:
            return True
        entity_type = self._entities[entity_id].type
        if entity_type is None or entity_type == type:
            return True
        if self.schema is not None:
            return self.schema.is_a(entity_type, type)
        return False

    def _index(self, entity: Entity) -> None:
        for name in entity.names:
            self._exact.setdefault(name.strip(), set()).add(entity.id)
            self._normalized.setdefault(normalize(name), set()).add(entity.id)

    def _require(self, entity_id: str) -> Entity:
        entity = self._entities.get(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        return entity

    def _unique_id(self, base: str) -> str:
        candidate, n = base, 2
        while candidate in self._entities:
            candidate, n = f"{base}-{n}", n + 1
        return candidate

