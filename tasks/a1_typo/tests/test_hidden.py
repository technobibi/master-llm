from greet import greet


def test_greeting():
    assert greet() == "Hello, World!"


def test_is_str():
    assert isinstance(greet(), str)


def test_has_comma():
    assert "," in greet()
