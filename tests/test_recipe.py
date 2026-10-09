"""Tests for chickentruck.recipe."""

import pytest

from chickentruck import EntityType, Predicate, Schema


def test_subtypes_follow_parent_chain(schema):
    assert schema.is_a("Scientist", "Person")
    assert schema.is_a("Person", "Person")
    assert not schema.is_a("Person", "Scientist")
    assert schema.ancestors("Scientist") == ("Scientist", "Person")


def test_predicate_range_kinds(schema):
    assert schema.predicate("BORN_IN").range_is_entity
    assert schema.predicate("BIRTH_YEAR").range_is_literal
    assert schema.predicate("NOPE") is None


def test_schema_rejects_undefined_references():
    schema = Schema()
    with pytest.raises(ValueError):
        schema.add_type(EntityType("Scientist", parent="Person"))
    with pytest.raises(ValueError):
        schema.add_predicate(Predicate("BORN_IN", domain="Person"))
    with pytest.raises(ValueError):
        schema.add_type(EntityType("string"))


def test_predicate_validates_its_options():
    with pytest.raises(ValueError):
        Predicate("X", cardinality="several")
    with pytest.raises(ValueError):
        Predicate("X", temporal="sometimes")


def test_schema_round_trips_through_json(schema):
    schema.strict = True
    restored = Schema.from_json(schema.to_json())

    assert restored.to_dict() == schema.to_dict()
    assert restored.strict
    assert restored.predicate("BORN_IN").domain == ("Person",)
