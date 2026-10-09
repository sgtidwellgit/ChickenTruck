"""Tests for chickentruck.soup."""

from chickentruck import (
    CONTRADICTED,
    DISPUTED,
    SUPPORTED,
    UNKNOWN,
    ChickenStock,
    Mention,
    Ref,
    check_claim,
    render_facts,
)
from chickentruck.soup import humanize_predicate


def test_humanize_predicate():
    assert humanize_predicate("BORN_IN") == "born in"


def test_render_facts_with_citations(kitchen):
    stock, coop = kitchen
    facts = stock.find(subject="person:franklin", predicate="WORKED_AT") + stock.find(
        predicate="BIRTH_YEAR"
    )

    text = render_facts(facts, coop=coop)

    assert text.splitlines() == [
        "- Benjamin Franklin worked at Post Office "
        "(role: Deputy Postmaster General; from 1753 to 1774; confidence 0.72) [1]",
        "- Benjamin Franklin birth year 1706 (confidence 0.81) [2]",
        "",
        "Sources:",
        "[1] letters",
        "[2] Encyclopedia - https://example.org/franklin",
    ]


def test_render_facts_uses_stock_entities_and_options(kitchen):
    stock, _ = kitchen
    [fact] = stock.find(predicate="BIRTH_YEAR")

    assert render_facts([fact], stock=stock, humanize=False, cite=False) == (
        "- Benjamin Franklin BIRTH_YEAR 1706 (confidence 0.81)"
    )
    assert render_facts([fact], cite=False).startswith("- person:franklin")
    assert render_facts([]) == ""


def test_render_marks_superseded(kitchen):
    stock, coop = kitchen
    [conflict] = stock.conflicts()
    stock.resolve_conflict(conflict.conflict_id, conflict.fact_ids[0])
    [loser] = [f for f in stock.all() if not f.active]

    assert "superseded" in render_facts([loser], coop=coop)


def test_supported_claim(kitchen):
    stock, coop = kitchen

    check = check_claim(stock, "person:franklin", "BIRTH_YEAR", 1706)

    assert check.verdict == SUPPORTED
    assert check.supported
    assert check.confidence == check.supporting[0].confidence
    assert [e.source.id for e in check.evidence] == ["encyclopedia"]


def test_contradicted_claim(kitchen):
    stock, _ = kitchen

    check = check_claim(stock, Ref("person:franklin"), "BIRTH_YEAR", 1705)

    assert check.verdict == CONTRADICTED
    assert check.supporting == ()
    assert check.contradicting[0].object == 1706


def test_open_conflict_means_disputed(kitchen):
    stock, coop = kitchen

    check = check_claim(stock, "Ben Franklin", "BORN_IN", "Boston", coop=coop)

    assert check.verdict == DISPUTED
    assert [f.object for f in check.supporting] == [Ref("place:boston")]
    assert [f.object for f in check.contradicting] == [Ref("place:philadelphia")]


def test_settled_conflict_becomes_supported(kitchen):
    stock, coop = kitchen
    [conflict] = stock.conflicts()
    stock.resolve_conflict(conflict.conflict_id, conflict.fact_ids[0])

    assert check_claim(stock, "Ben Franklin", "BORN_IN", "Boston", coop=coop).verdict == SUPPORTED
    assert check_claim(stock, "Ben Franklin", "BORN_IN", "Philadelphia", coop=coop).verdict == CONTRADICTED


def test_multi_valued_predicates_never_contradict(kitchen):
    stock, _ = kitchen

    assert check_claim(stock, "person:franklin", "WORKED_AT", "org:other").verdict == UNKNOWN
    assert check_claim(stock, "person:franklin", "WORKED_AT", "org:post-office").verdict == SUPPORTED


def test_at_limits_to_valid_facts(kitchen):
    stock, _ = kitchen

    assert check_claim(stock, "person:franklin", "WORKED_AT", Ref("org:post-office"), at="1760").supported
    assert check_claim(stock, "person:franklin", "WORKED_AT", Ref("org:post-office"), at="1780").verdict == UNKNOWN


def test_unknown_subjects_and_mentions(kitchen):
    stock, coop = kitchen

    assert check_claim(stock, "Nobody", "BORN_IN", "Boston", coop=coop).verdict == UNKNOWN
    assert check_claim(stock, Mention("Ben Franklin"), "BORN_IN", Mention("Nowhere"), coop=coop).verdict == CONTRADICTED
    assert check_claim(stock, Mention("person:franklin"), "BIRTH_YEAR", 1706).supported


def test_without_schema_nothing_contradicts():
    from chickentruck import ChickenTender, Evidence, Source, grill

    stock = ChickenStock()
    stock.add(grill(ChickenTender(Ref("a"), "COLOR", "red", evidence=[Evidence(Source("s"))])))

    assert check_claim(stock, "a", "COLOR", "red").supported
    assert check_claim(stock, "a", "COLOR", "blue").verdict == UNKNOWN
