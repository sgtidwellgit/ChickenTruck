"""Import-level tests for the ChickenTruck package."""

import re

import chickentruck


def test_version_is_date_based():
    assert re.fullmatch(r"\d{4}\.\d{1,2}\.\d{1,2}(\.\d+)?", chickentruck.__version__)


def test_public_api_is_importable():
    for name in chickentruck.__all__:
        assert hasattr(chickentruck, name)
