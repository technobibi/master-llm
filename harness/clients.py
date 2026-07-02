"""モデル呼び出しの境界。ここでトークン・コスト・時間を計測する。"""
import json
import os
import subprocess
import time

import requests

from harness import config
from harness.models import CallResult


def _price(model: str, in_tok: int, out_tok: int) -> float:
    p = config.PRICING.get(model)
    if not p:
        return 0.0
    return (in_tok * p["in"] + out_tok * p["out"]) / 1_000_000


def call_local(prompt: str) -> CallResult:
    """LM Studio の /v1 に対する単発チャット補完。応答テキストと usage を返す。"""
    t0 = time.perf_counter()
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
    wall = time.perf_counter() - t0
    usage = data.get("usage", {}) or {}
    return CallResult(
        model="local",
        in_tok=usage.get("prompt_tokens", 0),
        out_tok=usage.get("completion_tokens", 0),
        cost_usd=0.0,  # ローカルは無料
        wall_s=wall,
        turns=1,
        text=data["choices"][0]["message"]["content"],
    )


def call_cloud(prompt: str, cwd: str, max_turns: int) -> CallResult:
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

    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        # CLI 失敗 / 未認証など。空の失敗コールとして返す。
        return CallResult("cloud", 0, 0, 0.0, wall, 1, (proc.stderr or "")[:500])

    usage = data.get("usage", {}) or {}
    in_tok = usage.get("input_tokens", 0)
    out_tok = usage.get("output_tokens", 0)
    cost = data.get("total_cost_usd")
    if cost is None:
        cost = _price("cloud", in_tok, out_tok)
    return CallResult(
        model="cloud",
        in_tok=in_tok,
        out_tok=out_tok,
        cost_usd=cost,
        wall_s=wall,
        turns=data.get("num_turns", 1),
        text=data.get("result", ""),
    )
