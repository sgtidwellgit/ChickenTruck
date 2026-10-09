"""Tests for chickentruck.stock."""

from datetime import datetime, timezone

import pytest

from chickentruck import (
    ChickenTender,
    Evidence,
    Ref,
    Source,
    grill,
    highest_authority,
    highest_confidence,
    most_recent_evidence,
)


def fact(obj="place:boston", predicate="BORN_IN", confidence=0.9, source=None, **kw):
    evidence = [
        Evidence(
            source or Source("s"),
            confidence=confidence,
            extracted_at=kw.pop("extracted_at", None),
        )
    ]
    obj = Ref(obj) if isinstance(obj, str) else obj
    result = grill(ChickenTender(Ref("person:franklin"), predicate, obj, evidence=evidence, **kw))
    assert result.accepted, result.findings
    return result.fact


def test_stock_starts_empty(make_stock):
    stock = make_stock()

    assert len(stock) == 0
    assert stock.all() == []


def test_add_records_time_and_accepts_results(make_stock, clock):
    stock = make_stock(clock=clock)
    result = grill(ChickenTender(Ref("a"), "P", 1, evidence=[Evidence(Source("s"))]))

    stored = stock.add(result)

    assert stored.recorded_at == clock.now
    assert stock.get(stored.fact_id) == stored
    assert list(stock) == [stored]


def test_only_accepted_results_can_be_stocked(make_stock):
    stock = make_stock()
    rejected = grill(ChickenTender(Ref("a"), "P", 1))

    with pytest.raises(ValueError):
        stock.add(rejected)
    with pytest.raises(TypeError):
        stock.add("fact-1")


def test_same_claim_merges_evidence(make_stock, clock):
    stock = make_stock(clock=clock)
    first = stock.add(fact(confidence=0.6, source=Source("a")))
    clock.tick()
    merged = stock.add(fact(confidence=0.5, source=Source("b")))

    assert len(stock) == 1
    assert merged.fact_id == first.fact_id
    assert len(merged.evidence) == 2
    assert merged.confidence == pytest.approx(0.8)
    assert merged.recorded_at == first.recorded_at
    assert [s.id for s in stock.sources()] == ["a", "b"]


def test_find_by_pattern(make_stock):
    stock = make_stock()
    born = stock.add(fact())
    year = stock.add(fact(1706, predicate="BIRTH_YEAR"))

    assert stock.find(subject="person:franklin") == [born, year]
    assert stock.find(subject=Ref("person:franklin"), predicate="BIRTH_YEAR") == [year]
    assert stock.find(object=Ref("place:boston")) == [born]
    assert stock.find(object=1706) == [year]
    assert stock.find(subject="nobody") == []


def test_find_filters_by_confidence(make_stock):
    stock = make_stock()
    stock.add(fact(confidence=0.6))
    strong = stock.add(fact(1706, predicate="BIRTH_YEAR", confidence=0.95))

    assert stock.find(min_confidence=0.9) == [strong]


def test_find_valid_at(make_stock):
    stock = make_stock()
    london = stock.add(fact("place:london", predicate="LIVED_IN", valid_from="1757", valid_to="1775"))
    philly = stock.add(fact("place:philadelphia", predicate="LIVED_IN", valid_from="1775"))

    assert stock.find(predicate="LIVED_IN", valid_at="1760") == [london]
    assert stock.find(predicate="LIVED_IN", valid_at="1775-06") == [philly]
    assert stock.find(predicate="LIVED_IN", valid_at="1700") == []


def test_conflicts_need_a_single_valued_predicate(make_stock, schema):
    stock = make_stock(schema=schema)
    stock.add(fact("org:a", predicate="WORKED_AT"))
    stock.add(fact("org:b", predicate="WORKED_AT"))

    assert stock.conflicts() == []


