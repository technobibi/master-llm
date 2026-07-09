"""ルーティング判定：ローカルで足りるか、クラウドへ上げるか。

今は rule-v1（キーワード + 長さの手書きルール）。判定のたびに特徴量ごと
runs/router.jsonl に記録されるので、ペアデータが貯まったら
「ローカルで成功するか」を予測する分類器に差し替える（→ RESEARCH-BACKLOG R2。
差し替えは decide() の中身を置き換えるだけ。ここは所有者が自分で書く領域）。
迷ったらクラウド寄せ（安全側）が原則。
"""
from harness.models import RouterDecision

ROUTER_VERSION = "rule-v1"

SIMPLE_HINTS = (
    "どこ", "where", "翻訳", "translate", "ログ", "log",
    "rename", "typo", "format", "整形", "一覧", "list",
)


def extract_features(prompt: str, task=None) -> dict:
    """判定に使う特徴量。将来の学習器も同じ入り口を使う（原文は artifacts にあるので追加も可能）。"""
    p = prompt.lower()
    hit = next((h for h in SIMPLE_HINTS if h.lower() in p), None)
    feats = {
        "prompt_len": len(prompt),
        "n_words": len(prompt.split()),
        "prompt_lang": "ja" if any(ord(c) >= 0x3000 for c in prompt) else "en",
        "hint_hit": hit,
    }
    if task is not None:
        feats["category"] = task.category
    return feats


def decide(prompt: str, task=None) -> RouterDecision:
    """rule-v1: 短くて簡単キーワードを含むときだけローカル。確信が持てなければクラウド。"""
    feats = extract_features(prompt, task)
    simple = feats["prompt_len"] < 120 and feats["hint_hit"] is not None
    return RouterDecision(
        decision="local" if simple else "cloud",
        features=feats,
        router_version=ROUTER_VERSION,
    )


def is_simple(prompt: str) -> bool:
    """旧API互換。新規コードは decide() を使う。"""
    return decide(prompt).decision == "local"
