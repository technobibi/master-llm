"""ローカルモデルのエージェント実行ループ（ツール使用）。docs/DESIGN-agent.md が仕様。

素の単発生成(clients.call_local)と違い、モデルにツールを与え、
モデルがツールを要求→ハーネスが実行→結果を返す、を完了まで繰り返す。
これで Claude(claude -p)と同じ「読んで書いて実行して直す」土俵に乗せる。

★ run_tests は公開スモークテスト(smoke_test.py)だけ。隠しテスト(tests/)は
  絶対に触らせない（最終評価へのリークになる。DESIGN-testplan §0-1）。
"""
import json
import os
import subprocess
import sys
import time

import requests

from harness import config
from harness.applier import apply_code
from harness.models import CallResult

AGENT_VERSION = "local-agent-v2"  # v2: 成果物ができるまで終わらせない解決ループ+保険

_SYSTEM = """あなたはコーディングエージェントです。作業ディレクトリでタスクを完成させます。
使えるツール: list_files, read_file, write_file, run_tests, finish。
進め方:
1. まず list_files と read_file で現状を必ず確認する（推測でコードを書かない）。
2. write_file で編集・作成する。調査系の課題は指定された解答ファイル(例 BUGS.md)を write_file で作る。
3. コード課題は run_tests で確認し、失敗したら直す。
4. 完了したら finish を呼ぶ。
run_tests は公開スモークテストで、最終評価は別の隠しテストで行われます。"""

_SKIP = {"_hidden_tests", "__pycache__"}

_TOOLS = [
    {"type": "function", "function": {
        "name": "list_files", "description": "作業ディレクトリのファイル一覧",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "read_file", "description": "ファイルの内容を行番号付きで読む",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}}, "required": ["path"]}}},
    {"type": "function", "function": {
        "name": "write_file", "description": "ファイルに内容を書き込む（新規作成も可）",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}, "content": {"type": "string"}},
                       "required": ["path", "content"]}}},
    {"type": "function", "function": {
        "name": "run_tests", "description": "公開スモークテストを実行して結果を返す",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "finish", "description": "タスク完了を宣言する",
        "parameters": {"type": "object",
                       "properties": {"summary": {"type": "string"}}}}},
]

_MAX_TOOL_RESULT = 4000


def _resolve(cwd: str, path: str) -> str:
    """path を cwd 内に閉じ込めて絶対パス化。空・ディレクトリ・外部は弾く。"""
    if not path or not path.strip():
        raise ValueError("path が空です。ファイル名を指定してください。")
    full = os.path.realpath(os.path.join(cwd, path))
    root = os.path.realpath(cwd)
    if full != root and not full.startswith(root + os.sep):
        raise ValueError(f"作業ディレクトリの外は操作できません: {path}")
    if full == root or os.path.isdir(full):
        raise ValueError(f"{path} はディレクトリです。ファイル名を指定してください。")
    return full


def _list_files(cwd: str) -> str:
    out = []
    for root, dirs, files in os.walk(cwd):
        dirs[:] = [d for d in dirs if d not in _SKIP]
        for fn in sorted(files):
            if fn.endswith(".pyc"):
                continue
            out.append(os.path.relpath(os.path.join(root, fn), cwd))
    return "\n".join(sorted(out)) or "(ファイルなし)"


def _read_file(cwd: str, path: str) -> str:
    full = _resolve(cwd, path)
    if not os.path.isfile(full):
        return f"ファイルが存在しません: {path}"
    with open(full, encoding="utf-8", errors="replace") as f:
        lines = f.read().splitlines()
    return "\n".join(f"{i:4}| {ln}" for i, ln in enumerate(lines, 1))


def _write_file(cwd: str, path: str, content: str) -> str:
    full = _resolve(cwd, path)
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, "w", encoding="utf-8") as f:
        f.write(content)
    return f"書き込み完了: {path} ({len(content)} 文字)"


def _run_tests(cwd: str) -> str:
    smoke = os.path.join(cwd, "smoke_test.py")
    if not os.path.isfile(smoke):
        return "この課題に公開テストはありません（最終評価のみ。解答ファイルを作成して finish してください）。"
    env = dict(os.environ)
    env["PYTHONPATH"] = cwd + os.pathsep + env.get("PYTHONPATH", "")
    proc = subprocess.run([sys.executable, "-m", "pytest", "smoke_test.py", "-q"],
                          cwd=cwd, env=env, capture_output=True, text=True)
    tag = "成功" if proc.returncode == 0 else "失敗"
    return f"[スモーク{tag}]\n" + (proc.stdout or proc.stderr or "")[-_MAX_TOOL_RESULT:]


