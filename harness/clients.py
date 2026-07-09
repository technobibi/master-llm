"""モデル呼び出しの境界。トークン・キャッシュ・コスト・時間はすべてここで計測する。

エラー時も必ず CallResult を返す（error フィールドに記録）。呼び出しの失敗を
握りつぶすと「失敗した run のコスト・時間」がログから消えて集計が歪むため。
"""
import json
import os
import subprocess
import time

import requests

from harness import config
from harness.models import CallResult


def _api_equiv(in_tok: int, out_tok: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """API従量課金なら幾らかの換算値。キャッシュ読みは約1/10、書きは約1.25倍。"""
    p = config.PRICING.get("cloud")
    if not p:
        return 0.0
    return (in_tok * p["in"] + out_tok * p["out"]
            + cache_read * p["in"] * 0.10 + cache_write * p["in"] * 1.25) / 1_000_000


def call_local(prompt: str, role: str = "solo") -> CallResult:
    """LM Studio の /v1 に対する単発チャット補完。"""
    t0 = time.perf_counter()
    try:
        resp = requests.post(
            f"{config.LOCAL_BASE_URL}/chat/completions",
            json={
                "model": config.LOCAL_MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.2,
            },
            timeout=600,
        )
        resp.raise_for_status()
        data = resp.json()
    except (requests.RequestException, ValueError) as e:
        return CallResult(provider="local", model=config.LOCAL_MODEL, role=role,
                          wall_s=time.perf_counter() - t0, error=str(e)[:300])

    wall = time.perf_counter() - t0
    usage = data.get("usage", {}) or {}
    out_tok = usage.get("completion_tokens", 0)
    return CallResult(
        provider="local",
        model=config.LOCAL_MODEL,
        role=role,
        in_tok=usage.get("prompt_tokens", 0),
        out_tok=out_tok,
        cost_usd=0.0,          # ローカルは無料（電気代は R7 の研究テーマ）
        api_equiv_usd=0.0,
        wall_s=wall,
        tok_per_s=round(out_tok / wall, 2) if wall > 0 else 0.0,
        turns=1,
        text=data["choices"][0]["message"]["content"],
    )


def call_cloud(prompt: str, cwd: str, max_turns: int, role: str = "solo") -> CallResult:
    """Claude Code CLI をヘッドレスで実行。cwd 内のファイルを自律的に編集する。"""
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)  # ★サブスクトークンを使わせる（従量課金を防ぐ）
    cmd = [
        config.CLAUDE_BIN, "-p", prompt,
        "--output-format", "json",
        "--allowedTools", config.CLOUD_ALLOWED_TOOLS,
        "--max-turns", str(max_turns),
    ]
    if config.CLOUD_MODEL:
        cmd += ["--model", config.CLOUD_MODEL]

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    wall = time.perf_counter() - t0
    model = config.CLOUD_MODEL or "cli-default"

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return CallResult(provider="cloud", model=model, role=role, wall_s=wall,
                          error=(proc.stderr or proc.stdout or "no output")[:500])

    usage = data.get("usage", {}) or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cache_read = usage.get("cache_read_input_tokens", 0)
    cache_write = usage.get("cache_creation_input_tokens", 0)

    # CLI の total_cost_usd は「API換算」。実支払は課金モードで決まる。
    api_equiv = data.get("total_cost_usd")
    if api_equiv is None:
        api_equiv = _api_equiv(in_tok, out_tok, cache_read, cache_write)
    cost = api_equiv if config.CLOUD_BILLING == "api" else 0.0

    return CallResult(
        provider="cloud",
        model=model,
        role=role,
        in_tok=in_tok,
        out_tok=out_tok,
        cache_read_tok=cache_read,
        cache_write_tok=cache_write,
        cost_usd=cost,
        api_equiv_usd=api_equiv,
        wall_s=wall,
        tok_per_s=round(out_tok / wall, 2) if wall > 0 else 0.0,
        turns=data.get("num_turns", 1),
        error="error" if data.get("is_error") else None,
        text=data.get("result", ""),
    )
