"""runs.jsonl を arm 別に集計する。

- 平均ではなく中央値（LLMは外れ値が出るため。docs/STUDY-2 §2）
- v1 の古い行（schema キーなし）も読み替えて混ぜる
- router がある場合はオラクル regret（最良armとの差）も出す
"""
import json
from collections import defaultdict
from statistics import median

from harness import config


def load(path: str = None):
    path = path or config.RUNS_FILE
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(_upgrade(json.loads(line)))
    except FileNotFoundError:
        pass
    return rows


def _upgrade(r: dict) -> dict:
    """v1 行を v2 相当に読み替える（元の行は書き換えない。append-only 原則）。"""
    if r.get("schema", 1) >= 2:
        return r
    r = dict(r)
    # v1 の cost_usd は claude -p の報告額 = API換算値だったので api_equiv に移す
    r["api_equiv_usd"] = r.get("cost_usd", 0.0)
    r["cost_usd"] = 0.0
    r["cloud_calls"] = 1 if r["arm"] in ("cloud_only", "router") else 0
    r["cloud_out_tok"] = 0
    r["tests_passed"] = 1 if r["success"] else 0
    r["tests_total"] = 1
    r["n_calls"] = 1
    return r


def _group_label(r: dict) -> str:
    """集計キー。器（agent_version）やモデル（cloud_model）が変われば能力も別物なので、
    同じ arm でも別の行として集計する（v2/v3 や cli-default/opus を混ぜない）。"""
    arm, env = r["arm"], r.get("env", {})
    if arm == "local_agent" and env.get("agent_version"):
        return f"{arm}[{env['agent_version']}]"
    if arm in ("cloud_only", "router") and env.get("cloud_model"):
        return f"{arm}[{env['cloud_model']}]"
    return arm


def aggregate(rows):
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[_group_label(r)].append(r)

    out = {}
    for arm, rs in by_arm.items():
        n = len(rs) or 1
        wall = [r["wall_s"] for r in rs]
        out[arm] = {
            "runs": len(rs),
            "success_rate": sum(1 for r in rs if r["success"]) / n,
            "tests_rate": (sum(r["tests_passed"] for r in rs)
                           / max(sum(r["tests_total"] for r in rs), 1)),
            "med_api_equiv_usd": median(r["api_equiv_usd"] for r in rs),
            "med_wall_s": median(wall),
            "min_wall_s": min(wall),
            "max_wall_s": max(wall),
            "med_out_tok": median(r["out_tok"] for r in rs),
            "cloud_calls": sum(r["cloud_calls"] for r in rs),
            "cloud_out_tok": sum(r["cloud_out_tok"] for r in rs),
        }
    return out


def oracle_regret(rows):
    """router の判断は「全armの結果を知る神様（オラクル）」に比べ何を損したか。

    同じ task×rep を複数armで回した組だけが対象。router 行が無ければ None。
    最良の定義は「成功 > 時間 > 枠消費」の辞書順（dataset の oracle_arm と共通規則）。
    """
    by_key = defaultdict(dict)
    for r in rows:
        by_key[(r["task"], r["rep"])][r["arm"]] = r

    pairs = 0
    router_success = 0
    oracle_success = 0
    for group in by_key.values():
        if "router" not in group or len(group) < 2:
            continue
        pairs += 1
        router_row = group["router"]
        best = min(group.values(), key=lambda r: (not r["success"], r["wall_s"], r["cloud_out_tok"]))
        router_success += router_row["success"]
        oracle_success += best["success"]
    if pairs == 0:
        return None
    return {
        "pairs": pairs,
        "router_success_rate": router_success / pairs,
        "oracle_success_rate": oracle_success / pairs,
        "regret": (oracle_success - router_success) / pairs,
    }


def format_table(agg) -> str:
    w = max([len(k) for k in agg] + [12]) + 2
    header = (f"{'arm':<{w}}{'runs':>6}{'success':>9}{'tests':>7}"
              f"{'$eq(med)':>10}{'sec(med)':>10}{'out_tok':>9}{'cloud':>7}")
    lines = [header, "-" * len(header)]
    for arm, m in sorted(agg.items()):
        lines.append(
            f"{arm:<{w}}{m['runs']:>6}{m['success_rate'] * 100:>8.0f}%"
            f"{m['tests_rate'] * 100:>6.0f}%"
            f"{m['med_api_equiv_usd']:>10.4f}{m['med_wall_s']:>10.1f}"
            f"{m['med_out_tok']:>9.0f}{m['cloud_calls']:>7}"
        )
    return "\n".join(lines)
