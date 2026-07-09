from logfmt import format_log


def test_info():
    r = {'level': 'info', 'ts': '2026-01-01T00:00:00', 'message': 'hi'}
    assert format_log(r) == '[ INFO] 2026-01-01T00:00:00 hi'


def test_error():
    r = {'level': 'error', 'ts': '2026-01-01T00:00:00', 'message': 'boom'}
    assert format_log(r) == '[ERROR] 2026-01-01T00:00:00 boom'


def test_warn_padding():
    r = {'level': 'warn', 'ts': 'T', 'message': 'm'}
    assert format_log(r) == '[ WARN] T m'


def test_upcase():
    r = {'level': 'debug', 'ts': 'T', 'message': 'm'}
    assert format_log(r) == '[DEBUG] T m'
