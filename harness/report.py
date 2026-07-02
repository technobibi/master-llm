"""runs.jsonl を arm 別に集計して表にする。3軸をまとめて見るための最小集計。"""
import json
from collections import defaultdict

from harness import config


def load(path: str = None):
    path = path or config.RUNS_FILE
    rows = []
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    except FileNotFoundError:
        pass
    return rows


def aggregate(rows):
    by_arm = defaultdict(list)
    for r in rows:
        by_arm[r["arm"]].append(r)

    out = {}
    for arm, rs in by_arm.items():
        n = len(rs) or 1
        out[arm] = {
            "runs": len(rs),
            "success_rate": sum(1 for r in rs if r["success"]) / n,
            "avg_cost_usd": sum(r["cost_usd"] for r in rs) / n,
            "avg_wall_s": sum(r["wall_s"] for r in rs) / n,
            "avg_out_tok": sum(r["out_tok"] for r in rs) / n,
        }
    return out


def format_table(agg) -> str:
    header = (f"{'arm':<12}{'runs':>6}{'success':>10}"
              f"{'$avg':>10}{'sec avg':>10}{'out_tok':>10}")
    lines = [header, "-" * len(header)]
    for arm, m in sorted(agg.items()):
        lines.append(
            f"{arm:<12}{m['runs']:>6}{m['success_rate'] * 100:>9.0f}%"
            f"{m['avg_cost_usd']:>10.4f}{m['avg_wall_s']:>10.1f}{m['avg_out_tok']:>10.0f}"
        )
    return "\n".join(lines)
