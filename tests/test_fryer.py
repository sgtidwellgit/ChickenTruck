"""Tests for chickentruck.fryer: pattern and LLM extraction, and process_text."""

import json

import pytest

from chickentruck import (
    ACCEPTED,
    NEEDS_REVIEW,
    ChickenCoop,
    ChickenStock,
    ExtractionError,
    LLMExtractor,
    Mention,
    Pattern,
    PatternExtractor,
    Ref,
    Source,
    build_prompt,
    parse_claims,
    process_text,
)
from chickentruck.fryer import split_text, to_iso_date

BIO = (
    "Benjamin Franklin was born in Boston on January 17, 1706. "
    "In 1723 Franklin moved to Philadelphia. "
    "Franklin served as Deputy Postmaster General at the Post Office from 1753 to 1774. "
    "He was born in Boston, according to the letters."
)


@pytest.fixture
def bio():
    return Source("bio", title="A short biography", authority=0.9)


def fixed_clock():
    from datetime import datetime, timezone

    return datetime(2026, 1, 1, tzinfo=timezone.utc)


# --- Patterns -------------------------------------------------------------


@pytest.mark.parametrize(
    "text, iso",
    [
        ("1706", "1706"),
        ("1706-01", "1706-01"),
        ("1706-01-17", "1706-01-17"),
        ("January 17, 1706", "1706-01-17"),
        ("17th Jan. 1706", "1706-01-17"),
        ("Sept 1706", "1706-09"),
    ],
)
def test_to_iso_date(text, iso):
    assert to_iso_date(text) == iso


def test_to_iso_date_refuses_nonsense():
    with pytest.raises(ValueError):
        to_iso_date("someday")


def test_template_extracts_subject_object_and_validity(bio):
    pattern = Pattern("BORN_IN", "{subject} was born in {object} on {valid_from}")

    [tender] = PatternExtractor([pattern], clock=fixed_clock).extract(BIO, source=bio)

    assert tender.subject == "Benjamin Franklin"
    assert tender.predicate == "BORN_IN"
    assert tender.object == "Boston"
    assert tender.valid_from.isoformat() == "1706-01-17"
    [evidence] = tender.evidence
    assert evidence.source == bio
    assert evidence.quote == "Benjamin Franklin was born in Boston on January 17, 1706"
    assert evidence.locator == "chars 0-56"
    assert BIO[0:56] == evidence.quote
    assert evidence.confidence == 0.7
    assert evidence.extractor == "pattern"
    assert evidence.extracted_at == fixed_clock()


def test_extra_placeholders_become_qualifiers(bio):
    pattern = Pattern(
        "WORKED_AT",
        "{subject} served as {role} at the {object} from {valid_from:year} to {valid_to:year}",
    )

    [tender] = PatternExtractor([pattern]).extract(BIO, source=bio)

    assert tender.subject == "Franklin"
    assert tender.object == "Post Office"
    assert tender.qualifiers == {"role": "Deputy Postmaster General"}
    assert (tender.valid_from.isoformat(), tender.valid_to.isoformat()) == ("1753", "1774")


def test_pronouns_and_articles_are_not_names(bio):
    pattern = Pattern("BORN_IN", "{subject} was born in {object}")
    founded = Pattern("FOUNDED_BY", "{subject} was founded by {object}")
    text = BIO + " The University of Pennsylvania was founded by Benjamin Franklin."

    tenders = PatternExtractor([pattern, founded]).extract(text, source=bio)

    assert [(t.subject, t.object) for t in tenders] == [
        ("Benjamin Franklin", "Boston"),
        ("University of Pennsylvania", "Benjamin Franklin"),
    ]


def test_initials_and_connectors_stay_in_names(bio):
    pattern = Pattern("BORN_IN", "{subject} was born in {object}")

    [tender] = PatternExtractor([pattern]).extract("J. R. de Silva was born in Rio de Janeiro.", source=bio)

    assert (tender.subject, tender.object) == ("J. R. de Silva", "Rio de Janeiro")


def test_literal_words_ignore_case_and_spacing(bio):
    pattern = Pattern("BORN_IN", "{subject} was born in {object}")

    [tender] = PatternExtractor([pattern]).extract("Ada Lovelace WAS\n  born IN London", source=bio)

    assert tender.object == "London"


