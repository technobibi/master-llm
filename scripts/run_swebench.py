"""SWE-bench Lite を既存の計測基盤で回す実行スクリプト。

1インスタンス × 1arm × 1反復 = 1 run:
  ① キャッシュ済みリポ（swebench_repos/）を base_commit で checkout（まっさら作業コピー）
  ② arm 実行（gold / local_agent / cloud_only）。全 arm に同一プロンプト
  ③ git diff でパッチ抽出 → predictions.jsonl
  ④ swebench の Docker 評価（隠しテスト FAIL_TO_PASS / PASS_TO_PASS をコンテナ内で適用）
  ⑤ runs/runs.jsonl・calls.jsonl・artifacts/ へ既存スキーマ(v2)で記録

不変の計測ルール（docs/ARCHITECTURE.md）との対応:
  同一指示=② / テストは隠す=④（モデルには problem_statement しか見せない）/
  予算キャップ=⑤で事後判定（エージェントは実行時にも wall 打ち切り）/ append-only=⑤ /
  サブスク枠の保護= cloud_only は --yes-cloud を明示したときだけ動く

使い方（例）:
  ./.venv/bin/python -m scripts.run_swebench --arm gold --instances pallets__flask-4045
  ./.venv/bin/python -m scripts.run_swebench --arm local_agent --repo flask --limit 1
  ./.venv/bin/python -m scripts.run_swebench --arm cloud_only --instances <id> --yes-cloud
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict
from datetime import datetime, timezone

from harness import agent, clients, config, report, runner
from harness.models import Budget, CallResult, RunResult, Task

DATASET = "princeton-nlp/SWE-bench_Lite"
REPO_CACHE = "swebench_repos"          # bare クローンの置き場（gitignore 済み）
OUT_ROOT = os.path.join("runs", "swebench")  # 評価生成物の置き場（gitignore 済み）

# 全 arm に渡す同一プロンプト。問題文（GitHub issue）以外の情報は与えない
# （FAIL_TO_PASS 等のテスト情報を見せると「テストだけ通す不正」ができてしまう）
_PROMPT = """You are working in a checkout of the {repo} repository at commit {commit}.
Below is a GitHub issue describing a bug or requested change. Fix it by editing the source code.

Rules:
- Modify only the library source code. Do NOT modify or create tests.
- Keep the change minimal and focused on the issue.

