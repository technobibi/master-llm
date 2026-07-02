"""ルーティング判定：ローカルで足りるか、クラウドへ上げるか。

最初はキーワードの雑なルールで十分。runs.jsonl のログが貯まったら、
「ローカルで成功したか」を予測する小さな分類器に差し替えていく（=独自オーケストレータの学習）。
迷ったらクラウド寄せ（安全側）にするのが原則。
"""

SIMPLE_HINTS = (
    "どこ", "where", "翻訳", "translate", "ログ", "log",
    "rename", "typo", "format", "整形", "一覧", "list",
)


def is_simple(prompt: str) -> bool:
    """短くて簡単そうな手掛かりを含むときだけ True。確信が持てなければ False。"""
    p = prompt.lower()
    if len(prompt) < 120 and any(h.lower() in p for h in SIMPLE_HINTS):
        return True
    return False