def test_specific_patterns_win_over_general_ones(bio):
    patterns = [
        Pattern("BORN_IN", "{subject} was born in {object} on {valid_from}"),
        Pattern("BORN_IN", "{subject} was born in {object}"),
    ]

    tenders = PatternExtractor(patterns).extract(BIO, source=bio)

    assert len(tenders) == 1
    assert tenders[0].valid_from is not None


def test_typed_placeholders_and_mention_types(bio):
    pattern = Pattern(
        "POPULATION",
        "{subject} had a population of {object:int}",
        subject_type="Place",
    )

    [tender] = PatternExtractor([pattern]).extract("Boston had a population of 16,382 in 1765.", source=bio)

    assert tender.subject == Mention("Boston", "Place")
    assert tender.object == 16382


def test_object_type_makes_a_typed_mention(bio):
    pattern = Pattern("MOVED_TO", "In {valid_from:year} {subject} moved to {object}", object_type="Place")

    [tender] = PatternExtractor([pattern]).extract(BIO, source=bio)

    assert tender.object == Mention("Philadelphia", "Place")
    assert tender.valid_from.isoformat() == "1723"


def test_raw_regex_patterns_and_converters(bio):
    pattern = Pattern(
        "AGE",
        r"(?P<subject>[A-Z]\w+) was (?P<object>\d+) years old",
        regex=True,
        convert={"object": int},
        confidence=None,
    )

    [tender] = PatternExtractor([pattern]).extract("Franklin was 84 years old.", source=bio)

    assert tender.object == 84
    assert tender.evidence[0].confidence is None


def test_results_come_in_text_order(bio):
    patterns = [
        Pattern("WORKED_AT", "{subject} served as {role} at the {object}"),
        Pattern("BORN_IN", "{subject} was born in {object}"),
    ]

    tenders = PatternExtractor(patterns).extract(BIO, source=bio)

    assert [t.predicate for t in tenders] == ["BORN_IN", "WORKED_AT"]


@pytest.mark.parametrize(
    "kwargs",
    [
        {"predicate": "", "template": "{subject} is {object}"},
        {"predicate": "P", "template": "{subject} is here"},
        {"predicate": "P", "template": "{subject} is {object} and {object}"},
        {"predicate": "P", "template": "{subject} is {object:color}"},
        {"predicate": "P", "template": "(?P<subject>x)", "regex": True},
        {"predicate": "P", "template": "{subject} is {object}", "confidence": 2},
    ],
)
def test_bad_patterns_are_refused(kwargs):
    with pytest.raises(ValueError):
        Pattern(**kwargs)


# --- LLM ------------------------------------------------------------------


class FakeModel:
    """Records prompts and replies with canned text."""

    def __init__(self, *replies):
        self.replies = list(replies)
        self.prompts = []

    def __call__(self, prompt):
        self.prompts.append(prompt)
        return self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]


def claims(*items):
    return json.dumps({"claims": list(items)})


def test_prompt_without_schema_asks_for_snake_case():
    prompt = build_prompt("Some text.")

    assert "UPPER_SNAKE_CASE" in prompt
    assert '"""\nSome text.\n"""' in prompt


def test_prompt_lists_schema(schema):
    prompt = build_prompt("Some text.", schema, instructions="Ignore footnotes.")

    assert "- Scientist (a kind of Person)" in prompt
    assert "- BORN_IN: Person -> Place, one value at a time, happens at a moment" in prompt
    assert "- WORKED_AT: Person -> Organization" in prompt
    assert "Ignore footnotes." in prompt


@pytest.mark.parametrize(
    "response",
    [
        claims({"subject": "a"}),
        '[{"subject": "a"}]',
        '{"subject": "a"}',
        'Here you go:\n```json\n{"claims": [{"subject": "a"}]}\n```',
        'Sure. {"claims": [{"subject": "a"}]} Anything else?',
        'Note {not json} then [{"subject": "a"}]',
    ],
)
def test_parse_claims_finds_json(response):
    assert parse_claims(response) == [{"subject": "a"}]


def test_parse_claims_refuses_prose():
    with pytest.raises(ExtractionError) as error:
        parse_claims("I could not find any claims.")
    assert error.value.response == "I could not find any claims."


