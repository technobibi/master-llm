"""比較する条件（arm）。各 arm は (task, cwd) を受け取り、解を cwd に残し、
(呼び出し一覧, ルーター判定 or None) を返す。
検証・キャップ判定・ログ書き込みはすべて runner が後で一元的に行う。
"""
import os
import subprocess
import sys
import time

from harness import agent, clients, config, router
from harness.applier import apply_code
from harness.models import CallResult, Task


_SKIP_CONTEXT = {"__pycache__", "_hidden_tests"}


def _repo_context(cwd: str, limit_bytes: int = 20000) -> str:
    """cwd 内のファイル（=seedのコピー）を読んでプロンプトに添える文脈ブロックを作る。

    クラウド(claude -p)は自分でファイルを読めるが、ローカルの単発呼び出しは
    プロンプトしか見えない。同じ土俵にするため、ローカルには seed の中身を渡す。
    隠しテスト・解答ファイルは含めない（cwd にまだ無い or 別ディレクトリなので自然に除外）。
    """
    parts, total = [], 0
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in _SKIP_CONTEXT]
        for fn in sorted(files):
            rel = os.path.relpath(os.path.join(root, fn), cwd)
            try:
                with open(os.path.join(root, fn), encoding="utf-8") as f:
                    body = f.read()
            except (OSError, UnicodeDecodeError):
                continue
            block = f"--- {rel} ---\n{body}\n"
            if total + len(block) > limit_bytes:
                parts.append(f"(残りのファイルは省略)")
                return "\n".join(parts)
            parts.append(block)
            total += len(block)
    return "\n".join(parts)


def _local_prompt(task: Task, cwd: str) -> str:
    """ローカル用プロンプト。指示＋現在のリポジトリ内容（行番号付き）。"""
    ctx = _repo_context(cwd)
    if not ctx:
        return task.prompt
    return (task.prompt
            + "\n\n===== 現在のファイル内容（行番号付き。これを見て回答すること） =====\n"
            + _with_line_numbers(ctx))


def _with_line_numbers(text: str) -> str:
    """`--- file ---` ヘッダ行はそのまま、コード行に 1 始まりの行番号を振る
    （バグ/脆弱性報告で行番号を答えさせるため）。ファイルごとに採番し直す。"""
    out, n = [], 0
    for line in text.splitlines():
        if line.startswith("--- ") and line.endswith(" ---"):
            out.append(line)
            n = 0
        else:
            n += 1
            out.append(f"{n:4}| {line}")
    return "\n".join(out)


def _local_smoke(cwd: str, target_file: str):
    """ローカル修正ループ用の公開検証。戻り値: エラー文字列（問題なければ None）。

    ★隠しテスト(tests/)は絶対に使わない（昇格判定へのリークになる。STUDY-2 §1）。
    使う信号は2つだけ、いずれも公開:
      1. 対象ファイルの構文チェック（py_compile）
      2. seed 同梱の公開スモークテスト smoke_test.py（あれば）を実行
         — 隠しテストより緩い基本ケースのみ。モデルに見せてよい。
    """
    if target_file:
        path = os.path.join(cwd, target_file)
        if not os.path.isfile(path):
            return f"{target_file} が作られていない"
        proc = subprocess.run([sys.executable, "-m", "py_compile", path],
                              capture_output=True, text=True)
        if proc.returncode != 0:
            return "構文エラー:\n" + (proc.stderr or "syntax error")[-800:]

    smoke = os.path.join(cwd, "smoke_test.py")
    if os.path.isfile(smoke):
        env = dict(os.environ)
        env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", "smoke_test.py", "-q"],
            cwd=cwd, env=env, capture_output=True, text=True,
        )
        if proc.returncode != 0:
            return "公開スモークテスト失敗:\n" + (proc.stdout or proc.stderr or "")[-1000:]
    return None


def arm_cloud_only(task: Task, cwd: str):
    """ベースライン：全部 Claude に丸投げ（ツール付きエージェント動作）。"""
    call = clients.call_cloud(task.prompt, cwd, task.budget.max_turns)
    return [call], None


def _write_answer(text: str, cwd: str, answer_file: str) -> None:
    """report系タスク: モデルの応答本文をそのまま解答ファイルに書く（コード抽出しない）。"""
    path = os.path.join(cwd, answer_file)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text or "")


def arm_local_only(task: Task, cwd: str):
    """ローカルだけ。

    - report系（answer_file 指定 = 調査/バグ/脆弱性）: 1発生成して応答を解答ファイルへ。
      コードではないので構文チェック・再生成はしない。
    - code系（pytest）: 生成 → 構文チェック → エラーを渡して再生成、を最大 LOCAL_MAX_RETRIES 回。
      クラウド（自律エージェント）との非対称性を緩和する最小の修正ループ。
    """
    base = _local_prompt(task, cwd)  # 指示＋seedの中身（クラウドとの非対称性を緩和）

    if task.answer_file:
        call = clients.call_local(base, role="solo")
        if not call.error:
            _write_answer(call.text, cwd, task.answer_file)
        return [call], None

    calls = []
    prompt = base
    for attempt in range(1 + config.LOCAL_MAX_RETRIES):
        call = clients.call_local(prompt, role="solo" if attempt == 0 else "retry")
        calls.append(call)
        if call.error:
            break
        apply_code(call.text, cwd, task.target_file)
        err = _local_smoke(cwd, task.target_file)
        if err is None:
            break
        prompt = (base
                  + "\n\n前回の解答は次のエラーで動かなかった。"
                  + "修正した完全なコードを1つのコードブロックで出すこと:\n" + err)
    return calls, None


def arm_local_agent(task: Task, cwd: str):
    """ローカルをツール使用エージェントとして動かす（docs/DESIGN-agent.md）。
    モデルが read/write/run_tests を自分で使ってタスクを解く。cloud と同じ土俵。
    """
    call = agent.run_agent(task, cwd)
    return [call], None


def arm_router(task: Task, cwd: str):
    """本命：ルーターの判定どおりにローカルかクラウドへ送る。
    判定記録（特徴量つき）は runner が router.jsonl に残す。
    発展形（ローカル失敗時にクラウドへ昇格するカスケード）は R1。
    """
    dec = router.decide(task.prompt, task)
    if dec.decision == "local":
        calls, _ = arm_local_only(task, cwd)
        return calls, dec
    calls, _ = arm_cloud_only(task, cwd)
    return calls, dec


def arm_mock(task: Task, cwd: str):
    """配管テスト用。モデル不要。模範解 (mock_solution.txt) を書くだけ。

    report系は解答ファイルへ生テキストで、code系はコードブロックとして書く。
    """
    t0 = time.perf_counter()
    sample = os.path.join(task.dir, "mock_solution.txt")
    if os.path.isfile(sample):
        with open(sample, encoding="utf-8") as f:
            content = f.read()
        if task.answer_file:
            _write_answer(content, cwd, task.answer_file)
        else:
            apply_code("```\n" + content + "\n```", cwd, task.target_file)
    call = CallResult(provider="mock", model="mock", in_tok=100, out_tok=50,
                      wall_s=time.perf_counter() - t0, text="mock")
    return [call], None


ARMS = {
    "mock": arm_mock,
    "local_only": arm_local_only,
    "local_agent": arm_local_agent,
    "cloud_only": arm_cloud_only,
    "router": arm_router,
}
