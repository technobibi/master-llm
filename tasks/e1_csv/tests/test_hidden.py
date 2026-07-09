from agg import group_sum

ROWS = [
    {"cat": "a", "n": 1},
    {"cat": "b", "n": 2},
    {"cat": "a", "n": 3},
]


def test_basic():
    assert group_sum(ROWS, "cat", "n") == {"a": 4, "b": 2}


def test_single_group():
    assert group_sum([{"k": "x", "v": 5}], "k", "v") == {"x": 5}


def test_empty():
    assert group_sum([], "cat", "n") == {}


def test_missing_key_raises():
    import pytest
    with pytest.raises(KeyError):
        group_sum(ROWS, "nope", "n")


def test_missing_value_raises():
    import pytest
    with pytest.raises(KeyError):
        group_sum(ROWS, "cat", "nope")