def test_llm_claims_become_tenders(schema, bio):
    model = FakeModel(
        claims(
            {
                "subject": "Benjamin Franklin",
                "subject_type": "Person",
                "predicate": "born in",
                "object": "Boston",
                "object_type": "Place",
                "valid_from": "1706-01-17",
                "quote": "was born in   Boston",
                "confidence": 0.9,
            },
            {"subject": "Franklin", "predicate": "BIRTH_YEAR", "object": "1706", "quote": "January 17, 1706"},
            {
                "subject": "Franklin",
                "predicate": "WORKED_AT",
                "object": "Post Office",
                "qualifiers": {"role": "Deputy Postmaster General"},
                "valid_from": 1753,
                "valid_to": 1774,
                "quote": "Franklin served as Deputy Postmaster General at the Post Office",
            },
        )
    )
    extractor = LLMExtractor(model, schema=schema, clock=fixed_clock)

    born, year, worked = extractor.extract(BIO, source=bio)

    assert "BORN_IN: Person -> Place" in model.prompts[0]
    assert born.subject == Mention("Benjamin Franklin", "Person")
    assert born.predicate == "BORN_IN"
    assert born.object == Mention("Boston", "Place")
    assert born.evidence[0].quote == "was born in Boston"
    assert born.evidence[0].locator == "chars 18-36"
    assert born.evidence[0].confidence == 0.9
    assert born.evidence[0].extractor == "llm"

    assert year.object == 1706  # schema range "integer"
    assert year.evidence[0].confidence == 0.6  # the extractor's default

    assert worked.object == Mention("Post Office", "Organization")  # schema range
    assert worked.qualifiers == {"role": "Deputy Postmaster General"}
    assert worked.valid_to.isoformat() == "1774"


@pytest.mark.parametrize(
    "item, reason",
    [
        ("just a string", "claim is not a JSON object"),
        ({"predicate": "P", "object": "x", "quote": "Franklin"}, "missing subject"),
        ({"subject": "a", "predicate": "  ", "object": "x", "quote": "Franklin"}, "missing predicate"),
        ({"subject": "a", "predicate": "P", "object": "", "quote": "Franklin"}, "missing object"),
        ({"subject": "a", "predicate": "P", "object": ["x"], "quote": "Franklin"}, "object must be a single value"),
        ({"subject": "a", "predicate": "P", "object": "x"}, "missing quote"),
        ({"subject": "a", "predicate": "P", "object": "x", "quote": "died in Paris"}, "quote not found in the text"),
        ({"subject": "a", "predicate": "P", "object": "x", "quote": "Franklin", "qualifiers": [1]}, "qualifiers must be a JSON object"),
        ({"subject": "a", "predicate": "P", "object": "x", "object_type": "integer", "quote": "Franklin"}, "object 'x' is not an integer"),
        ({"subject": "a", "predicate": "P", "object": "x", "object_type": "number", "quote": "Franklin"}, "object 'x' is not a number"),
        ({"subject": "a", "predicate": "P", "object": "x", "object_type": "boolean", "quote": "Franklin"}, "object 'x' is not true or false"),
    ],
)
def test_bad_claims_are_skipped_with_reasons(item, reason, bio):
    report = LLMExtractor(FakeModel(json.dumps([item]))).extract_with_report(BIO, source=bio)

    assert report.tenders == ()
    assert [s.reason for s in report.skipped] == [reason]
    assert report.skipped[0].item == item


def test_invalid_time_is_skipped(bio):
    item = {"subject": "a", "predicate": "P", "object": "x", "valid_from": "late", "quote": "Franklin"}

    [skipped] = LLMExtractor(FakeModel(json.dumps([item]))).extract_with_report(BIO, source=bio).skipped

    assert skipped.reason.startswith("invalid claim:")


def test_literal_objects_and_bad_confidence(bio):
    model = FakeModel(
        claims(
            {"subject": "a", "predicate": "ALIVE", "object": "yes", "object_type": "boolean", "quote": "Franklin", "confidence": 7},
            {"subject": "a", "predicate": "HEIGHT", "object": "1.8", "object_type": "number", "quote": "Franklin", "confidence": True},
            {"subject": "a", "predicate": "AGE", "object": 84, "quote": "Franklin"},
        )
    )

    alive, height, age = LLMExtractor(model, confidence=None).extract(BIO, source=bio)

    assert (alive.object, height.object, age.object) == (True, 1.8, 84)
    assert alive.evidence[0].confidence is None
    assert height.evidence[0].confidence is None


def test_quotes_can_be_optional(bio):
    model = FakeModel(claims({"subject": "a", "predicate": "P", "object": "x", "quote": "not there"}))

    [tender] = LLMExtractor(model, require_quote=False).extract(BIO, source=bio)

    assert tender.evidence[0].quote is None
    assert tender.evidence[0].locator is None


