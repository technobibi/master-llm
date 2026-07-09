import os, tempfile
from todo import TodoList


def test_smoke():
    fd, p = tempfile.mkstemp(suffix='.json')
    os.close(fd)
    t = TodoList()
    t.add('a')
    t.save(p)
    t2 = TodoList()
    t2.load(p)
    assert t2.list_tasks() == ['a']
