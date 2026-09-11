"""Tests for chickentruck.stock."""

from chickentruck.stock import ChickenStock


def test_stock_starts_empty():
    stock = ChickenStock()

    assert len(stock) == 0
    assert stock.all() == []


def test_stock_add_appends_items_in_order():
    stock = ChickenStock()
    stock.add("fact-1")
    stock.add("fact-2")

    assert len(stock) == 2
    assert stock.all() == ["fact-1", "fact-2"]