def test_unreadable_response_raises(bio):
    with pytest.raises(ExtractionError):
        LLMExtractor(FakeModel("no claims here")).extract(BIO, source=bio)


def test_long_text_is_chunked_with_global_locators(bio):
    text = "Ada Lovelace was born in London.\n\nAlan Turing was born in Maida Vale."
    model = FakeModel(
        claims({"subject": "Ada Lovelace", "predicate": "BORN_IN", "object": "London", "quote": "born in London"}),
        claims({"subject": "Alan Turing", "predicate": "BORN_IN", "object": "Maida Vale", "quote": "born in Maida Vale"}),
    )

    report = LLMExtractor(model, max_chars=40).extract_with_report(text, source=bio)

    assert len(model.prompts) == 2
    assert len(report.responses) == 2
    ada, alan = report.tenders
    start, end = (int(n) for n in alan.evidence[0].locator.split()[1].split("-"))
    assert text[start:end] == "born in Maida Vale"
    assert ada.evidence[0].locator == "chars 17-31"


def test_split_text():
    text = "One. Two.\n\nThree is longer. Four."

    chunks = split_text(text, 12)

    assert "".join(c for _, c in chunks) == text
    assert all(len(c) <= 12 for _, c in chunks)
    assert all(text[o : o + len(c)] == c for o, c in chunks)
    assert split_text("abcdefgh", 3) == [(0, "abc"), (3, "def"), (6, "gh")]
    with pytest.raises(ValueError):
        split_text(text, 0)


# --- process_text ---------------------------------------------------------


def test_process_text_runs_the_whole_pipeline(schema, coop, bio):
    stock = ChickenStock(schema=schema)
    patterns = PatternExtractor(
        [
            Pattern("BORN_IN", "{subject} was born in {object} on {valid_from}"),
            Pattern("BORN_IN", "{subject} was born in {object}"),
            Pattern("WORKED_AT", "{subject} served as {role} at the {object} from {valid_from:year} to {valid_to:year}"),
        ]
    )

    results = process_text(BIO, source=bio, extractor=patterns, coop=coop, stock=stock)

    assert [r.status for r in results] == [ACCEPTED, ACCEPTED]
    [born] = stock.find(subject="person:franklin", predicate="BORN_IN")
    assert born.object == Ref("place:boston")
    assert born.valid_from.isoformat() == "1706-01-17"
    # "Franklin" alone is not a known name: it becomes a provisional entity to review
    [worked] = stock.find(predicate="WORKED_AT")
    assert worked.subject == Ref("person:franklin-2")
    assert worked.object == Ref("org:post-office")
    assert [e.id for e in coop.provisional()] == ["person:franklin-2"]
    assert len(stock) == 2


def test_process_text_with_several_extractors_and_options(schema, coop, bio):
    model = FakeModel(claims({"subject": "Ben Franklin", "predicate": "BIRTH_YEAR", "object": 1706, "quote": "1706", "confidence": 0.9}))
    patterns = PatternExtractor([Pattern("BORN_IN", "{subject} was born in {object}")])
    stock = ChickenStock(schema=schema)

    results = process_text(
        BIO,
        source=bio,
        extractor=[patterns, LLMExtractor(model, schema=schema)],
        coop=coop,
        stock=stock,
        accept_at=0.9,
    )

    assert [r.status for r in results] == [NEEDS_REVIEW, NEEDS_REVIEW]
    assert len(stock) == 0


def test_process_text_without_coop_or_stock(bio):
    results = process_text(
        "Ada Lovelace was born in London.",
        source=bio,
        extractor=PatternExtractor([Pattern("BORN_IN", "{subject} was born in {object}")]),
    )

    [result] = results
    assert result.status == NEEDS_REVIEW  # unresolved mentions
    assert result.tender.subject == "Ada Lovelace"


def test_process_text_takes_schema_from_stock(schema, bio):
    stock = ChickenStock(schema=schema)
    coop = ChickenCoop()

    results = process_text(
        "Ada Lovelace was born in London.",
        source=bio,
        extractor=PatternExtractor([Pattern("BORN_IN", "{subject} was born in {object}")]),
        coop=coop,
        stock=stock,
    )

    assert results[0].accepted
    assert stock.all()[0].object == Ref("place:london")
