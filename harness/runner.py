"""1タスク実行の司令塔：まっさら作業コピー → arm 実行 → 隠しテスト検証 → ログ。"""
import json
import os
import shutil
import subprocess
import sys
import time
from dataclasses import asdict

from harness import config
from harness.arms import ARMS
from harness.models import RunResult
from harness.workspace import cleanup, fresh_workspace


def verify(task, cwd: str) -> bool:
    """task の「隠しテスト」を作業コピーに対して実行する。

    テストはエージェントには渡さず、実行が終わった今この瞬間だけコピーして回す。
    （python -m pytest は cwd を sys.path に載せるので target ファイルを import できる）
    """
    hidden = os.path.join(task.dir, "tests")
    if not os.path.isdir(hidden):
        return False
    dest = os.path.join(cwd, "_hidden_tests")
    shutil.copytree(hidden, dest, dirs_exist_ok=True)

    env = dict(os.environ)
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "_hidden_tests", "-q"],
        cwd=cwd, env=env, capture_output=True, text=True,
    )
    return proc.returncode == 0


def run_task(task, arm_name: str, rep: int) -> RunResult:
    """1タスク × 1arm × 1反復 を実行して RunResult を返す。時間は arm 全体を囲む。"""
    arm = ARMS[arm_name]
    cwd = fresh_workspace(task)
    try:
        t0 = time.perf_counter()
        calls, hit_cap = arm(task, cwd)
        wall = time.perf_counter() - t0
        ok = verify(task, cwd) and not hit_cap
        return RunResult(
            task=task.id, category=task.category, arm=arm_name, rep=rep,
            success=ok,
            in_tok=sum(c.in_tok for c in calls),
            out_tok=sum(c.out_tok for c in calls),
            cost_usd=round(sum(c.cost_usd for c in calls), 6),
            wall_s=round(wall, 3),
            turns=sum(c.turns for c in calls),
            hit_cap=hit_cap,
        )
    finally:
        cleanup(cwd)


def append_result(result: RunResult, path: str = None) -> None:
    path = path or config.RUNS_FILE
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
