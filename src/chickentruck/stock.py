"""chicken_stock -- foundational store for validated knowledge.

Chicken stock is the base other dishes build on; likewise `ChickenStock`
is meant to become the backend-independent store for accepted, validated
knowledge, with adapters (in-memory, PostgreSQL, Neo4j, RDF, ...) layered
on top once that interface is designed (see PROJECT.md). For now it is a
plain in-memory list -- the only backend implemented so far.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ChickenStock:
    """A minimal in-memory store for validated knowledge items."""

    _items: list[Any] = field(default_factory=list)

    def add(self, item: Any) -> None:
        """Add a validated knowledge item to the store."""

        self._items.append(item)

    def all(self) -> list[Any]:
        """Return every item currently in the store, in insertion order."""

        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)
