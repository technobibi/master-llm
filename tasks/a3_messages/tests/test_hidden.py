from messages import msg


def test_not_found():
    assert msg("not_found") == "見つかりません"


def test_forbidden():
    assert msg("forbidden") == "権限がありません"


def test_timeout():
    assert msg("timeout") == "タイムアウトしました"
