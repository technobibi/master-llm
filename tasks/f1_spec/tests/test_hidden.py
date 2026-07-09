from deadline import mark

TASKS = [
    {'name': 'A', 'due': 1},
    {'name': 'B', 'due': 5},
    {'name': 'C', 'due': None},
]


def test_overdue_marked():
    out = mark(TASKS, today=3)
    assert out[0] == '[期限切れ]A'


def test_future_untouched():
    out = mark(TASKS, today=3)
    assert out[1] == 'B'


def test_none_untouched():
    out = mark(TASKS, today=3)
    assert out[2] == 'C'


def test_all_future():
    out = mark(TASKS, today=0)
    assert out == ['A', 'B', 'C']
