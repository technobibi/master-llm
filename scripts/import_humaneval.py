#!/usr/bin/env python3
"""HumanEval（公開のコード実装ベンチ・164問）を、このハーネスのタスク形式に取り込む。

  python -m scripts.import_humaneval            # 既定20問を tasks_humaneval/ に生成
  python -m scripts.import_humaneval --limit 164  # 全問
  python -m scripts.import_humaneval --out tasks_humaneval --limit 50

方針（docs/DESIGN-router.md §7）:
- 生成物 tasks_humaneval/ は gitignore（公開データの派生・リポ肥大回避）。
  コミットするのはこのインポーターだけ。各ユーザーが実行して手元に生成する。
- ★汚染注意: HumanEval は有名で、モデルの訓練データに答えが入っている疑いがある。
  「ローカルが解けた」が実力か暗記か切り分けにくい。複数ベンチを混ぜて使うこと。

変換:
  HumanEval.prompt（関数スタブ+docstring）→ seed/solution.py（未完成の初期状態）
  HumanEval.test（check関数）           → tests/test_hidden.py（隠し採点）
  HumanEval.prompt + canonical_solution → mock_solution.txt（配管確認用の模範解）
"""
import argparse
import gzip
import json
import os
import urllib.request

URL = "https://raw.githubusercontent.com/openai/human-eval/master/data/HumanEval.jsonl.gz"
CACHE = "/tmp/HumanEval.jsonl.gz"


def _load():
    if not os.path.isfile(CACHE):
        urllib.request.urlretrieve(URL, CACHE)
    with gzip.open(CACHE) as f:
        return [json.loads(l) for l in f if l.strip()]


def _tier(solution: str) -> str:
    """模範解の行数で難易度を粗く推定（規模特徴の spread のため）。"""
    n = len([l for l in solution.splitlines() if l.strip()])
    return "low" if n <= 3 else "high" if n >= 12 else "mid"


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _yaml_str(s: str) -> str:
    """prompt を YAML ブロックスカラーに（各行2スペースインデント）。"""
    return "".join(f"  {line}\n" for line in s.splitlines())


def convert(rec, out_root):
    num = rec["task_id"].split("/")[1]
    tid = f"he_{int(num):03d}"
    entry = rec["entry_point"]
    tier = _tier(rec["canonical_solution"])
    d = os.path.join(out_root, tid)

    prompt = (f"solution.py の関数 {entry} を、docstring の仕様どおりに実装してください。\n"
              f"シグネチャは変えず、必要な import も含めてファイル全体を出力すること。")
    _write(os.path.join(d, "task.yaml"),
           f"id: {tid}\ncategory: humaneval\ntier: {tier}\nscoring: pytest\n"
           f"target_file: solution.py\nprompt: |\n{_yaml_str(prompt)}"
           f"budget:\n  max_cost_usd: 2.00\n  max_turns: 20\n  max_wall_s: 400\n")

    # seed: 関数スタブ+docstring（docstringだけを本体に持つ有効なPython）
    _write(os.path.join(d, "seed", "solution.py"), rec["prompt"])

    # 隠しテスト: check(candidate) を定義し、完成した関数に対して回す。
    # 一部の check は模範解のヘルパー関数（例: poly）を名前で直接参照するため、
    # solution の全名前を取り込む（HumanEval 公式評価と同じ「同一名前空間で実行」方式）。
    # HumanEval の関数名に test_* は無いので pytest の誤収集は起きない。
    test_body = (f"from solution import *\n\n"
                 f"{rec['test']}\n\n"
                 f"def test_humaneval():\n    check({entry})\n")
    _write(os.path.join(d, "tests", "test_hidden.py"), test_body)

    # 模範解（配管確認用）: prompt(スタブ) + canonical_solution(本体) = 完全な関数
    _write(os.path.join(d, "mock_solution.txt"), rec["prompt"] + rec["canonical_solution"])
    return tid


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=20, help="取り込む問題数（最大164）")
    ap.add_argument("--out", default="tasks_humaneval", help="生成先ディレクトリ")
    args = ap.parse_args()

    rows = _load()[: args.limit]
    ids = [convert(r, args.out) for r in rows]
    print(f"HumanEval から {len(ids)} 問を {args.out}/ に生成: {ids[0]} 〜 {ids[-1]}")
    print("★汚染注意: HumanEval は訓練データに含まれる疑いあり。実力の過大評価に注意し、"
          "複数ベンチ（MBPP/LiveCodeBench 等）を混ぜて使うこと。")
    print(f"確認: python -m scripts.run_bench --arms mock --task {ids[0]}")


if __name__ == "__main__":
    main()
