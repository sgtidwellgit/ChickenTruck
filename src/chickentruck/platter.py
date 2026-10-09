"""chicken_platter -- serving knowledge in the shapes consumers need.

The same stocked knowledge, plated three ways:

- `to_graph`: a property graph (nodes, edges, and literal statements)
  for graph databases and visualizers.
- `to_tables`: normalized relational tables as lists of dicts, ready for
  a database, a CSV writer, or a DataFrame constructor.
- `to_ntriples`: RDF N-Triples text for semantic-web tooling.

Everything here is plain Python data with no dependencies. Entities
come from the ``coop`` when one is given, otherwise from the stock's own
entity store.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional
from urllib.parse import quote

from ._temporal import DAY, INSTANT, MONTH, YEAR, TimePoint
from .coop import ChickenCoop, Entity, Ref
from .grilled import Fact
from .stock import StockBackend

SIMPLE = "simple"
FULL = "full"


def json_value(value: Any) -> Any:
    """A fact value as plain JSON data: refs become IDs, times become ISO text."""

    if isinstance(value, Ref):
        return value.id
    if isinstance(value, TimePoint):
        return value.isoformat()
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    return value


def value_type(value: Any) -> str:
    """The kind of a fact value, using the schema's range vocabulary."""

    if isinstance(value, Ref):
        return "entity"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, (TimePoint, date, datetime)):
        return "time"
    return "json"


def _cell(value: Any) -> Any:
    """A JSON value flattened to one table cell: containers become JSON text."""

    plain = json_value(value)
    if isinstance(plain, (list, dict)):
        return json.dumps(plain, sort_keys=True)
    return plain


def _entities(stock: StockBackend, coop: Optional[ChickenCoop]) -> List[Entity]:
    return coop.entities() if coop is not None else stock.entities()


def _facts(stock: StockBackend, include_superseded: bool) -> List[Fact]:
    return [f for f in stock.all() if include_superseded or f.active]


def _time_fields(fact: Fact) -> Dict[str, Any]:
    return {
        "valid_from": fact.valid_from.isoformat() if fact.valid_from else None,
        "valid_to": fact.valid_to.isoformat() if fact.valid_to else None,
    }


@dataclass
class Graph:
    """A property graph: entity nodes, fact edges, and literal statements."""

    nodes: List[Dict[str, Any]] = field(default_factory=list)
    edges: List[Dict[str, Any]] = field(default_factory=list)
    statements: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"nodes": self.nodes, "edges": self.edges, "statements": self.statements}


def to_graph(
    stock: StockBackend,
    *,
    coop: Optional[ChickenCoop] = None,
    mode: str = SIMPLE,
    include_superseded: bool = False,
) -> Graph:
    """Export knowledge as a property graph.

    Facts between two entities become edges carrying their ID,
    confidence, validity, and source IDs. Facts with a literal object
    depend on ``mode``:

    - ``"simple"``: folded into the subject node's ``properties``
      (several values become a list). Compact, but drops their
      validity and provenance.
    - ``"full"``: kept as separate ``statements`` with all metadata.
    """

    if mode not in (SIMPLE, FULL):
        raise ValueError(f"mode must be 'simple' or 'full', not {mode!r}")

    nodes: Dict[str, Dict[str, Any]] = {}
    for entity in _entities(stock, coop):
        nodes[entity.id] = {
            "id": entity.id,
            "label": entity.label,
            "type": entity.type,
            "aliases": sorted(entity.aliases),
            "provisional": entity.provisional,
            "properties": {},
        }

    def node(entity_id: str) -> Dict[str, Any]:
        if entity_id not in nodes:
            nodes[entity_id] = {
                "id": entity_id,
                "label": entity_id,
                "type": None,
                "aliases": [],
                "provisional": False,
                "properties": {},
            }
        return nodes[entity_id]

    graph = Graph()
    properties: Dict[str, Dict[str, List[Any]]] = {}
    for fact in _facts(stock, include_superseded):
        node(fact.subject.id)
        record = {
            "id": fact.fact_id,
            "predicate": fact.predicate,
            "confidence": fact.confidence,
            **_time_fields(fact),
            "qualifiers": json_value(fact.qualifiers),
            "sources": [s.id for s in fact.sources],
            "status": fact.status,
        }
        if isinstance(fact.object, Ref):
            node(fact.object.id)
            graph.edges.append({"source": fact.subject.id, "target": fact.object.id, **record})
        elif mode == FULL:
            graph.statements.append(
                {
                    "subject": fact.subject.id,
                    "value": json_value(fact.object),
                    "value_type": value_type(fact.object),
                    **record,
                }
            )
        else:
            values = properties.setdefault(fact.subject.id, {}).setdefault(fact.predicate, [])
            values.append(json_value(fact.object))

    for entity_id, props in properties.items():
        for predicate, values in props.items():
            nodes[entity_id]["properties"][predicate] = values[0] if len(values) == 1 else values
    graph.nodes = list(nodes.values())
    return graph


