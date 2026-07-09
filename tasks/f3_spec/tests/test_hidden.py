import pytest
from validate import validate


def test_ok():
    assert validate('taro', 'a@b.com', 20) == ('taro', 'a@b.com', 20)


def test_empty_name():
    with pytest.raises(ValueError):
        validate('', 'a@b.com', 20)


def test_bad_email():
    with pytest.raises(ValueError):
        validate('taro', 'nope', 20)


def test_age_low():
    with pytest.raises(ValueError):
        validate('taro', 'a@b.com', -1)


def test_age_high():
    with pytest.raises(ValueError):
        validate('taro', 'a@b.com', 200)
