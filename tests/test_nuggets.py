"""Tests for chickentruck.nuggets."""

from chickentruck import Pattern, PatternExtractor, Source
from chickentruck.nuggets import Nugget, extract_nuggets


def test_nugget_holds_subject_predicate_object():
    nugget = Nugget(subject="Benjamin Franklin", predicate="BORN_IN", object="Boston")

    assert nugget.subject == "Benjamin Franklin"
    assert nugget.predicate == "BORN_IN"
    assert nugget.object == "Boston"


def test_extract_nuggets_strips_tenders_to_bare_facts():
    extractor = PatternExtractor(
        [
            Pattern("BORN_IN", "{subject} was born in {object}", subject_type="Person", object_type="Place"),
            Pattern("BIRTH_YEAR", "{subject} was born in {object:int}"),
        ]
    )

    nuggets = extract_nuggets("Benjamin Franklin was born in Boston. Ada Lovelace was born in 1815.", extractor)

    assert nuggets == [
        Nugget("Benjamin Franklin", "BORN_IN", "Boston"),
        Nugget("Ada Lovelace", "BIRTH_YEAR", 1815),
    ]


def test_extract_nuggets_passes_the_source():
    seen = []

    class Recorder:
        def extract(self, text, *, source):
            seen.append(source)
            return []

    assert extract_nuggets("text", Recorder()) == []
    assert extract_nuggets("text", Recorder(), source=Source("mine")) == []
    assert [s.id for s in seen] == ["text", "mine"]
