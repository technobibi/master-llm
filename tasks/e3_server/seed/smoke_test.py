from store import ItemStore


def test_smoke():
    s = ItemStore()
    i = s.add('a', 100)
    assert i == 1
    assert s.get(1)['name'] == 'a'