def test_no_schema_means_no_conflict_detection(make_stock):
    stock = make_stock()
    stock.add(fact())
    stock.add(fact("place:philadelphia"))

    assert stock.conflicts() == []


def test_keep_both_records_an_open_conflict(make_stock, schema):
    stock = make_stock(schema=schema)
    boston = stock.add(fact())
    philly = stock.add(fact("place:philadelphia"))

    [conflict] = stock.conflicts(open_only=True)
    assert conflict.fact_ids == (boston.fact_id, philly.fact_id)
    assert conflict.policy == "keep_both"
    assert conflict.open
    assert len(stock.find(predicate="BORN_IN")) == 2


def test_resolve_conflict_supersedes_the_loser(make_stock, schema, clock):
    stock = make_stock(schema=schema, clock=clock)
    boston = stock.add(fact())
    philly = stock.add(fact("place:philadelphia"))
    [conflict] = stock.conflicts()
    clock.tick()

    settled = stock.resolve_conflict(conflict.conflict_id, boston.fact_id)

    assert settled.winner == boston.fact_id
    assert stock.conflicts(open_only=True) == []
    assert stock.find(predicate="BORN_IN") == [boston]
    loser = stock.get(philly.fact_id)
    assert not loser.active
    assert loser.superseded_at == clock.now
    assert len(stock) == 2
    with pytest.raises(ValueError):
        stock.resolve_conflict(conflict.conflict_id, "fact:other")


def test_non_overlapping_validity_is_not_a_conflict(make_stock, schema):
    stock = make_stock(schema=schema)
    stock.add(fact("place:a", predicate="HEADQUARTERED_IN", valid_from="1900", valid_to="1950"))
    stock.add(fact("place:b", predicate="HEADQUARTERED_IN", valid_from="1950"))

    assert stock.conflicts() == []


def test_highest_confidence_policy_picks_a_winner(make_stock, schema):
    stock = make_stock(schema=schema, policy=highest_confidence)
    weak = stock.add(fact(confidence=0.6))
    strong = stock.add(fact("place:philadelphia", confidence=0.95))

    [conflict] = stock.conflicts()
    assert conflict.winner == strong.fact_id
    assert stock.find(predicate="BORN_IN") == [strong]
    assert not stock.get(weak.fact_id).active


def test_new_fact_can_lose(make_stock, schema):
    stock = make_stock(schema=schema, policy=highest_authority)
    trusted = stock.add(fact(source=Source("a", authority=0.9)))
    rumor = stock.add(fact("place:philadelphia", source=Source("b", authority=0.6)))

    assert not rumor.active
    assert stock.find(predicate="BORN_IN") == [trusted]


def test_most_recent_evidence_policy(make_stock, schema):
    stock = make_stock(schema=schema, policy=most_recent_evidence)
    stock.add(fact(extracted_at=datetime(2020, 1, 1, tzinfo=timezone.utc)))
    newer = stock.add(
        fact("place:philadelphia", extracted_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
    )

    assert stock.find(predicate="BORN_IN") == [newer]


def test_ties_keep_both(make_stock, schema):
    stock = make_stock(schema=schema, policy=highest_confidence)
    stock.add(fact(confidence=0.8))
    stock.add(fact("place:philadelphia", confidence=0.8))

    assert stock.conflicts(open_only=True)
    assert len(stock.find(predicate="BORN_IN")) == 2


def test_as_of_answers_what_was_believed_then(make_stock, schema, clock):
    stock = make_stock(schema=schema, policy=highest_confidence, clock=clock)
    day0 = clock.now
    old = stock.add(fact(confidence=0.6))
    day1 = clock.tick()
    new = stock.add(fact("place:philadelphia", confidence=0.95))

    assert stock.find(predicate="BORN_IN", as_of=day0) == [stock.get(old.fact_id)]
    assert stock.find(predicate="BORN_IN", as_of=day1) == [new]
    assert len(stock.find(predicate="BORN_IN", include_superseded=True)) == 2
