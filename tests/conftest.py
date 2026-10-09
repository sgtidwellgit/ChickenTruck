"""Shared fixtures: a small schema, coop, source, and clock."""

from datetime import datetime, timedelta, timezone

import pytest

from chickentruck import (
    ChickenCoop,
    ChickenStock,
    ChickenTender,
    Entity,
    Evidence,
    EntityType,
    Predicate,
    Schema,
    Source,
    SqliteStock,
    grill,
)


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


@pytest.fixture(params=["memory", "sqlite"])
def make_stock(request, tmp_path):
    """Build a stock on each backend, so both are held to the same behavior."""

    opened = []

    def make(**kwargs):
        if request.param == "memory":
            return ChickenStock(**kwargs)
        stock = SqliteStock(tmp_path / f"stock{len(opened)}.db", **kwargs)
        opened.append(stock)
        return stock

    yield make
    for stock in opened:
        stock.close()


@pytest.fixture
def kitchen(make_stock, schema, clock):
    """A stocked knowledge base about Franklin, with an open conflict.

    Returns ``(stock, coop)``; the coop persists its entities in the stock.
    """

    stock = make_stock(schema=schema, clock=clock)
    coop = ChickenCoop(schema=schema, store=stock)
    coop.add(Entity("person:franklin", "Benjamin Franklin", "Scientist", aliases={"Ben Franklin"}))
    coop.add(Entity("place:boston", "Boston", "Place"))
    coop.add(Entity("place:philadelphia", "Philadelphia", "Place"))
    coop.add(Entity("org:post-office", "Post Office", "Organization"))

    encyclopedia = Source("encyclopedia", title="Encyclopedia", uri="https://example.org/franklin", authority=0.9)
    letters = Source("letters", kind="document", authority=0.8)
    blog = Source("blog", authority=0.6)

    def stock_claim(subject, predicate, obj, source, confidence=0.9, **kw):
        tender = coop.resolve_tender(
            ChickenTender(subject, predicate, obj, evidence=[Evidence(source, confidence=confidence)], **kw)
        )
        result = grill(tender, schema=schema, coop=coop)
        assert result.accepted, result.findings
        return stock.add(result)

    stock_claim("Ben Franklin", "BORN_IN", "Boston", encyclopedia, 0.95, valid_from="1706-01-17")
    stock_claim("Benjamin Franklin", "BORN_IN", "Boston", letters, 0.7, valid_from="1706-01-17")
    stock_claim("Benjamin Franklin", "BORN_IN", "Philadelphia", blog, 0.9, valid_from="1706-01-17")
    stock_claim("Benjamin Franklin", "BIRTH_YEAR", 1706, encyclopedia)
    stock_claim(
        "Benjamin Franklin",
        "WORKED_AT",
        "Post Office",
        letters,
        valid_from="1753",
        valid_to="1774",
        qualifiers={"role": "Deputy Postmaster General"},
    )
    return stock, coop
