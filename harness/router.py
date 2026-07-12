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


def _seed_scale(task):
    """seed/ の規模（ファイル数・総バイト数）。埋め込みが捉えられない『規模』軸を明示的に持つ。
    埋め込みは意味は捉えるが「5ファイル vs 50ファイル」を区別できないため、規模は別特徴で。
    （docs/DESIGN-agent.md / ルーティング設計メモ参照）"""
    import os
    seed = os.path.join(task.dir, "seed")
    n_files, total_bytes = 0, 0
    if os.path.isdir(seed):
        for root, _, files in os.walk(seed):
            for fn in files:
                if fn.endswith(".pyc"):
                    continue
                n_files += 1
                try:
                    total_bytes += os.path.getsize(os.path.join(root, fn))
                except OSError:
                    pass
    return n_files, total_bytes


def extract_features(prompt: str, task=None) -> dict:
    """判定に使う特徴量。将来の学習器も同じ入り口を使う（原文は artifacts にあるので追加も可能）。

    2系統を持つ:
      - 意味系: prompt の内容（将来ここに埋め込みベクトルを足す）
      - 規模系: ファイル数・バイト数など（埋め込みでは測れない大きさの軸）
    """
    p = prompt.lower()
    hit = next((h for h in SIMPLE_HINTS if h.lower() in p), None)
    feats = {
        # --- 意味系 ---
        "prompt_len": len(prompt),
        "n_words": len(prompt.split()),
        "prompt_lang": "ja" if any(ord(c) >= 0x3000 for c in prompt) else "en",
        "hint_hit": hit,
    }
    if task is not None:
        feats["category"] = task.category
        feats["tier"] = getattr(task, "tier", "low")
        feats["scoring"] = getattr(task, "scoring", "pytest")
        feats["modality"] = getattr(task, "modality", "text")
        # --- 規模系（ローカルで収まる大きさかの判定に使う。埋め込みとは別軸）---
        n_files, seed_bytes = _seed_scale(task)
        feats["n_seed_files"] = n_files
        feats["seed_bytes"] = seed_bytes
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
