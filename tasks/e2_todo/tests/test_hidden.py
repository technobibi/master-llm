import os
import tempfile
from todo import TodoList


def _tmp():
    fd, p = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    return p


def test_save_load_roundtrip():
    t = TodoList()
    t.add('a')
    t.add('b')
    p = _tmp()
    t.save(p)
    t2 = TodoList()
    t2.load(p)
    assert t2.list_tasks() == ['a', 'b']


def test_load_missing_file_keeps_empty():
    t = TodoList()
    t.load('/no/such/file.json')
    assert t.list_tasks() == []


def test_add_unchanged():
    t = TodoList()
    t.add('x')
    assert t.list_tasks() == ['x']


def test_save_creates_file():
    t = TodoList()
    t.add('z')
    p = _tmp()
    t.save(p)
    assert os.path.getsize(p) > 0


def test_empty_roundtrip():
    t = TodoList()
    p = _tmp()
    t.save(p)
    t2 = TodoList()
    t2.load(p)
    assert t2.list_tasks() == []
