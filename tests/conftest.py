"""Shared fixtures: a small schema, coop, source, and clock."""

from datetime import datetime, timedelta, timezone

import pytest

from chickentruck import ChickenCoop, Entity, EntityType, Predicate, Schema, Source


@pytest.fixture
def schema():
    schema = Schema()
    schema.add_type(EntityType("Person"))
    schema.add_type(EntityType("Scientist", parent="Person"))
    schema.add_type(EntityType("Place"))
    schema.add_type(EntityType("Organization"))
    schema.add_predicate(
        Predicate("BORN_IN", domain="Person", range="Place", cardinality="one", temporal="moment")
    )
    schema.add_predicate(
        Predicate("BIRTH_YEAR", domain="Person", range="integer", cardinality="one")
    )
    schema.add_predicate(Predicate("WORKED_AT", domain="Person", range="Organization"))
    schema.add_predicate(
        Predicate("HEADQUARTERED_IN", domain="Organization", range="Place", cardinality="one")
    )
    return schema


@pytest.fixture
def coop(schema):
    coop = ChickenCoop(schema=schema)
    coop.add(Entity("person:franklin", "Benjamin Franklin", "Scientist", aliases={"Ben Franklin"}))
    coop.add(Entity("place:boston", "Boston", "Place"))
    coop.add(Entity("place:philadelphia", "Philadelphia", "Place"))
    coop.add(Entity("org:post-office", "Post Office", "Organization"))
    return coop


@pytest.fixture
def source():
    return Source("encyclopedia", uri="https://example.org/franklin", authority=0.9)


class Clock:
    """A controllable UTC clock for stock tests."""

    def __init__(self):
        self.now = datetime(2026, 1, 1, tzinfo=timezone.utc)

    def __call__(self):
        return self.now

    def tick(self, days=1):
        self.now += timedelta(days=days)
        return self.now


@pytest.fixture
def clock():
    return Clock()
