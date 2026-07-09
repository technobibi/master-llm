from greet import greet


def test_smoke():
    g = greet()
    assert 'Hello' in g and 'World' in g
