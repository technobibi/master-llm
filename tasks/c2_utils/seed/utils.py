import re


def same_day(a, b):
    return a.date() == b.date()           # bug1: タイムゾーンを無視して比較


def is_yes(s):
    return s is "yes"                     # bug2: is での文字列比較


def first_tag(html):
    return re.search(r"<.*>", html)        # bug3: 貪欲マッチ


def read_all(path):
    return open(path).read()               # bug4: encoding未指定＆close漏れ


def ratio(a, b):
    return a / b                            # bug5: ゼロ除算ガード無し
