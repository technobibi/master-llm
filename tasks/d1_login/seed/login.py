import sqlite3

API_KEY = "demo-not-a-real-secret-000000"   # vuln2: 鍵のハードコード（ダミー値）


def find_user(db, username):
    q = f"SELECT * FROM users WHERE name = '{username}'"   # vuln1: SQLインジェクション
    return db.execute(q).fetchone()
