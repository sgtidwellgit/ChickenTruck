"""Tests for chickentruck.nuggets."""

import pytest

from chickentruck.nuggets import Nugget, extract_nuggets


def test_nugget_holds_subject_predicate_object():
    nugget = Nugget(subject="Benjamin Franklin", predicate="BORN_IN", object="Boston")

    assert nugget.subject == "Benjamin Franklin"
    assert nugget.predicate == "BORN_IN"
    assert nugget.object == "Boston"


def test_extract_nuggets_is_not_yet_implemented():
    with pytest.raises(NotImplementedError):
        extract_nuggets("Benjamin Franklin was born in Boston in 1706.")
