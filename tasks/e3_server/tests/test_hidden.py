import pytest
from store import ItemStore


def test_add_returns_incrementing_ids():
    s = ItemStore()
    assert s.add('a', 100) == 1
    assert s.add('b', 200) == 2


def test_get_returns_item():
    s = ItemStore()
    i = s.add('a', 100)
    assert s.get(i) == {'id': 1, 'name': 'a', 'price': 100}


def test_get_missing_raises():
    s = ItemStore()
    with pytest.raises(KeyError):
        s.get(99)


def test_empty_name_raises():
    s = ItemStore()
    with pytest.raises(ValueError):
        s.add('', 100)


def test_negative_price_raises():
    s = ItemStore()
    with pytest.raises(ValueError):
        s.add('a', -1)


def test_filter_by_max_price_sorted():
    s = ItemStore()
    s.add('a', 300)
    s.add('b', 100)
    s.add('c', 200)
    out = s.filter_by_max_price(200)
    assert [x['name'] for x in out] == ['b', 'c']
