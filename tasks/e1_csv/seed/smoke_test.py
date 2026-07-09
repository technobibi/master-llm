from agg import group_sum


def test_smoke():
    rows = [{'cat': 'a', 'n': 1}, {'cat': 'a', 'n': 3}]
    assert group_sum(rows, 'cat', 'n') == {'a': 4}
