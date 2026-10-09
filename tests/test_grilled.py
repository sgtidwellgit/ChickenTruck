"""Tests for chickentruck.grilled."""

import pytest

from chickentruck import (
    ACCEPTED,
    NEEDS_REVIEW,
    REJECTED,
    ChickenTender,
    Evidence,
    Finding,
    Mention,
    Ref,
    Source,
    grill,
)
from chickentruck.grilled import fact_id_for


def tender(subject="person:franklin", predicate="BORN_IN", obj=None, confidence=0.9, **kw):
    obj = Ref("place:boston") if obj is None else obj
    evidence = kw.pop("evidence", [Evidence(Source("s"), confidence=confidence)])
    subject = Ref(subject) if isinstance(subject, str) else subject
    return ChickenTender(subject, predicate, obj, evidence=evidence, **kw)


def rules_of(result):
    return {f.rule for f in result.findings}


def test_clean_tender_is_accepted_with_a_fact(schema, coop):
    result = grill(tender(valid_from="1706"), schema=schema, coop=coop)

    assert result.status == ACCEPTED
    assert result.accepted
    assert result.fact.subject == Ref("person:franklin")
    assert result.fact.confidence == pytest.approx(0.9)
    assert result.fact.fact_id == fact_id_for(result.tender)


def test_grill_works_without_a_schema():
    assert grill(tender(predicate="ANYTHING", obj="free text")).accepted


def test_missing_evidence_rejects_unless_waived():
    assert grill(tender(evidence=[])).status == REJECTED
    assert grill(tender(evidence=[]), require_evidence=False).accepted


def test_structural_errors_reject():
    bad = ChickenTender(Ref("x"), " ", None, evidence=[Evidence(Source("s"))])

    result = grill(bad)

    assert result.status == REJECTED
    assert {"predicate.empty", "object.missing"} <= rules_of(result)


def test_unresolved_entities_go_to_review():
    result = grill(tender(subject=Mention("Somebody"), obj=Mention("Somewhere")))

    assert result.status == NEEDS_REVIEW
    assert {"subject.unresolved", "object.unresolved"} <= rules_of(result)
    assert result.fact is None


def test_naive_and_empty_intervals_reject():
    assert "time.naive" in rules_of(grill(tender(valid_from="2026-01-01T00:00:00")))
    result = grill(tender(predicate="WORKED_AT", valid_from="1775", valid_to="1775"))
    assert "time.empty_interval" in rules_of(result)


def test_confidence_thresholds():
    assert grill(tender(confidence=0.1)).status == REJECTED
    assert grill(tender(confidence=0.3)).status == NEEDS_REVIEW
    assert grill(tender(confidence=0.3), accept_at=0.3).accepted
    unknown = grill(tender(evidence=[Evidence(Source("s"))]))
    assert unknown.accepted
    assert "confidence.unknown" in rules_of(unknown)
    with pytest.raises(ValueError):
        grill(tender(), accept_at=0.2, reject_below=0.5)


def test_unknown_predicate_is_info_unless_strict(schema):
    assert grill(tender(predicate="LIKED"), schema=schema).accepted
    schema.strict = True
    assert grill(tender(predicate="LIKED"), schema=schema).status == REJECTED


def test_moment_predicate_cannot_have_an_end(schema, coop):
    result = grill(tender(valid_from="1706", valid_to="1707"), schema=schema, coop=coop)

    assert "schema.moment_with_end" in rules_of(result)
    assert result.status == REJECTED


def test_domain_check_uses_coop_types_and_subtypes(schema, coop):
    assert grill(tender(), schema=schema, coop=coop).accepted  # Scientist is a Person
    wrong = grill(tender(subject="place:boston"), schema=schema, coop=coop)
    assert wrong.status == REJECTED
    assert "schema.domain" in rules_of(wrong)


def test_type_checks_need_a_coop(schema):
    result = grill(tender(), schema=schema)

    assert result.accepted
    assert "schema.domain" in rules_of(result)


def test_range_checks(schema, coop):
    def status(**kw):
        return grill(tender(**kw), schema=schema, coop=coop).status

    assert status(predicate="BIRTH_YEAR", obj=1706) == ACCEPTED
    assert status(predicate="BIRTH_YEAR", obj="1706") == REJECTED
    assert status(predicate="BIRTH_YEAR", obj=True) == REJECTED
    assert status(obj=Ref("org:post-office")) == REJECTED
    assert status(obj="Boston") == NEEDS_REVIEW


def test_unknown_entity_goes_to_review(schema, coop):
    result = grill(tender(subject="person:nobody"), schema=schema, coop=coop)

    assert result.status == NEEDS_REVIEW
    assert "subject.unknown_entity" in rules_of(result)


def test_custom_rules_add_findings():
    def no_boston(t):
        if t.object == Ref("place:boston"):
            yield Finding("custom.no_boston", "error", "Boston is off the menu")

    result = grill(tender(), rules=[no_boston])

    assert result.status == REJECTED
    assert result.reasons == ["Boston is off the menu"]


def test_fact_id_ignores_evidence_but_not_the_claim():
    a = tender(confidence=0.9)
    b = tender(evidence=[Evidence(Source("other"), confidence=0.5)])

    assert fact_id_for(a) == fact_id_for(b)
    assert fact_id_for(a) != fact_id_for(tender(obj=Ref("place:philadelphia")))
    assert fact_id_for(a) != fact_id_for(tender(valid_from="1706"))
    assert fact_id_for(a) != fact_id_for(tender(qualifiers={"role": "x"}))