def to_tables(
    stock: StockBackend,
    *,
    coop: Optional[ChickenCoop] = None,
    include_superseded: bool = True,
) -> Dict[str, List[Dict[str, Any]]]:
    """Export knowledge as normalized relational tables.

    Returns ``entities``, ``aliases``, ``sources``, ``facts``,
    ``evidence``, ``qualifiers``, and ``conflicts``, each a list of flat
    dicts (one per row). A fact's object goes in ``object_entity_id``
    when it is an entity, otherwise in ``object_value`` with its kind in
    ``object_type``. Superseded facts are included by default so the
    history is complete.
    """

    entities = _entities(stock, coop)
    facts = _facts(stock, include_superseded)
    tables: Dict[str, List[Dict[str, Any]]] = {
        "entities": [
            {"id": e.id, "label": e.label, "type": e.type, "provisional": e.provisional}
            for e in entities
        ],
        "aliases": [
            {"entity_id": e.id, "alias": alias} for e in entities for alias in sorted(e.aliases)
        ],
        "sources": [
            {
                "id": s.id,
                "kind": s.kind,
                "uri": s.uri,
                "title": s.title,
                "retrieved_at": s.retrieved_at.isoformat() if s.retrieved_at else None,
                "authority": s.authority,
            }
            for s in stock.sources()
        ],
        "facts": [],
        "evidence": [],
        "qualifiers": [],
        "conflicts": [
            {
                "conflict_id": c.conflict_id,
                "fact_a": c.fact_ids[0],
                "fact_b": c.fact_ids[1],
                "subject_id": c.subject.id,
                "predicate": c.predicate,
                "detected_at": c.detected_at.isoformat(),
                "policy": c.policy,
                "winner": c.winner,
            }
            for c in stock.conflicts()
        ],
    }
    for fact in facts:
        is_entity = isinstance(fact.object, Ref)
        tables["facts"].append(
            {
                "fact_id": fact.fact_id,
                "subject_id": fact.subject.id,
                "predicate": fact.predicate,
                "object_entity_id": fact.object.id if is_entity else None,
                "object_value": None if is_entity else _cell(fact.object),
                "object_type": value_type(fact.object),
                **_time_fields(fact),
                "valid_from_precision": fact.valid_from.precision if fact.valid_from else None,
                "valid_to_precision": fact.valid_to.precision if fact.valid_to else None,
                "confidence": fact.confidence,
                "status": fact.status,
                "recorded_at": fact.recorded_at.isoformat() if fact.recorded_at else None,
                "superseded_at": fact.superseded_at.isoformat() if fact.superseded_at else None,
            }
        )
        for position, item in enumerate(fact.evidence):
            tables["evidence"].append(
                {
                    "fact_id": fact.fact_id,
                    "position": position,
                    "source_id": item.source.id,
                    "locator": item.locator,
                    "quote": item.quote,
                    "confidence": item.confidence,
                    "extractor": item.extractor,
                    "extracted_at": item.extracted_at.isoformat() if item.extracted_at else None,
                }
            )
        for key, value in sorted(fact.qualifiers.items()):
            tables["qualifiers"].append(
                {
                    "fact_id": fact.fact_id,
                    "key": key,
                    "value": _cell(value),
                    "value_type": value_type(value),
                }
            )
    return tables


_RDF_TYPE = "<http://www.w3.org/1999/02/22-rdf-syntax-ns#type>"
_RDFS_LABEL = "<http://www.w3.org/2000/01/rdf-schema#label>"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_TIME_TYPES = {YEAR: "gYear", MONTH: "gYearMonth", DAY: "date", INSTANT: "dateTime"}


def _iri(base: str, kind: str, name: str) -> str:
    return f"<{base}{kind}/{quote(name, safe='')}>"


def _literal(value: Any) -> str:
    def text(raw: str, datatype: Optional[str] = None) -> str:
        escaped = (
            raw.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n").replace("\r", "\\r")
        )
        return f'"{escaped}"' + (f"^^<{_XSD}{datatype}>" if datatype else "")

    if isinstance(value, bool):
        return text("true" if value else "false", "boolean")
    if isinstance(value, int):
        return text(str(value), "integer")
    if isinstance(value, float):
        return text(repr(value), "double")
    if isinstance(value, TimePoint):
        return text(value.isoformat(), _TIME_TYPES[value.precision])
    if isinstance(value, datetime):
        return text(value.isoformat(), "dateTime")
    if isinstance(value, date):
        return text(value.isoformat(), "date")
    if isinstance(value, str):
        return text(value)
    return text(json.dumps(json_value(value), sort_keys=True))


def to_ntriples(
    stock: StockBackend,
    *,
    coop: Optional[ChickenCoop] = None,
    base: str = "urn:chickentruck:",
) -> str:
    """Export active knowledge as RDF N-Triples.

    Entities get ``rdfs:label`` and ``rdf:type`` triples; each active
    fact becomes one triple. Plain triples cannot carry confidence,
    validity, or provenance -- use `to_graph` or `to_tables` when those
    matter.
    """

    lines: List[str] = []
    for entity in _entities(stock, coop):
        subject = _iri(base, "entity", entity.id)
        lines.append(f"{subject} {_RDFS_LABEL} {_literal(entity.label)} .")
        if entity.type:
            lines.append(f"{subject} {_RDF_TYPE} {_iri(base, 'type', entity.type)} .")
    for fact in _facts(stock, include_superseded=False):
        subject = _iri(base, "entity", fact.subject.id)
        predicate = _iri(base, "predicate", fact.predicate)
        if isinstance(fact.object, Ref):
            obj = _iri(base, "entity", fact.object.id)
        else:
            obj = _literal(fact.object)
        lines.append(f"{subject} {predicate} {obj} .")
    return "".join(line + "\n" for line in lines)

