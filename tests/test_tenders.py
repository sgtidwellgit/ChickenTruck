"""Tests for chickentruck.tenders."""

import pytest

from chickentruck import ChickenTender, Evidence, Nugget, Source, noisy_or


def test_tender_from_nugget_copies_claim(source):
    nugget = Nugget(subject="Benjamin Franklin", predicate="BORN_IN", object="Boston")
    tender = ChickenTender.from_nugget(nugget, evidence=[Evidence(source, confidence=0.9)])

    assert (tender.subject, tender.predicate, tender.object) == (
        "Benjamin Franklin",
        "BORN_IN",
        "Boston",
    )
    assert tender.sources == (source,)


def test_tender_parses_validity():
    tender = ChickenTender("a", "b", "c", valid_from="1757", valid_to="1775-03")

    assert tender.valid_from.precision == "year"
    assert tender.valid_to.isoformat() == "1775-03"


def test_tender_defaults_are_empty():
    tender = ChickenTender("a", "b", "c")

    assert tender.evidence == ()
    assert tender.confidence is None
    assert tender.valid_from is None
    assert tender.qualifiers == {}


def test_confidence_is_weighted_by_authority(source):
    assert Evidence(source, confidence=0.5).weighted_confidence == pytest.approx(0.45)
    assert Evidence(Source("unknown"), confidence=0.5).weighted_confidence == 0.5


def test_noisy_or_combines_independent_evidence():
    a = Evidence(Source("a"), confidence=0.6)
    b = Evidence(Source("b"), confidence=0.5)
    unknown = Evidence(Source("c"))

    assert noisy_or([a, b, unknown]) == pytest.approx(0.8)
    assert noisy_or([unknown]) is None
    assert noisy_or([]) is None


def test_values_outside_unit_interval_are_refused():
    with pytest.raises(ValueError):
        Source("s", authority=1.5)
    with pytest.raises(ValueError):
        Evidence(Source("s"), confidence=-0.1)
    with pytest.raises(ValueError):
        Source("s", kind="rumor")
