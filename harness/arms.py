"""比較する条件（arm）。各 arm は (task, cwd) を受け取り、解を cwd に残し、
(呼び出し一覧, ルーター判定 or None) を返す。
検証・キャップ判定・ログ書き込みはすべて runner が後で一元的に行う。
"""
import os
import subprocess
import sys
import time

from harness import clients, config, router
from harness.applier import apply_code
from harness.models import CallResult, Task


def _local_smoke(cwd: str, target_file: str):
    """ローカル修正ループ用の公開スモークチェック（構文チェックのみ）。

    ★隠しテストは絶対に使わない（使うと昇格判定へのリークになる。STUDY-2 §1）。
    戻り値: エラーメッセージ（問題なければ None）。
    """
    path = os.path.join(cwd, target_file)
    if not os.path.isfile(path):
        return f"{target_file} が作られていない"
    proc = subprocess.run([sys.executable, "-m", "py_compile", path],
                          capture_output=True, text=True)
    if proc.returncode == 0:
        return None
    return (proc.stderr or "syntax error")[-800:]


def arm_cloud_only(task: Task, cwd: str):
    """ベースライン：全部 Claude に丸投げ（ツール付きエージェント動作）。"""
    call = clients.call_cloud(task.prompt, cwd, task.budget.max_turns)
    return [call], None


def arm_local_only(task: Task, cwd: str):
    """ローカルだけ。生成 → 構文チェック → エラーを渡して再生成、を最大
    LOCAL_MAX_RETRIES 回。クラウド（自律エージェント）との非対称性を緩和する
    最小の修正ループ。実行結果まで見るループは将来の課題。
    """
    calls = []
    prompt = task.prompt
    for attempt in range(1 + config.LOCAL_MAX_RETRIES):
        call = clients.call_local(prompt, role="solo" if attempt == 0 else "retry")
        calls.append(call)
        if call.error:
            break
        apply_code(call.text, cwd, task.target_file)
        err = _local_smoke(cwd, task.target_file)
        if err is None:
            break
        prompt = (task.prompt
                  + "\n\n前回の解答は次のエラーで動かなかった。"
                  + "修正した完全なコードを1つのコードブロックで出すこと:\n" + err)
    return calls, None


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
    """配管テスト用。モデル不要。模範解 (mock_solution.txt) を書くだけ。"""
    t0 = time.perf_counter()
    sample = os.path.join(task.dir, "mock_solution.txt")
    if os.path.isfile(sample):
        with open(sample) as f:
            apply_code("```\n" + f.read() + "\n```", cwd, task.target_file)
    call = CallResult(provider="mock", model="mock", in_tok=100, out_tok=50,
                      wall_s=time.perf_counter() - t0, text="mock")
    return [call], None


ARMS = {
    "mock": arm_mock,
    "local_only": arm_local_only,
    "cloud_only": arm_cloud_only,
    "router": arm_router,
}
