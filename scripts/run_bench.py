#!/usr/bin/env python3
"""ベンチ実行：全タスク × 選択した arm × N反復 を回す。
ログ（runs/calls/router + artifacts）は runner が実行のたびに追記する。

例:
  python -m scripts.run_bench --arms mock
  python -m scripts.run_bench --arms cloud_only,router --repeats 3
  python -m scripts.run_bench --arms router --task he_000
"""
import argparse

from harness import config
from harness.arms import ARMS
from harness.runner import run_task
from tasks.registry import load_tasks


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arms", default="mock",
                    help="カンマ区切りの arm 名: " + ", ".join(ARMS))
    ap.add_argument("--repeats", type=int, default=config.DEFAULT_REPEATS)
    ap.add_argument("--task", default=None, help="この task id だけ実行")
    args = ap.parse_args()

    arms = [a.strip() for a in args.arms.split(",") if a.strip()]
    for a in arms:
        if a not in ARMS:
            raise SystemExit(f"unknown arm: {a}  (使えるのは: {', '.join(ARMS)})")

    tasks = load_tasks()
    if args.task:
        tasks = [t for t in tasks if t.id == args.task]
    if not tasks:
        raise SystemExit("タスクが見つかりません（tasks/ を確認）")

    for task in tasks:
        for arm in arms:
            for rep in range(args.repeats):
                res = run_task(task, arm, rep)
                flag = "ok  " if res.success else "FAIL"
                cap = f" (cap:{res.cap_reason})" if res.hit_cap else ""
                print(f"[{flag}] {task.id:<12} {arm:<11} rep{rep} "
                      f"tests {res.tests_passed}/{res.tests_total} "
                      f"$eq{res.api_equiv_usd:.4f} {res.wall_s:6.1f}s "
                      f"in={res.in_tok} out={res.out_tok} calls={res.n_calls}{cap}")


if __name__ == "__main__":
    main()
