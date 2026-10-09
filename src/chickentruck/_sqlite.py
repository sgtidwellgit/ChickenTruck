"""SQLite backend for chicken_stock -- persistent knowledge, stdlib only.

`SqliteStock` follows exactly the same rules as the in-memory
`ChickenStock` (both build on `StockLogic`); it just keeps facts,
evidence, sources, conflicts, and entities in a SQLite database file.

Values are stored as tagged JSON, so entity references, time points,
dates, and datetimes come back as the same Python types. Literal values
must be JSON-compatible (str, int, float, bool, None, lists, and dicts
with string keys); tuples come back as lists.

A schema passed in is saved in the database; opening the file again
without one reuses the saved schema.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional, Sequence, Tuple, Union

from ._temporal import TimePoint, parse_time
from .coop import Entity, Ref
from .grilled import Fact, value_key
from .recipe import Schema
from .stock import Conflict, Policy, StockLogic, _utc_now, keep_both
from .tenders import ConfidenceCombiner, Evidence, Source, noisy_or

FORMAT_VERSION = "1"

_DDL = """
CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS facts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    fact_id TEXT NOT NULL UNIQUE,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_key TEXT NOT NULL,
    object_json TEXT NOT NULL,
    valid_from TEXT,
    valid_to TEXT,
    qualifiers_json TEXT NOT NULL,
    confidence REAL,
    status TEXT NOT NULL,
    recorded_at TEXT,
    superseded_at TEXT
);
CREATE INDEX IF NOT EXISTS facts_subject ON facts (subject_id);
CREATE INDEX IF NOT EXISTS facts_predicate ON facts (predicate);
CREATE INDEX IF NOT EXISTS facts_object ON facts (object_key);
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    uri TEXT,
    title TEXT,
    retrieved_at TEXT,
    authority REAL
);
CREATE TABLE IF NOT EXISTS evidence (
    fact_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    source_id TEXT NOT NULL,
    locator TEXT,
    quote TEXT,
    confidence REAL,
    extractor TEXT,
    extracted_at TEXT,
    PRIMARY KEY (fact_id, position)
);
CREATE TABLE IF NOT EXISTS conflicts (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    conflict_id TEXT NOT NULL UNIQUE,
    fact_a TEXT NOT NULL,
    fact_b TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    detected_at TEXT NOT NULL,
    policy TEXT NOT NULL,
    winner TEXT
);
CREATE TABLE IF NOT EXISTS entities (
    seq INTEGER PRIMARY KEY AUTOINCREMENT,
    id TEXT NOT NULL UNIQUE,
    label TEXT NOT NULL,
    type TEXT,
    aliases_json TEXT NOT NULL,
    provisional INTEGER NOT NULL
);
"""

_FACT_COLUMNS = (
    "fact_id, subject_id, predicate, object_json, valid_from, valid_to, "
    "qualifiers_json, confidence, status, recorded_at, superseded_at"
)


def encode_value(value: Any) -> Any:
    """Turn a fact value into tagged, JSON-compatible data."""

    if isinstance(value, Ref):
        return {"$ref": value.id}
    if isinstance(value, TimePoint):
        return {"$time": value.isoformat()}
    if isinstance(value, datetime):
        return {"$datetime": value.isoformat()}
    if isinstance(value, date):
        return {"$date": value.isoformat()}
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    if isinstance(value, (list, tuple)):
        return [encode_value(v) for v in value]
    if isinstance(value, dict) and all(isinstance(k, str) for k in value):
        return {"$dict": {k: encode_value(v) for k, v in value.items()}}
    raise TypeError(f"SqliteStock cannot store a {type(value).__name__} value: {value!r}")


def decode_value(data: Any) -> Any:
    """Inverse of `encode_value`."""

    if isinstance(data, list):
        return [decode_value(v) for v in data]
    if isinstance(data, dict):
        if "$ref" in data:
            return Ref(data["$ref"])
        if "$time" in data:
            return parse_time(data["$time"])
        if "$datetime" in data:
            return datetime.fromisoformat(data["$datetime"])
        if "$date" in data:
            return date.fromisoformat(data["$date"])
        return {k: decode_value(v) for k, v in data["$dict"].items()}
    return data


def _dumps(value: Any) -> str:
    return json.dumps(encode_value(value), sort_keys=True)


def _loads(text: str) -> Any:
    return decode_value(json.loads(text))


def _time_text(point: Optional[TimePoint]) -> Optional[str]:
    return None if point is None else point.isoformat()


def _dt_text(value: Optional[datetime]) -> Optional[str]:
    return None if value is None else value.isoformat()


def _dt(text: Optional[str]) -> Optional[datetime]:
    return None if text is None else datetime.fromisoformat(text)


class SqliteStock(StockLogic):
    """A `StockBackend` persisted in a SQLite database.

    ``path`` is a file path, or ``":memory:"`` (the default) for a
    throwaway database. Use it as a context manager, or call `close`.
    """

    def __init__(
        self,
        path: Union[str, Path] = ":memory:",
        *,
        schema: Optional[Schema] = None,
        policy: Policy = keep_both,
        combine: ConfidenceCombiner = noisy_or,
        clock: Callable[[], datetime] = _utc_now,
    ) -> None:
        self.path = str(path)
        self.policy = policy
        self.combine = combine
        self.clock = clock
        self._depth = 0
        self._conn = sqlite3.connect(self.path)
        self._conn.executescript(_DDL)
        with self._transaction():
            stored_format = self._meta("format")
            if stored_format is None:
                self._set_meta("format", FORMAT_VERSION)
            elif stored_format != FORMAT_VERSION:
                raise ValueError(
                    f"{self.path} uses storage format {stored_format}, "
                    f"this version reads format {FORMAT_VERSION}"
                )
            if schema is not None:
                self._set_meta("schema", schema.to_json())
                self.schema: Optional[Schema] = schema
            else:
                saved = self._meta("schema")
                self.schema = Schema.from_json(saved) if saved else None

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "SqliteStock":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __len__(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM facts").fetchone()[0]

    # -- entities -----------------------------------------------------------

    def put_entity(self, entity: Entity) -> None:
        with self._transaction():
            self._conn.execute(
                "INSERT INTO entities (id, label, type, aliases_json, provisional) "
                "VALUES (?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
                "label = excluded.label, type = excluded.type, "
                "aliases_json = excluded.aliases_json, provisional = excluded.provisional",
                (
                    entity.id,
                    entity.label,
                    entity.type,
                    json.dumps(sorted(entity.aliases)),
                    int(entity.provisional),
                ),
            )

    def get_entity(self, entity_id: str) -> Optional[Entity]:
        row = self._conn.execute(
            "SELECT id, label, type, aliases_json, provisional FROM entities WHERE id = ?",
            (entity_id,),
        ).fetchone()
        return None if row is None else self._entity(row)

    def entities(self) -> List[Entity]:
        rows = self._conn.execute(
            "SELECT id, label, type, aliases_json, provisional FROM entities ORDER BY seq"
        )
        return [self._entity(row) for row in rows]

    @staticmethod
    def _entity(row: Sequence[Any]) -> Entity:
        return Entity(row[0], row[1], row[2], frozenset(json.loads(row[3])), bool(row[4]))

    # -- storage primitives -------------------------------------------------

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._depth += 1
        try:
            yield
        except BaseException:
            self._depth -= 1
            if self._depth == 0:
                self._conn.rollback()
            raise
        self._depth -= 1
        if self._depth == 0:
            self._conn.commit()

    def _load(self, fact_id: str) -> Optional[Fact]:
        facts = self._select("fact_id = ?", (fact_id,))
        return facts[0] if facts else None

    def _match(
        self, subject_id: Optional[str], predicate: Optional[str], object_key: Optional[str]
    ) -> List[Fact]:
        clauses, params = [], []
        for column, value in (
            ("subject_id", subject_id),
            ("predicate", predicate),
            ("object_key", object_key),
        ):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        return self._select(" AND ".join(clauses) or "1 = 1", tuple(params))

    def _save(self, fact: Fact, new: bool) -> None:
        row = (
            fact.subject.id,
            fact.predicate,
            value_key(fact.object),
            _dumps(fact.object),
            _time_text(fact.valid_from),
            _time_text(fact.valid_to),
            _dumps(fact.qualifiers),
            fact.confidence,
            fact.status,
            _dt_text(fact.recorded_at),
            _dt_text(fact.superseded_at),
        )
        if new:
            self._conn.execute(
                "INSERT INTO facts (subject_id, predicate, object_key, object_json, "
                "valid_from, valid_to, qualifiers_json, confidence, status, recorded_at, "
                "superseded_at, fact_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                row + (fact.fact_id,),
            )
        else:
            self._conn.execute(
                "UPDATE facts SET subject_id = ?, predicate = ?, object_key = ?, "
                "object_json = ?, valid_from = ?, valid_to = ?, qualifiers_json = ?, "
                "confidence = ?, status = ?, recorded_at = ?, superseded_at = ? "
                "WHERE fact_id = ?",
                row + (fact.fact_id,),
            )
            self._conn.execute("DELETE FROM evidence WHERE fact_id = ?", (fact.fact_id,))
        for position, item in enumerate(fact.evidence):
            self._save_source(item.source)
            self._conn.execute(
                "INSERT INTO evidence (fact_id, position, source_id, locator, quote, "
                "confidence, extractor, extracted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    fact.fact_id,
                    position,
                    item.source.id,
                    item.locator,
                    item.quote,
                    item.confidence,
                    item.extractor,
                    _dt_text(item.extracted_at),
                ),
            )

    def _save_source(self, source: Source) -> None:
        self._conn.execute(
            "INSERT INTO sources (id, kind, uri, title, retrieved_at, authority) "
            "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "kind = excluded.kind, uri = excluded.uri, title = excluded.title, "
            "retrieved_at = excluded.retrieved_at, authority = excluded.authority",
            (
                source.id,
                source.kind,
                source.uri,
                source.title,
                _dt_text(source.retrieved_at),
                source.authority,
            ),
        )

    def _load_conflicts(self) -> List[Conflict]:
        rows = self._conn.execute(
            "SELECT conflict_id, fact_a, fact_b, subject_id, predicate, detected_at, "
            "policy, winner FROM conflicts ORDER BY seq"
        )
        return [
            Conflict(row[0], (row[1], row[2]), Ref(row[3]), row[4], _dt(row[5]), row[6], row[7])
            for row in rows
        ]

    def _save_conflict(self, conflict: Conflict, new: bool) -> None:
        if new:
            self._conn.execute(
                "INSERT INTO conflicts (conflict_id, fact_a, fact_b, subject_id, predicate, "
                "detected_at, policy, winner) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    conflict.conflict_id,
                    conflict.fact_ids[0],
                    conflict.fact_ids[1],
                    conflict.subject.id,
                    conflict.predicate,
                    _dt_text(conflict.detected_at),
                    conflict.policy,
                    conflict.winner,
                ),
            )
        else:
            self._conn.execute(
                "UPDATE conflicts SET winner = ? WHERE conflict_id = ?",
                (conflict.winner, conflict.conflict_id),
            )

    # -- reading --------------------------------------------------------------

    def _select(self, where: str, params: Tuple[Any, ...]) -> List[Fact]:
        rows = self._conn.execute(
            f"SELECT {_FACT_COLUMNS} FROM facts WHERE {where} ORDER BY seq", params
        ).fetchall()
        if not rows:
            return []
        evidence = self._evidence_for(where, params)
        return [self._fact(row, evidence.get(row[0], ())) for row in rows]

    def _evidence_for(self, where: str, params: Tuple[Any, ...]) -> Dict[str, Tuple[Evidence, ...]]:
        rows = self._conn.execute(
            "SELECT e.fact_id, e.locator, e.quote, e.confidence, e.extractor, e.extracted_at, "
            "s.id, s.kind, s.uri, s.title, s.retrieved_at, s.authority "
            "FROM evidence e JOIN sources s ON s.id = e.source_id "
            f"WHERE e.fact_id IN (SELECT fact_id FROM facts WHERE {where}) "
            "ORDER BY e.fact_id, e.position",
            params,
        )
        grouped: Dict[str, List[Evidence]] = {}
        for row in rows:
            source = Source(row[6], row[7], row[8], row[9], _dt(row[10]), row[11])
            grouped.setdefault(row[0], []).append(
                Evidence(source, row[1], row[2], row[3], row[4], _dt(row[5]))
            )
        return {k: tuple(v) for k, v in grouped.items()}

    @staticmethod
    def _fact(row: Sequence[Any], evidence: Tuple[Evidence, ...]) -> Fact:
        return Fact(
            fact_id=row[0],
            subject=Ref(row[1]),
            predicate=row[2],
            object=_loads(row[3]),
            evidence=evidence,
            confidence=row[7],
            valid_from=parse_time(row[4]),
            valid_to=parse_time(row[5]),
            qualifiers=_loads(row[6]),
            status=row[8],
            recorded_at=_dt(row[9]),
            superseded_at=_dt(row[10]),
        )

    def _meta(self, key: str) -> Optional[str]:
        row = self._conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return None if row is None else row[0]

    def _set_meta(self, key: str, value: str) -> None:
        self._conn.execute(
            "INSERT INTO meta (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
