import hashlib
import os

BASE = "/srv/files"


def serve(path):
    full = os.path.join(BASE, path)        # vuln1: パストラバーサル（../ 未検査）
    return open(full).read()


def admin_delete(path, user):
    os.remove(os.path.join(BASE, path))    # vuln2: 認可チェック無し
    return True


def hash_pw(pw):
    return hashlib.md5(pw.encode()).hexdigest()   # vuln3: 弱いハッシュ MD5
