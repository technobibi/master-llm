import calc as m


def test_new_name_works():
    assert m.calculate_total([1, 2, 3]) == 6


def test_old_name_gone():
    assert not hasattr(m, "calc")


def test_empty():
    assert m.calculate_total([]) == 0
