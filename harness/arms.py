"""比較する条件（arm）。各 arm は (task, cwd) を受け取り、解を cwd に残し、
(呼び出し一覧, キャップ超過フラグ) を返す。検証は runner が後で行う。
"""
import os
import time

from harness import clients
from harness.applier import apply_code
from harness.models import CallResult, Task
from harness.router import is_simple


def _over_cost(call: CallResult, task: Task) -> bool:
    return (call.cost_usd or 0) > task.budget.max_cost_usd


def _over_time(call: CallResult, task: Task) -> bool:
    return call.wall_s > task.budget.max_wall_s


def arm_cloud_only(task: Task, cwd: str):
    """ベースライン：全部 Claude に丸投げ。"""
    call = clients.call_cloud(task.prompt, cwd, task.budget.max_turns)
    return [call], _over_cost(call, task) or _over_time(call, task)


def arm_local_only(task: Task, cwd: str):
    """ローカルだけ（単発生成 → ファイル反映）。ローカルの限界を見る用。"""
    call = clients.call_local(task.prompt)
    apply_code(call.text, cwd, task.target_file)
    return [call], _over_time(call, task)


def arm_router(task: Task, cwd: str):
    """本命：簡単ならローカル、そうでなければクラウド。

    発展形：ローカルで実行→検証で落ちたらクラウドへ昇格（CascadeFlow 型）。
    """
    if is_simple(task.prompt):
        call = clients.call_local(task.prompt)
        apply_code(call.text, cwd, task.target_file)
        return [call], _over_time(call, task)
    call = clients.call_cloud(task.prompt, cwd, task.budget.max_turns)
    return [call], _over_cost(call, task) or _over_time(call, task)


def arm_mock(task: Task, cwd: str):
    """配管テスト用。モデル不要。模範解 (mock_solution.txt) を書くだけ。
    checkout→実行→検証→ログ→集計の全経路が動くかを、環境構築前に確認できる。
    """
    t0 = time.perf_counter()
    sample = os.path.join(task.dir, "mock_solution.txt")
    if os.path.isfile(sample):
        with open(sample) as f:
            apply_code("```\n" + f.read() + "\n```", cwd, task.target_file)
    call = CallResult("mock", in_tok=100, out_tok=50, cost_usd=0.0,
                      wall_s=time.perf_counter() - t0, turns=1, text="mock")
    return [call], False


ARMS = {
    "mock": arm_mock,
    "local_only": arm_local_only,
    "cloud_only": arm_cloud_only,
    "router": arm_router,
}