def _dispatch(name: str, args: dict, cwd: str) -> str:
    try:
        if name == "list_files":
            return _list_files(cwd)
        if name == "read_file":
            return _read_file(cwd, args.get("path", ""))
        if name == "write_file":
            return _write_file(cwd, args.get("path", ""), args.get("content", ""))
        if name == "run_tests":
            return _run_tests(cwd)
        return f"未知のツール: {name}"
    except Exception as e:  # ツール失敗はモデルに返して自己修正させる（握りつぶさない）
        return f"ツールエラー({name}): {e}"


def _required_output(task):
    """このタスクが最終的に残すべきファイル（report系は解答ファイル、code系は対象ファイル）。"""
    return task.answer_file or task.target_file or None


def _output_present(task, cwd: str) -> bool:
    out = _required_output(task)
    if not out:
        return True  # 成果物ファイルが定義されていないタスク
    p = os.path.join(cwd, out)
    return os.path.isfile(p) and os.path.getsize(p) > 0


def run_agent(task, cwd: str) -> CallResult:
    """タスクをエージェントとして解く。集約した CallResult を1つ返す
    （cloud と同じく turns=ステップ数、トークンは合算）。全対話は text に残す。

    解決ループ: モデルが「完了」を示しても、必要な成果物ファイルが無ければ差し戻して
    作らせる。それでも作らなければ最後に保険で最終テキストを保存する（素より悪くしない）。"""
    messages = [{"role": "system", "content": _SYSTEM},
                {"role": "user", "content": task.prompt}]
    transcript = []
    t0 = time.perf_counter()
    in_tok = out_tok = 0
    max_steps = min(task.budget.max_turns, config.AGENT_MAX_STEPS)
    err = None
    steps = 0
    last_text = ""
    nudges = 0

    while steps < max_steps:
        steps += 1
        try:
            resp = requests.post(
                f"{config.LOCAL_BASE_URL}/chat/completions",
                json={"model": config.LOCAL_MODEL, "messages": messages,
                      "tools": _TOOLS, "temperature": 0.2},
                timeout=600,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            err = str(e)[:300]
            break

        usage = data.get("usage", {}) or {}
        in_tok += usage.get("prompt_tokens", 0)
        out_tok += usage.get("completion_tokens", 0)
        msg = data["choices"][0]["message"]
        tool_calls = msg.get("tool_calls") or []
        messages.append({"role": "assistant", "content": msg.get("content") or "",
                         "tool_calls": tool_calls})
        if msg.get("content"):
            last_text = msg["content"]
            transcript.append(f"[assistant] {msg['content']}")

        finish_requested = not tool_calls  # ツール無しのテキスト = 完了の意思
        for tc in tool_calls:
            fn = tc.get("function", {}).get("name", "")
            raw = tc.get("function", {}).get("arguments", "") or "{}"
            try:
                args = json.loads(raw)
            except json.JSONDecodeError:
                args = {}
            if fn == "finish":
                finish_requested = True
                result = ("了解。タスク完了。" if _output_present(task, cwd)
                          else f"まだ {_required_output(task)} が作成されていません。"
                               "write_file で保存してから finish してください。")
            else:
                result = _dispatch(fn, args, cwd)
            transcript.append(f"[tool:{fn}] args={args}\n{result[:500]}")
            messages.append({"role": "tool", "tool_call_id": tc.get("id", ""),
                             "content": result[:_MAX_TOOL_RESULT]})

        if finish_requested:
            if _output_present(task, cwd):
                break  # 成果物あり＝本当に完了
            # 成果物が無いのに完了しようとした → 差し戻して作らせる（解決ループ）
            nudges += 1
            if nudges > 3:
                break  # 何度促しても作らない → ループ後の保険に委ねる
            out = _required_output(task)
            transcript.append(f"[nudge#{nudges}] {out} 未作成のため差し戻し")
            messages.append({"role": "user", "content":
                             f"回答内容は分かりましたが、まだ {out} というファイルが作られていません。"
                             f"その答えを write_file で {out} に必ず保存してください。"})

    # 保険: 成果物が無いまま終わったが、モデルが答えをテキストで出しているなら救済
    # （エージェントを素の単発生成より悪くしないための最終防衛線）
    if not _output_present(task, cwd) and last_text.strip():
        out = _required_output(task)
        if out:
            if task.answer_file:
                with open(os.path.join(cwd, out), "w", encoding="utf-8") as f:
                    f.write(last_text)
            else:
                apply_code(last_text, cwd, out)
            transcript.append(f"[保険] {out} が無かったので最終テキストを保存した")

    wall = time.perf_counter() - t0
    return CallResult(
        provider="local", model=config.LOCAL_MODEL, role="agent",
        in_tok=in_tok, out_tok=out_tok, cost_usd=0.0, api_equiv_usd=0.0,
        wall_s=wall, tok_per_s=round(out_tok / wall, 2) if wall > 0 else 0.0,
        turns=steps, error=err,
        text="\n\n".join(transcript)[:20000],
    )
