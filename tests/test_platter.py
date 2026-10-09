"""Tests for chickentruck.platter."""

import json

import pytest

from chickentruck import ChickenStock, to_graph, to_ntriples, to_tables
from chickentruck.platter import json_value, value_type
from chickentruck._temporal import parse_time
from chickentruck import Ref


def test_value_helpers():
    assert json_value(Ref("x")) == "x"
    assert json_value(parse_time("1706")) == "1706"
    assert json_value({"a": [Ref("y")]}) == {"a": ["y"]}
    assert [value_type(v) for v in (Ref("x"), True, 1, 1.5, "s", parse_time("1706"), [1])] == [
        "entity",
        "boolean",
        "integer",
        "number",
        "string",
        "time",
        "json",
    ]


def test_graph_simple_mode(kitchen):
    stock, _ = kitchen
    graph = to_graph(stock)

    nodes = {n["id"]: n for n in graph.nodes}
    assert set(nodes) == {"person:franklin", "place:boston", "place:philadelphia", "org:post-office"}
    assert nodes["person:franklin"]["label"] == "Benjamin Franklin"
    assert nodes["person:franklin"]["properties"] == {"BIRTH_YEAR": 1706}
    assert graph.statements == []

    born = [e for e in graph.edges if e["predicate"] == "BORN_IN"]
    assert {e["target"] for e in born} == {"place:boston", "place:philadelphia"}
    boston = next(e for e in born if e["target"] == "place:boston")
    assert boston["sources"] == ["encyclopedia", "letters"]
    assert boston["valid_from"] == "1706-01-17"

    worked = next(e for e in graph.edges if e["predicate"] == "WORKED_AT")
    assert worked["qualifiers"] == {"role": "Deputy Postmaster General"}
    assert worked["valid_to"] == "1774"
    json.dumps(graph.to_dict())  # fully JSON-serializable


def test_graph_full_mode_keeps_literal_metadata(kitchen):
    stock, _ = kitchen
    graph = to_graph(stock, mode="full")

    [statement] = graph.statements
    assert statement["subject"] == "person:franklin"
    assert statement["value"] == 1706
    assert statement["value_type"] == "integer"
    assert statement["sources"] == ["encyclopedia"]
    assert all(n["properties"] == {} for n in graph.nodes)


def test_graph_rejects_unknown_mode(kitchen):
    with pytest.raises(ValueError):
        to_graph(kitchen[0], mode="fancy")


def test_graph_adds_nodes_for_unknown_entities(clock):
    from chickentruck import ChickenTender, Evidence, Source, grill

    stock = ChickenStock()
    stock.add(grill(ChickenTender(Ref("a"), "KNOWS", Ref("b"), evidence=[Evidence(Source("s"))])))

    assert [n["id"] for n in to_graph(stock).nodes] == ["a", "b"]


def test_graph_hides_superseded_by_default(kitchen):
    stock, _ = kitchen
    [conflict] = stock.conflicts()
    stock.resolve_conflict(conflict.conflict_id, conflict.fact_ids[0])

    assert len(to_graph(stock).edges) == 2
    assert len(to_graph(stock, include_superseded=True).edges) == 3


def test_tables(kitchen):
    stock, _ = kitchen
    tables = to_tables(stock)

    assert set(tables) == {"entities", "aliases", "sources", "facts", "evidence", "qualifiers", "conflicts"}
    assert {"entity_id": "person:franklin", "alias": "Ben Franklin"} in tables["aliases"]
    assert [s["id"] for s in tables["sources"]] == ["encyclopedia", "letters", "blog"]
    assert len(tables["facts"]) == 4
    assert len(tables["evidence"]) == 5
    assert len(tables["conflicts"]) == 1

    year = next(f for f in tables["facts"] if f["predicate"] == "BIRTH_YEAR")
    assert year["object_entity_id"] is None
    assert year["object_value"] == 1706
    assert year["object_type"] == "integer"

    born = next(f for f in tables["facts"] if f["object_entity_id"] == "place:boston")
    assert born["object_value"] is None
    assert born["valid_from_precision"] == "day"
    assert born["recorded_at"]

    [qualifier] = tables["qualifiers"]
    assert qualifier["key"] == "role"
    assert qualifier["value_type"] == "string"

    for rows in tables.values():
        for row in rows:
            assert all(not isinstance(v, (list, dict)) for v in row.values())


def test_tables_can_use_a_separate_coop(kitchen, coop):
    stock, _ = kitchen

    tables = to_tables(stock, coop=coop)

    assert [e["id"] for e in tables["entities"]] == [e.id for e in coop.entities()]


def test_ntriples(kitchen):
    stock, _ = kitchen
    text = to_ntriples(stock)
    lines = text.splitlines()

    assert all(line.endswith(" .") for line in lines)
    franklin = "<urn:chickentruck:entity/person%3Afranklin>"
    assert (
        f'{franklin} <http://www.w3.org/2000/01/rdf-schema#label> "Benjamin Franklin" .' in lines
    )
    assert (
        f"{franklin} <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> "
        "<urn:chickentruck:type/Scientist> ." in lines
    )
    assert (
        f"{franklin} <urn:chickentruck:predicate/BIRTH_YEAR> "
        '"1706"^^<http://www.w3.org/2001/XMLSchema#integer> .' in lines
    )
    assert (
        f"{franklin} <urn:chickentruck:predicate/BORN_IN> "
        "<urn:chickentruck:entity/place%3Aboston> ." in lines
    )


def test_ntriples_escapes_literals():
    from chickentruck import ChickenTender, Evidence, Source, grill

    stock = ChickenStock()
    stock.add(grill(ChickenTender(Ref("a"), "SAID", 'He said "hi"\nthen left', evidence=[Evidence(Source("s"))])))

    assert '"He said \\"hi\\"\\nthen left" .' in to_ntriples(stock)
