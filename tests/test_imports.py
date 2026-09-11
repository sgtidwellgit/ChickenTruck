"""Import-level tests for the ChickenTruck package stub."""

import chickentruck


def test_version_is_exposed():
    assert isinstance(chickentruck.__version__, str)
    assert chickentruck.__version__


def test_public_api_is_importable():
    for name in chickentruck.__all__:
        assert hasattr(chickentruck, name)
