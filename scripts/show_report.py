#!/usr/bin/env python3
"""runs/runs.jsonl を集計して arm 別の比較テーブル（+オラクル regret）を表示する。"""
from harness.report import aggregate, format_table, load, oracle_regret


def main():
    rows = load()
    if not rows:
        print("まだ結果がありません。まず: python -m scripts.run_bench --arms mock")
        return
    print(format_table(aggregate(rows)))

    reg = oracle_regret(rows)
    if reg:
        print(f"\nオラクル regret（同一 task×rep を複数armで回した {reg['pairs']} 組が対象）:")
        print(f"  router 成功率 {reg['router_success_rate']:.0%}"
              f" / オラクル {reg['oracle_success_rate']:.0%}"
              f" → regret {reg['regret']:.0%}（0%に近いほどルーターは神様に近い）")


if __name__ == "__main__":
    main()
