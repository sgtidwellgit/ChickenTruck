"""Tests specific to the SQLite backend: persistence and value round-trips."""

import sqlite3
from datetime import date, datetime, timezone

import pytest

from chickentruck import (
    ChickenCoop,
    ChickenTender,
    Entity,
    Evidence,
    Ref,
    Source,
    SqliteStock,
    grill,
    highest_confidence,
)
from chickentruck._sqlite import decode_value, encode_value
from chickentruck._temporal import parse_time


def accepted(obj, predicate="P", subject="a", **kw):
    evidence = kw.pop(
        "evidence",
        [Evidence(Source("s", title="S", authority=0.9), locator="p. 3", quote="q", confidence=0.8)],
    )
    result = grill(ChickenTender(Ref(subject), predicate, obj, evidence=evidence, **kw))
    assert result.accepted, result.findings
    return result


@pytest.mark.parametrize(
    "value",
    [
        "text",
        42,
        2.5,
        True,
        Ref("place:boston"),
        parse_time("1706"),
        parse_time("2026-10-09T12:00:00+00:00"),
        date(1706, 1, 17),
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        ["a", 1, Ref("x")],
        {"nested": {"ref": Ref("y")}, "$ref": "not a tag"},
    ],
)
def test_values_round_trip(value):
    assert decode_value(encode_value(value)) == value


def test_unsupported_values_are_refused():
    with pytest.raises(TypeError):
        encode_value(object())
    with pytest.raises(TypeError):
        encode_value({1: "non-string key"})


def test_everything_survives_reopening(tmp_path, schema):
    path = tmp_path / "knowledge.db"
    with SqliteStock(path, schema=schema, policy=highest_confidence) as stock:
        coop = ChickenCoop(schema=schema, store=stock)
        coop.add(Entity("person:franklin", "Benjamin Franklin", "Person", aliases={"Ben"}))
        coop.resolve("Deborah Read", type="Person")
        stored = stock.add(
            accepted(
                Ref("place:boston"),
                predicate="BORN_IN",
                subject="person:franklin",
                valid_from="1706-01-17",
                qualifiers={"note": "Milk Street"},
            )
        )
        stock.add(accepted(Ref("place:philadelphia"), predicate="BORN_IN", subject="person:franklin", evidence=[Evidence(Source("blog"), confidence=0.6)], valid_from="1706-01-17"))
        before = stock.all()
        conflicts = stock.conflicts()

    with SqliteStock(path) as reopened:
        assert reopened.schema.to_dict() == schema.to_dict()
        assert reopened.all() == before
        assert reopened.get(stored.fact_id) == stored
        assert reopened.conflicts() == conflicts
        coop = ChickenCoop(schema=reopened.schema, store=reopened)
        assert coop.resolve("Ben").entity_id == "person:franklin"
        assert [e.id for e in coop.provisional()] == ["person:deborah-read"]


def test_failed_add_rolls_back(tmp_path):
    with SqliteStock(tmp_path / "k.db") as stock:
        stock.add(accepted(1))
        bad = accepted(object())  # grill accepts any literal; SQLite cannot store it
        with pytest.raises(TypeError):
            stock.add(bad)
        assert len(stock) == 1


def test_other_storage_formats_are_refused(tmp_path):
    path = tmp_path / "k.db"
    SqliteStock(path).close()
    conn = sqlite3.connect(str(path))
    conn.execute("UPDATE meta SET value = '999' WHERE key = 'format'")
    conn.commit()
    conn.close()

    with pytest.raises(ValueError):
        SqliteStock(path)


def test_sources_are_shared_by_id(tmp_path):
    with SqliteStock(tmp_path / "k.db") as stock:
        stock.add(accepted(1))
        stock.add(accepted(2))

        assert [s.id for s in stock.sources()] == ["s"]
