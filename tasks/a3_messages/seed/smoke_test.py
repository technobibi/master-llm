from messages import msg


def test_smoke():
    assert msg('not_found') == '見つかりません'
