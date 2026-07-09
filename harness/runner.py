"""1タスク実行の司令塔：まっさら作業コピー → arm 実行 → 隠しテスト検証
→ artifacts 保存 → 3つのログ（runs / calls / router）へ追記。

ログはすべて append-only。原文（プロンプト・応答・diff・pytest出力）は
runs/artifacts/<run_id>/ に保存し、後から特徴量や分析をやり直せるようにする
（docs/DESIGN-telemetry.md の原則3「生データ > 派生値」）。
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import datetime, timezone

from harness import config, router
from harness.arms import ARMS
from harness.models import RunResult
from harness.workspace import cleanup, fresh_workspace

_PASSED = re.compile(r"(\d+) passed")
_FAILED = re.compile(r"(\d+) failed")
_ERROR = re.compile(r"(\d+) error")


def verify(task, cwd: str):
    """隠しテストを実行し (passed, total, 出力全文) を返す。

    テストはエージェントには渡さず、実行が終わった今この瞬間だけコピーして回す。
    """
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
        total = -1  # 収集エラー等。0/−1 → 失敗扱い
    return passed, max(total, 0), out


def _write_artifact(adir: str, name: str, content: str) -> None:
    with open(os.path.join(adir, name), "w") as f:
        f.write(content or "")


def _save_diff(task, cwd: str, adir: str) -> None:
    """seed → 最終状態の差分。成功解は将来の学習データ（sft）の原料になる。

    絶対パス（ホームパス・tempパス）は a/seed・b/final に置換して残さない。
    """
    seed = os.path.join(task.dir, "seed")
    proc = subprocess.run(
        ["diff", "-ruN", "-x", "_hidden_tests", "-x", "__pycache__", "-x", "*.pyc",
         seed if os.path.isdir(seed) else "/dev/null", cwd],
        capture_output=True, text=True,
    )
    patch = proc.stdout.replace(seed, "a/seed").replace(cwd, "b/final")
    _write_artifact(adir, "diff.patch", patch)


def _append_jsonl(record: dict, path: str) -> None:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def _cap_reason(calls, wall: float, task):
    api_eq = sum(c.api_equiv_usd for c in calls)
    if api_eq > task.budget.max_cost_usd:
        return "cost"
    if wall > task.budget.max_wall_s:
        return "time"
    if sum(c.turns for c in calls) > task.budget.max_turns:
        return "turns"
    return None


def run_task(task, arm_name: str, rep: int) -> RunResult:
    """1タスク × 1arm × 1反復 を実行し、artifacts と3ログに記録して返す。"""
    arm = ARMS[arm_name]
    cwd = fresh_workspace(task)
    now = datetime.now(timezone.utc)
    run_id = f"{now.strftime('%Y%m%dT%H%M%SZ')}_{task.id}_{arm_name}_{rep}"
    adir = os.path.join(config.ARTIFACTS_DIR, run_id)
    os.makedirs(adir, exist_ok=True)
    _write_artifact(adir, "prompt.txt", task.prompt)

    try:
        t0 = time.perf_counter()
        calls, router_dec = arm(task, cwd)
        wall = time.perf_counter() - t0

        for i, c in enumerate(calls):
            _write_artifact(adir, f"call_{i}.txt", c.text or (c.error or ""))
        _save_diff(task, cwd, adir)
        passed, total, pytest_out = verify(task, cwd)
        _write_artifact(adir, "pytest.txt", pytest_out)

        cap = _cap_reason(calls, wall, task)
        ok = total > 0 and passed == total and cap is None
        result = RunResult(
            task=task.id, category=task.category, arm=arm_name, rep=rep,
            success=ok,
            in_tok=sum(c.in_tok for c in calls),
            out_tok=sum(c.out_tok for c in calls),
            cost_usd=round(sum(c.cost_usd for c in calls), 6),
            wall_s=round(wall, 3),
            turns=sum(c.turns for c in calls),
            hit_cap=cap is not None,
            run_id=run_id,
            ts=now.isoformat(timespec="seconds"),
            cap_reason=cap,
            tests_passed=passed,
            tests_total=total,
            api_equiv_usd=round(sum(c.api_equiv_usd for c in calls), 6),
            cache_read_tok=sum(c.cache_read_tok for c in calls),
            cache_write_tok=sum(c.cache_write_tok for c in calls),
            cloud_calls=sum(1 for c in calls if c.provider == "cloud"),
            cloud_out_tok=sum(c.out_tok for c in calls if c.provider == "cloud"),
            n_calls=len(calls),
            env={
                "local_model": config.LOCAL_MODEL,
                "cloud_model": config.CLOUD_MODEL or "cli-default",
                "billing": config.CLOUD_BILLING,
                "machine": config.MACHINE_LABEL,
                "router_version": router.ROUTER_VERSION,
            },
        )

        _append_jsonl(asdict(result), config.RUNS_FILE)
        for i, c in enumerate(calls):
            rec = asdict(c)
            rec.pop("text")  # 原文は artifacts へ。ログ行は軽く保つ
            rec.update(schema=2, run_id=run_id, seq=i,
                       artifact=f"artifacts/{run_id}/call_{i}.txt")
            _append_jsonl(rec, config.CALLS_FILE)
        if router_dec is not None:
            _append_jsonl({
                "schema": 2, "run_id": run_id,
                "router_version": router_dec.router_version,
                "decision": router_dec.decision,
                "confidence": router_dec.confidence,
                "features": router_dec.features,
                "outcome_success": ok,
                "escalated": False,  # カスケード（R1）導入時に使う
            }, config.ROUTER_FILE)
        return result
    finally:
        cleanup(cwd)
