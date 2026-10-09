"""Tests for chickentruck.coop."""

import pytest

from chickentruck import ChickenCoop, ChickenTender, Entity, Mention, Ref
from chickentruck.coop import make_entity_id, normalize


def test_normalize_ignores_case_punctuation_and_spacing():
    assert normalize("  Benjamin   FRANKLIN, Jr. ") == "benjamin franklin jr"


def test_make_entity_id_is_readable():
    assert make_entity_id("Benjamin Franklin", "Person") == "person:benjamin-franklin"
    assert make_entity_id("Boston") == "boston"


def test_exact_and_alias_matches(coop):
    assert coop.resolve("Benjamin Franklin").entity_id == "person:franklin"
    alias = coop.resolve("Ben Franklin")
    assert alias.entity_id == "person:franklin"
    assert alias.score == 1.0


def test_normalized_match_scores_lower(coop):
    result = coop.resolve("ben  franklin.")

    assert result.entity_id == "person:franklin"
    assert result.score == 0.9


def test_type_hint_honors_subtypes(coop):
    assert coop.resolve("Ben Franklin", type="Person").entity_id == "person:franklin"
    assert coop.resolve("Boston", type="Person", create=False).entity_id is None


def test_ambiguous_mentions_stay_unresolved():
    coop = ChickenCoop()
    coop.add(Entity("place:paris-fr", "Paris", "Place"))
    coop.add(Entity("place:paris-tx", "Paris", "Place"))

    result = coop.resolve("Paris")

    assert result.ambiguous
    assert result.candidates == ("place:paris-fr", "place:paris-tx")
    assert len(coop) == 2


def test_unmatched_mention_creates_provisional_entity(coop):
    result = coop.resolve("Deborah Read", type="Person")

    assert result.created
    entity = coop.get(result.entity_id)
    assert entity.provisional
    assert entity.id == "person:deborah-read"
    assert coop.provisional() == [entity]
    assert not coop.confirm(entity.id).provisional


def test_created_ids_do_not_collide():
    coop = ChickenCoop()
    coop.add(Entity("boston", "Boston, Lincolnshire"))

    assert coop.resolve("Boston").entity_id == "boston-2"


def test_add_alias_makes_new_name_resolvable(coop):
    coop.add_alias("person:franklin", "Poor Richard")

    assert coop.resolve("poor richard").entity_id == "person:franklin"


def test_duplicate_entity_ids_are_refused(coop):
    with pytest.raises(ValueError):
        coop.add(Entity("place:boston", "Boston"))


def test_resolve_tender_uses_schema_range(coop):
    tender = ChickenTender("Ben Franklin", "BORN_IN", "Boston")

    resolved = coop.resolve_tender(tender)

    assert resolved.subject == Ref("person:franklin")
    assert resolved.object == Ref("place:boston")
    assert tender.subject == "Ben Franklin"


def test_resolve_tender_leaves_literals_alone(coop):
    resolved = coop.resolve_tender(ChickenTender("Ben Franklin", "BIRTH_YEAR", 1706))

    assert resolved.object == 1706


def test_resolve_tender_without_schema_resolves_only_mentions():
    coop = ChickenCoop()

    literal = coop.resolve_tender(ChickenTender("Franklin", "NICKNAME", "First American"))
    assert literal.object == "First American"

    entity = coop.resolve_tender(ChickenTender("Franklin", "VISITED", Mention("Paris", "Place")))
    assert entity.object == Ref("place:paris")


def test_unresolvable_mentions_stay_mentions(coop):
    resolved = coop.resolve_tender(ChickenTender("Somebody", "BORN_IN", "Boston"), create=False)

    assert resolved.subject == Mention("Somebody", "Person")
    assert resolved.object == Ref("place:boston")
