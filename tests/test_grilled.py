"""Tests for chickentruck.grilled."""

import pytest

from chickentruck.grilled import grill
from chickentruck.tenders import ChickenTender


def test_grill_is_not_yet_implemented():
    tender = ChickenTender(subject="a", predicate="b", object="c")

    with pytest.raises(NotImplementedError):
        grill(tender)
