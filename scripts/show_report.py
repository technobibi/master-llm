#!/usr/bin/env python3
"""runs/runs.jsonl を集計して arm 別の比較テーブルを表示する。"""
from harness.report import aggregate, format_table, load


def main():
    rows = load()
    if not rows:
        print("まだ結果がありません。まず: python -m scripts.run_bench --arms mock")
        return
    print(format_table(aggregate(rows)))


if __name__ == "__main__":
    main()
