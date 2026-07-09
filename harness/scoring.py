"""採点方式の振り分け（docs/DESIGN-testplan.md §1）。

すべて静的・決定的。同じ解答は必ず同じ点になる（LLM採点は使わない）。
各スコアラは (passed:int, total:int, 出力全文:str) を返し、runner が success 判定に使う。
ui-static は Playwright 実行環境が要るため別ランナー扱い（ここでは未対応を明示）。
"""
import json
import os
import re
import shutil
import subprocess
import sys

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERROR = re.compile(r"(\d+) error")


def score(task, cwd: str):
    """task.scoring に応じて採点する。戻り値 (passed, total, log_text)。"""
    method = getattr(task, "scoring", "pytest")
    if method == "pytest":
        return score_pytest(task, cwd)
    if method == "report-match":
        return score_report_match(task, cwd)
    if method == "manifest-recall":
        return score_manifest_recall(task, cwd)
    if method == "ui-static":
        return 0, 0, "ui-static は専用ランナー（tasks_ui/）で採点する。通常ベンチ非対応。"
    return 0, 0, f"unknown scoring: {method}"


# ---- pytest: 隠しテストの通過数 --------------------------------------------

def score_pytest(task, cwd: str):
    hidden = os.path.join(task.dir, "tests")
    if not os.path.isdir(hidden):
        return 0, 0, "(tests/ がありません)"
    dest = os.path.join(cwd, "_hidden_tests")
    shutil.copytree(hidden, dest, dirs_exist_ok=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "_hidden_tests", "-q"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    out = (proc.stdout or "") + (proc.stderr or "")
    passed = int(m.group(1)) if (m := _PASSED.search(out)) else 0
    failed = int(m.group(1)) if (m := _FAILED.search(out)) else 0
    errors = int(m.group(1)) if (m := _ERROR.search(out)) else 0
    total = passed + failed + errors
    if total == 0 and proc.returncode != 0:
        total = 1  # 収集エラー等 → 0/1 で失敗扱い
    return passed, total, out


# ---- report-match: 解答ファイルをチェックリストで照合 -----------------------
# tests/checks.json 形式:
#   {"answer_file": "ANSWER.md",
#    "checks": [{"desc": "...", "any": ["regex1","regex2"]}, {"desc": "...", "all": [...]}]}
#   各 check は any(いずれか一致=OK) か all(全一致=OK)。大文字小文字無視。

def _load_checks(task):
    path = os.path.join(task.dir, "tests", "checks.json")
    with open(path) as f:
        return json.load(f)


def _read_answer(cwd: str, name: str):
    path = os.path.join(cwd, name)
    if not os.path.isfile(path):
        return None
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def _check_hit(text: str, check: dict) -> bool:
    pats_any = check.get("any", [])
    pats_all = check.get("all", [])
    if pats_any and not any(re.search(p, text, re.IGNORECASE) for p in pats_any):
        return False
    if pats_all and not all(re.search(p, text, re.IGNORECASE) for p in pats_all):
        return False
    return bool(pats_any or pats_all)


def score_report_match(task, cwd: str):
    spec = _load_checks(task)
    answer_name = spec.get("answer_file") or task.answer_file or "ANSWER.md"
    text = _read_answer(cwd, answer_name)
    if text is None:
        return 0, len(spec["checks"]), f"{answer_name} が作成されていない"
    lines, passed = [], 0
    for c in spec["checks"]:
        ok = _check_hit(text, c)
        passed += ok
        lines.append(f"[{'OK' if ok else '--'}] {c.get('desc', '')}")
    return passed, len(spec["checks"]), "\n".join(lines)


# ---- manifest-recall: 仕込みリストとの照合で発見数を数える ------------------
# tests/manifest.json 形式:
#   {"answer_file": "BUGS.md",
#    "planted": [{"id":"b1","file":"cart.py","symbol":"total","lines":[10,14],
#                 "type_keywords":["off.?by.?one","オフバイワン"]}]}
# 判定: file言及 かつ（symbol言及 または lines範囲内の行番号言及）で発見1件。

_LINE_NUM = re.compile(r"(?:行|line|:)\s*(\d+)", re.IGNORECASE)


def score_manifest_recall(task, cwd: str):
    with open(os.path.join(task.dir, "tests", "manifest.json")) as f:
        spec = json.load(f)
    answer_name = spec.get("answer_file") or task.answer_file or "BUGS.md"
    text = _read_answer(cwd, answer_name)
    planted = spec["planted"]
    if text is None:
        return 0, len(planted), f"{answer_name} が作成されていない"

    low = text.lower()
    mentioned_lines = {int(n) for n in _LINE_NUM.findall(text)}
    lines, found = [], 0
    for p in planted:
        file_hit = os.path.basename(p["file"]).lower() in low
        sym_hit = p.get("symbol", "").lower() in low if p.get("symbol") else False
        line_hit = any(lo <= n <= hi for n in mentioned_lines
                       for lo, hi in [p.get("lines", [0, -1])])
        hit = file_hit and (sym_hit or line_hit)
        type_hit = hit and any(re.search(k, text, re.IGNORECASE)
                               for k in p.get("type_keywords", []))
        found += hit
        lines.append(f"[{'FOUND' if hit else '-----'}]"
                     f"{'(type✓)' if type_hit else '       '} {p['id']}: {p['file']}")
    lines.append(f"recall {found}/{len(planted)}")
    return found, len(planted), "\n".join(lines)