<issue>
{problem}
</issue>
"""


def _sh(args, cwd=None, input_text=None):
    return subprocess.run(args, cwd=cwd, input=input_text,
                          capture_output=True, text=True)


# ---------- リポジトリの用意 ----------

def _ensure_repo(repo: str) -> str:
    """GitHub リポの bare クローンをキャッシュする（初回のみダウンロード）。"""
    dest = os.path.join(REPO_CACHE, repo.replace("/", "__") + ".git")
    if not os.path.isdir(dest):
        os.makedirs(REPO_CACHE, exist_ok=True)
        print(f"[clone] {repo} → {dest}（初回のみ）")
        proc = _sh(["git", "clone", "--bare", f"https://github.com/{repo}.git", dest])
        if proc.returncode != 0:
            raise RuntimeError(f"clone 失敗 {repo}: {proc.stderr[-300:]}")
    return dest


def _checkout(cache: str, base_commit: str) -> str:
    """base_commit のまっさら作業コピーを temp に作る（--shared でオブジェクトは共有）。"""
    tmp = tempfile.mkdtemp(prefix="swb_")
    proc = _sh(["git", "clone", "--shared", "--no-checkout", cache, tmp])
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"local clone 失敗: {proc.stderr[-300:]}")
    proc = _sh(["git", "checkout", "-q", base_commit], cwd=tmp)
    if proc.returncode != 0:
        shutil.rmtree(tmp, ignore_errors=True)
        raise RuntimeError(f"checkout 失敗 {base_commit[:12]}: {proc.stderr[-300:]}")
    return tmp


def _extract_patch(cwd: str) -> str:
    """作業コピーの変更を1つのパッチにまとめる（新規ファイル含む）。"""
    _sh(["git", "add", "-A"], cwd=cwd)
    proc = _sh(["git", "-c", "core.fileMode=false", "diff", "--cached", "--no-color"], cwd=cwd)
    return proc.stdout


# ---------- arm ----------

def _arm_gold(inst: dict, task: Task, cwd: str) -> CallResult:
    """正解パッチをそのまま適用する配管テスト用 arm（mock と同じ位置づけ・モデル不要）。
    checkout → diff 抽出 → Docker 評価 → 記録、の自前パイプライン全体を無料で検証できる。
    """
    t0 = time.perf_counter()
    proc = _sh(["git", "apply", "--whitespace=nowarn", "-"], cwd=cwd,
               input_text=inst["patch"])
    err = None if proc.returncode == 0 else f"gold apply 失敗: {proc.stderr[-300:]}"
    return CallResult(provider="mock", model="gold", wall_s=time.perf_counter() - t0,
                      error=err, text="(gold patch applied)")


def _run_arm(arm: str, inst: dict, task: Task, cwd: str) -> CallResult:
    if arm == "gold":
        return _arm_gold(inst, task, cwd)
    if arm == "local_agent":
        return agent.run_agent(task, cwd)
    if arm == "local_aider":
        return _arm_aider(task, cwd)
    if arm == "local_opencode":
        return _arm_opencode(task, cwd)
    if arm == "cloud_only":
        return clients.call_cloud(task.prompt, cwd, task.budget.max_turns)
    if arm == "cloud_full":
        return clients.call_cloud(task.prompt, cwd, task.budget.max_turns, full=True)
    raise ValueError(f"未知の arm: {arm}")


AIDER_LABEL = "aider-0.86.2"  # 実用装備ローカルの器バージョン（env.harness に記録）
OPENCODE_LABEL = "opencode-1.17.15"  # 完全体ローカル（サブエージェント・フルツール・MCP）


def _arm_opencode(task: Task, cwd: str) -> CallResult:
    """完全体ローカル: OpenCode（サブエージェント/bash/編集/grep標準装備）を
    ヘッドレス実行。LM Studio モデルを lmstudio/<id> で指定。"""
    oc = os.environ.get("OPENCODE_BIN", "opencode")
    cmd = [oc, "run", "-m", f"lmstudio/{config.LOCAL_MODEL}", task.prompt]
    t0 = time.perf_counter()
    err = None
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=dict(os.environ), capture_output=True,
                              text=True, timeout=task.budget.max_wall_s)
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        if proc.returncode != 0:
            err = f"opencode rc={proc.returncode}"
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
        err = f"opencode timeout {task.budget.max_wall_s:.0f}s"
    wall = time.perf_counter() - t0
    return CallResult(provider="local", model=config.LOCAL_MODEL, role="opencode",
                      wall_s=wall, turns=1, error=err, text=(out or "")[-20000:])


def _aider_tokens(text: str):
    """Aider の "Tokens: 8.2k sent, 415 received." 行を合算して (in, out) を返す。"""
    def n(s):
        s = s.replace(",", "")
        return int(float(s[:-1]) * 1000) if s.endswith("k") else int(float(s))
    in_tok = out_tok = 0
    for m in re.finditer(r"Tokens: ([\d.,k]+) sent, ([\d.,k]+) received", text):
        in_tok += n(m.group(1))
        out_tok += n(m.group(2))
    return in_tok, out_tok


def _arm_aider(task: Task, cwd: str) -> CallResult:
    """実用装備ローカル: Aider（diff編集・リポマップ）で LM Studio モデルを駆動。
    自作エージェント（local_agent）と違い、道具の質は製品級。器の差の計測対象。"""
    aider = os.environ.get("AIDER_BIN", os.path.expanduser("~/.local/bin/aider"))
    env = dict(os.environ)
    env["OPENAI_API_BASE"] = config.LOCAL_BASE_URL
    env["OPENAI_API_KEY"] = "dummy"
    cmd = [aider, "--model", f"openai/{config.LOCAL_MODEL}",
           "--yes-always", "--no-auto-commits", "--no-pretty", "--no-stream",
           "--no-analytics", "--no-show-model-warnings",
           "--message", task.prompt]
    t0 = time.perf_counter()
    err = None
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True,
                              text=True, timeout=task.budget.max_wall_s)
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        if proc.returncode != 0:
            err = f"aider rc={proc.returncode}"
    except subprocess.TimeoutExpired as e:
        out = e.stdout if isinstance(e.stdout, str) else (e.stdout or b"").decode(errors="replace")
        err = f"aider timeout {task.budget.max_wall_s:.0f}s"
    wall = time.perf_counter() - t0
    in_tok, out_tok = _aider_tokens(out or "")
    return CallResult(provider="local", model=config.LOCAL_MODEL, role="aider",
                      in_tok=in_tok, out_tok=out_tok,
                      wall_s=wall, tok_per_s=round(out_tok / wall, 2) if wall > 0 else 0.0,
                      turns=1, error=err, text=(out or "")[-20000:])


# ---------- Docker 評価 ----------

def _docker_eval(batch_dir: str, preds_path: str, iid: str, eval_id: str,
                 timeout: int) -> str:
    """swebench の公式ハーネスで1インスタンスを評価。出力は batch_dir 配下に閉じる。"""
    cmd = [sys.executable, "-m", "swebench.harness.run_evaluation",
           "-d", DATASET, "-s", "test",
           "-p", os.path.abspath(preds_path),
           "-i", iid, "-id", eval_id,
           "--max_workers", "1", "-t", str(timeout),
           "--cache_level", "env", "--report_dir", "."]
    proc = subprocess.run(cmd, cwd=batch_dir, capture_output=True, text=True)
    with open(os.path.join(batch_dir, f"eval_{eval_id}.log"), "w") as f:
        f.write(proc.stdout + "\n--- stderr ---\n" + proc.stderr)
    if proc.returncode != 0:
        return f"docker 評価がエラー終了 (exit {proc.returncode})。eval_{eval_id}.log 参照"
    return ""


def _parse_report(batch_dir: str, model_label: str, eval_id: str, iid: str):
    """(resolved, f2p_pass, f2p_total, p2p_pass, p2p_total) を評価レポートから読む。"""
    per = os.path.join(batch_dir, "logs", "run_evaluation", eval_id,
                       model_label, iid, "report.json")
    if not os.path.isfile(per):
        return False, 0, 0, 0, 0
    with open(per) as f:
        rep = json.load(f).get(iid, {})
    ts = rep.get("tests_status", {})
    f2p = ts.get("FAIL_TO_PASS", {})
    p2p = ts.get("PASS_TO_PASS", {})
    f2p_pass, f2p_fail = len(f2p.get("success", [])), len(f2p.get("failure", []))
    p2p_pass, p2p_fail = len(p2p.get("success", [])), len(p2p.get("failure", []))
    return (bool(rep.get("resolved")), f2p_pass, f2p_pass + f2p_fail,
            p2p_pass, p2p_pass + p2p_fail)


# ---------- メイン ----------

def _done_instance_ids(arm: str) -> set:
    """同じ条件（arm、local はさらに同じ agent_version+local_model、
    cloud は同じ cloud_model）で記録済みのインスタンス集合。再開時の二重実行を防ぐ。"""
    done = set()
    if not os.path.isfile(config.RUNS_FILE):
        return done
    invalid = report.invalid_run_ids()
    with open(config.RUNS_FILE) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("run_id") in invalid:
                continue
            if r.get("category") != "swebench" or r.get("arm") != arm:
                continue
            env = r.get("env", {})
            if arm == "local_agent" and (
                env.get("agent_version") != agent.AGENT_VERSION
                or env.get("local_model") != config.LOCAL_MODEL
            ):
                continue
            if arm in ("local_aider", "local_opencode") and env.get("local_model") != config.LOCAL_MODEL:
                continue
            if arm in ("cloud_only", "cloud_full") and env.get("cloud_model") != config.CLOUD_MODEL:
                continue
            done.add(r.get("task"))
    return done


def _select_instances(args):
    from datasets import load_dataset
    ds = load_dataset(DATASET, split="test")
    rows = list(ds)
    if args.instances:
        want = set(args.instances)
        rows = [r for r in rows if r["instance_id"] in want]
        missing = want - {r["instance_id"] for r in rows}
        if missing:
            sys.exit(f"データセットに無い instance_id: {sorted(missing)}")
    elif args.repo:
        rows = [r for r in rows if args.repo in r["repo"]]
        rows = rows[: args.limit]
    else:
        sys.exit("--instances か --repo を指定してください（誤爆防止のため既定で全件は回さない）")
    return rows


def main():
    ap = argparse.ArgumentParser(
        description="SWE-bench Lite を既存テレメトリで計測（docs/DESIGN-swebench.md）")
    ap.add_argument("--arm", required=True,
                    choices=["gold", "local_agent", "local_aider", "local_opencode",
                             "cloud_only", "cloud_full"])
    ap.add_argument("--instances", nargs="*", help="instance_id を空白区切りで指定")
    ap.add_argument("--repo", help="repo 名の部分一致で選ぶ（例: flask）")
    ap.add_argument("--limit", type=int, default=1, help="--repo 選択時の件数上限（既定1）")
    ap.add_argument("--repeats", type=int, default=1,
                    help="反復数（比較の主張には3以上・中央値を使うこと）")
    ap.add_argument("--max-turns", type=int, default=30, help="エージェントの最大ステップ")
    ap.add_argument("--max-wall", type=float, default=1800.0, help="1問の壁時計上限秒")
    ap.add_argument("--max-cost", type=float, default=2.0, help="API換算$の上限")
    ap.add_argument("--eval-timeout", type=int, default=1800, help="Docker評価のタイムアウト秒")
    ap.add_argument("--yes-cloud", action="store_true",
                    help="cloud_only の実行に必須（サブスク枠を消費する自覚の明示）")
    ap.add_argument("--no-skip-done", action="store_true",
                    help="実行済み（同arm・同版/モデル）でも再実行する")
    ap.add_argument("--keep-workspace", action="store_true", help="作業コピーを消さない（デバッグ）")
    args = ap.parse_args()

    if args.arm == "cloud_only" and not args.yes_cloud:
        sys.exit("cloud_only はサブスク枠を消費します。意図的なら --yes-cloud を付けてください。")
    if shutil.which("docker") is None or _sh(["docker", "info"]).returncode != 0:
        sys.exit("Docker が動いていません。Docker Desktop を起動してください。")

    rows = _select_instances(args)
    if not args.no_skip_done:
        done = _done_instance_ids(args.arm)
        skipped = [r["instance_id"] for r in rows if r["instance_id"] in done]
        rows = [r for r in rows if r["instance_id"] not in done]
        if skipped:
            print(f"[skip] 実行済み {len(skipped)} 問を除外（--no-skip-done で再実行可）")
    if not rows:
        print("対象がありません（すべて実行済み）。")
        return
    print(f"対象 {len(rows)} 問 × {args.repeats} 反復, arm={args.arm}")

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    batch_dir = os.path.join(OUT_ROOT, f"{stamp}_{args.arm}")
    os.makedirs(batch_dir, exist_ok=True)

    # swebench はステップ数が要る。設定既定(12)より大きい値を CLI から通す
    config.AGENT_MAX_STEPS = max(config.AGENT_MAX_STEPS, args.max_turns)

    resolved_n = 0
    for inst in rows:
        iid = inst["instance_id"]
        cache = _ensure_repo(inst["repo"])
        task = Task(
            id=iid, category="swebench",
            prompt=_PROMPT.format(repo=inst["repo"], commit=inst["base_commit"][:12],
                                  problem=inst["problem_statement"]),
            target_file="", dir=batch_dir,
            budget=Budget(max_cost_usd=args.max_cost, max_turns=args.max_turns,
                          max_wall_s=args.max_wall),
            tier="high", scoring="swebench",
        )
        for rep in range(args.repeats):
            run_id = f"{stamp}_{iid}_{args.arm}_{rep}"
            adir = os.path.join(config.ARTIFACTS_DIR, run_id)
            os.makedirs(adir, exist_ok=True)
            with open(os.path.join(adir, "prompt.txt"), "w") as f:
                f.write(task.prompt)

            cwd = _checkout(cache, inst["base_commit"])
            try:
                t0 = time.perf_counter()
                call = _run_arm(args.arm, inst, task, cwd)
                wall = time.perf_counter() - t0
                patch = _extract_patch(cwd)
            finally:
                if args.keep_workspace:
                    print(f"[keep] {cwd}")
                else:
                    shutil.rmtree(cwd, ignore_errors=True)

            with open(os.path.join(adir, "call_0.txt"), "w") as f:
                f.write(call.text or (call.error or ""))
            with open(os.path.join(adir, "model_patch.diff"), "w") as f:
                f.write(patch)

            model_label = f"{args.arm}_{(call.model or 'none').replace('/', '-')}"
            eval_id = f"{iid}_r{rep}"
            preds = os.path.join(batch_dir, f"preds_{eval_id}.jsonl")
            with open(preds, "w") as f:
                f.write(json.dumps({"instance_id": iid, "model_name_or_path": model_label,
                                    "model_patch": patch}) + "\n")

            eval_err = ""
            if patch.strip():
                eval_err = _docker_eval(batch_dir, preds, iid, eval_id, args.eval_timeout)
            resolved, f2p_p, f2p_t, p2p_p, p2p_t = _parse_report(
                batch_dir, model_label, eval_id, iid)
            # tests_total はデータセット由来で必ず埋める（レポート欠損時も分母を残す）
            total = (f2p_t + p2p_t) or (len(json.loads(inst["FAIL_TO_PASS"]))
                                        + len(json.loads(inst["PASS_TO_PASS"])))
            passed = f2p_p + p2p_p

            cap = runner._cap_reason([call], wall, task)  # キャップ判定は runner と同一基準
            ok = resolved and cap is None and not call.error
            result = RunResult(
                task=iid, category="swebench", arm=args.arm, rep=rep,
                success=ok,
                in_tok=call.in_tok, out_tok=call.out_tok,
                cost_usd=round(call.cost_usd, 6), wall_s=round(wall, 3),
                turns=call.turns, hit_cap=cap is not None,
                run_id=run_id, ts=now.isoformat(timespec="seconds"),
                cap_reason=cap, tests_passed=passed, tests_total=total,
                api_equiv_usd=round(call.api_equiv_usd, 6),
                cache_read_tok=call.cache_read_tok, cache_write_tok=call.cache_write_tok,
                cloud_calls=1 if call.provider == "cloud" else 0,
                cloud_out_tok=call.out_tok if call.provider == "cloud" else 0,
                n_calls=1,
                env={
                    "entry": "run_swebench-v1", "dataset": DATASET,
                    "repo": inst["repo"], "base_commit": inst["base_commit"],
                    "eval_id": eval_id, "eval_error": eval_err or None,
                    "local_model": config.LOCAL_MODEL,
                    "cloud_model": config.CLOUD_MODEL or "cli-default",
                    "billing": config.CLOUD_BILLING, "machine": config.MACHINE_LABEL,
                    "agent_version": agent.AGENT_VERSION,
                    "harness": (AIDER_LABEL if args.arm == "local_aider"
                                else OPENCODE_LABEL if args.arm == "local_opencode"
                                else "claude-full" if args.arm == "cloud_full" else "builtin"),
                    "max_wall": args.max_wall,
                    "agent_max_out_tokens": config.AGENT_MAX_OUT_TOKENS or None,
                },
            )
            runner._append_jsonl(asdict(result), config.RUNS_FILE)
            rec = asdict(call)
            rec.pop("text")
            rec.update(schema=2, run_id=run_id, seq=0,
                       artifact=f"artifacts/{run_id}/call_0.txt")
            runner._append_jsonl(rec, config.CALLS_FILE)

            resolved_n += 1 if ok else 0
            mark = "ok " if ok else ("cap" if cap else "ng ")
            note = eval_err or call.error or ""
            print(f"[{mark}] {iid:34s} {args.arm} rep{rep} "
                  f"resolved={resolved} tests {passed}/{total} "
                  f"$eq{call.api_equiv_usd:.4f} {wall:.0f}s turns={call.turns} {note[:80]}")

    print(f"\n完了: resolved {resolved_n}/{len(rows) * args.repeats}  "
          f"生成物: {batch_dir}  ログ: {config.RUNS_FILE}")


if __name__ == "__main__":
    main()
