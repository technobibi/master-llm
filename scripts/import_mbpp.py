#!/usr/bin/env python3
"""MBPP（sanitized・427問）を、このハーネスのタスク形式に取り込む。

  python -m scripts.import_mbpp              # 既定30問を tasks_mbpp/ に生成
  python -m scripts.import_mbpp --limit 427  # 全問

HumanEval との違い（→ import_humaneval.py と対比）:
- MBPP の prompt は**自然言語の指示**（「〜する関数を書け」）で、関数スタブではない。
- 関数名は模範解 `code` から取り出す（テストがその名前を呼ぶため、名前を外すと採点不能）。

変換:
  code から関数シグネチャを抽出 → seed/solution.py（NL指示を docstring に添えたスタブ）
  test_imports + test_list                → tests/test_hidden.py（隠し採点）
  code（模範解）                          → mock_solution.txt（配管確認用）

方針・注意は import_humaneval と同じ（生成物は gitignore、汚染に注意し複数ベンチを混ぜる）。
"""
import argparse
import ast
import json
import os
import urllib.request

URL = "https://raw.githubusercontent.com/google-research/google-research/master/mbpp/sanitized-mbpp.json"
CACHE = "/tmp/mbpp.json"


def _load():
    if not os.path.isfile(CACHE):
        urllib.request.urlretrieve(URL, CACHE)
    return json.load(open(CACHE))


def _entry_and_sig(code, test_blob):
    """模範解から、テストが呼ぶ関数名とそのシグネチャ行を返す。失敗なら (None, None)。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return None, None
    defs = [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]
    if not defs:
        return None, None
    entry = next((d for d in defs if d in test_blob), defs[-1])
    sig = next((ln.strip() for ln in code.splitlines()
                if ln.strip().startswith(f"def {entry}")), None)
    return (entry, sig) if sig else (None, None)


def _write(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)


def _yaml_str(s):
    return "".join(f"  {line}\n" for line in s.splitlines())


def convert(rec, out_root):
    test_list = rec["test_list"]
    entry, sig = _entry_and_sig(rec["code"], " ".join(test_list))
    if not entry:
        return None
    tid = f"mbpp_{int(rec['task_id']):03d}"
    d = os.path.join(out_root, tid)
    desc = rec["prompt"].strip()

    prompt = (f"solution.py の関数 {entry} を実装してください。仕様:\n{desc}\n"
              f"シグネチャは変えず、必要な import も含めてファイル全体を出力すること。")
    _write(os.path.join(d, "task.yaml"),
           f"id: {tid}\ncategory: mbpp\ntier: mid\nscoring: pytest\n"
           f"target_file: solution.py\nprompt: |\n{_yaml_str(prompt)}"
           f"budget:\n  max_cost_usd: 2.00\n  max_turns: 20\n  max_wall_s: 400\n")

    # seed: シグネチャ + NL指示(docstring) + pass（有効なPython）
    doc = desc.replace('"""', "'''")
    _write(os.path.join(d, "seed", "solution.py"), f'{sig}\n    """{doc}"""\n    pass\n')

    # 隠しテスト: test_imports + 各assertを1つのpytest関数にまとめる。
    # solution の import は test 関数の内側に置く（関数名が test_* だと pytest が
    # トップレベルの import を誤ってテストとして収集してしまうため）。
    imports = "\n".join(rec.get("test_imports", []) or [])
    asserts = "\n".join("    " + a for a in test_list)
    _write(os.path.join(d, "tests", "test_hidden.py"),
           f"{imports}\n\n\ndef test_mbpp():\n    from solution import {entry}\n{asserts}\n")

    _write(os.path.join(d, "mock_solution.txt"), rec["code"])
    return tid


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--limit", type=int, default=30, help="取り込む問題数（最大427）")
    ap.add_argument("--out", default="tasks_mbpp", help="生成先ディレクトリ")
    args = ap.parse_args()

    rows = _load()[: args.limit]
    ids = [convert(r, args.out) for r in rows]
    ok = [i for i in ids if i]
    print(f"MBPP から {len(ok)} 問を {args.out}/ に生成（解析不能で {len(ids) - len(ok)} 問スキップ）")
    print("★汚染注意: MBPP も訓練データに含まれる疑いあり。複数ベンチを混ぜて使うこと。")
    if ok:
        print(f"確認: python -m scripts.run_bench --arms mock --task {ok[0]}")


if __name__ == "__main__":
    main()
