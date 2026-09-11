"""Tests for chickentruck.tenders."""

from chickentruck.nuggets import Nugget
from chickentruck.tenders import ChickenTender


def test_tender_from_nugget_copies_subject_predicate_object():
    nugget = Nugget(subject="Benjamin Franklin", predicate="BORN_IN", object="Boston")
    tender = ChickenTender.from_nugget(nugget, source="wikipedia", confidence=0.9)

    assert tender.subject == nugget.subject
    assert tender.predicate == nugget.predicate
    assert tender.object == nugget.object
    assert tender.source == "wikipedia"
    assert tender.confidence == 0.9


def test_tender_defaults_are_unset():
    tender = ChickenTender(subject="a", predicate="b", object="c")

    assert tender.source is None
    assert tender.confidence is None
    assert tender.valid_from is None
    assert tender.valid_to is None
    assert tender.extraction_metadata == {}
