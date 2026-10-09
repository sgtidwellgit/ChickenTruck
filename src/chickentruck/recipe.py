"""chicken_recipe -- a lightweight schema for knowledge.

A recipe says what a dish is allowed to contain; a `Schema` says which
entity types exist, how they inherit from each other, and what each
predicate accepts. Schemas are optional: without one, `grill` runs only
structural checks and `ChickenStock` cannot detect conflicts (it needs
to know which predicates are single-valued).

A schema can be built in Python or loaded from a plain dict / JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple

ONE = "one"
MANY = "many"
CARDINALITIES = (ONE, MANY)

SPAN = "span"
MOMENT = "moment"
TEMPORAL_KINDS = (SPAN, MOMENT)

#: Range names that mean "a plain value" rather than an entity type.
LITERAL_TYPES = ("string", "integer", "number", "boolean", "time")


@dataclass(frozen=True)
class EntityType:
    """A kind of entity, optionally a subtype of ``parent``."""

    name: str
    parent: Optional[str] = None
    description: str = ""


@dataclass(frozen=True)
class Predicate:
    """What a predicate accepts.

    - ``domain``: entity types the subject may have (empty means any).
    - ``range``: an entity type name, one of `LITERAL_TYPES`, or ``None``
      for anything.
    - ``cardinality``: ``"one"`` if a subject can hold only one object at
      a time (e.g. BORN_IN), ``"many"`` otherwise.
    - ``temporal``: ``"span"`` facts hold over an interval; ``"moment"``
      facts happen at a point and may only set ``valid_from``.
    """

    name: str
    domain: Tuple[str, ...] = ()
    range: Optional[str] = None
    cardinality: str = MANY
    temporal: str = SPAN
    description: str = ""

    def __post_init__(self) -> None:
        if isinstance(self.domain, str):
            object.__setattr__(self, "domain", (self.domain,))
        else:
            object.__setattr__(self, "domain", tuple(self.domain))
        if self.cardinality not in CARDINALITIES:
            raise ValueError(f"unknown cardinality {self.cardinality!r}")
        if self.temporal not in TEMPORAL_KINDS:
            raise ValueError(f"unknown temporal kind {self.temporal!r}")

    @property
    def range_is_literal(self) -> bool:
        return self.range in LITERAL_TYPES

    @property
    def range_is_entity(self) -> bool:
        return self.range is not None and self.range not in LITERAL_TYPES


@dataclass
class Schema:
    """Entity types and predicate definitions.

    With ``strict=True``, `grill` rejects predicates the schema does not
    define; otherwise unknown predicates pass with an informational note.
    """

    entity_types: Dict[str, EntityType] = field(default_factory=dict)
    predicates: Dict[str, Predicate] = field(default_factory=dict)
    strict: bool = False

    def add_type(self, entity_type: EntityType) -> EntityType:
        if entity_type.name in self.entity_types:
            raise ValueError(f"entity type {entity_type.name!r} already defined")
        if entity_type.name in LITERAL_TYPES:
            raise ValueError(f"{entity_type.name!r} is reserved for literal values")
        if entity_type.parent is not None:
            if entity_type.parent not in self.entity_types:
                raise ValueError(
                    f"parent type {entity_type.parent!r} of {entity_type.name!r} "
                    "is not defined (define parents first)"
                )
        self.entity_types[entity_type.name] = entity_type
        return entity_type

    def add_predicate(self, predicate: Predicate) -> Predicate:
        if predicate.name in self.predicates:
            raise ValueError(f"predicate {predicate.name!r} already defined")
        for type_name in predicate.domain:
            self._require_type(type_name, predicate.name)
        if predicate.range_is_entity:
            self._require_type(predicate.range, predicate.name)
        self.predicates[predicate.name] = predicate
        return predicate

    def predicate(self, name: str) -> Optional[Predicate]:
        return self.predicates.get(name)

    def ancestors(self, type_name: str) -> Tuple[str, ...]:
        """``type_name`` followed by each parent up to the root."""

        chain = []
        current: Optional[str] = type_name
        while current is not None:
            chain.append(current)
            entity_type = self.entity_types.get(current)
            current = entity_type.parent if entity_type else None
        return tuple(chain)

    def is_a(self, type_name: str, ancestor: str) -> bool:
        """True when ``type_name`` is ``ancestor`` or one of its subtypes."""

        return ancestor in self.ancestors(type_name)

    def is_any(self, type_name: str, candidates: Iterable[str]) -> bool:
        return any(self.is_a(type_name, c) for c in candidates)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strict": self.strict,
            "entity_types": [
                {"name": t.name, "parent": t.parent, "description": t.description}
                for t in self.entity_types.values()
            ],
            "predicates": [
                {
                    "name": p.name,
                    "domain": list(p.domain),
                    "range": p.range,
                    "cardinality": p.cardinality,
                    "temporal": p.temporal,
                    "description": p.description,
                }
                for p in self.predicates.values()
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Schema":
        schema = cls(strict=bool(data.get("strict", False)))
        for item in data.get("entity_types", []):
            schema.add_type(EntityType(**item))
        for item in data.get("predicates", []):
            schema.add_predicate(Predicate(**item))
        return schema

    def to_json(self, **kwargs: Any) -> str:
        return json.dumps(self.to_dict(), **kwargs)

    @classmethod
    def from_json(cls, text: str) -> "Schema":
        return cls.from_dict(json.loads(text))

    def _require_type(self, type_name: str, predicate_name: str) -> None:
        if type_name not in self.entity_types:
            raise ValueError(
                f"predicate {predicate_name!r} references undefined entity type "
                f"{type_name!r}"
            )
