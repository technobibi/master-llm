"""ローカル専用の簡易UIサーバ（標準ライブラリ + requests のみ・追加依存なし）。

起動:  python -m scripts.serve_ui   →  http://127.0.0.1:8787

できること = 現時点のCLI機能のUI化:
  - タスク一覧（tasks/*/task.yaml）
  - 環境チェック（LM Studio 疎通・claude CLI の有無）
  - ベンチ実行（arm選択・反復数・タスク絞り込み）→ scripts.run_bench をサブプロセスで起動
  - 進捗・実行ログの表示 / 中断
  - 集計レポート（harness.report と同じ集計）と実行履歴（runs.jsonl の末尾）

127.0.0.1 のみで待ち受ける。外部公開しない前提の開発用ツール。
"""
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import requests

from harness import config
from harness.arms import ARMS
from harness.report import aggregate, load
from tasks.registry import load_tasks

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")

MIME = {".html": "text/html", ".css": "text/css", ".js": "text/javascript"}


class BenchJob:
    """同時に1つだけ動くベンチ実行。標準出力を行単位で溜めてUIに流す。"""

    def __init__(self):
        self.proc = None
        self.log = deque(maxlen=500)
        self.lock = threading.Lock()
        self.total = 0  # 予定 run 数（進捗表示用）

    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def done(self) -> int:
        """完了 run 数 = run_bench が出す [ok]/[FAIL] 行を数える。"""
        return sum(1 for line in self.log if line.startswith("["))

    def start(self, arms, repeats, task=None, total=0) -> bool:
        with self.lock:
            if self.running():
                return False
            cmd = [sys.executable, "-u", "-m", "scripts.run_bench",
                   "--arms", ",".join(arms), "--repeats", str(repeats)]
            if task:
                cmd += ["--task", task]
            self.log.clear()
            self.total = total
            self.log.append("$ " + " ".join(cmd))
            self.proc = subprocess.Popen(
                cmd, cwd=ROOT, text=True,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
            threading.Thread(target=self._pump, daemon=True).start()
            return True

    def _pump(self):
        for line in self.proc.stdout:
            self.log.append(line.rstrip())
        self.log.append(f"--- 終了 (exit {self.proc.wait()})")

    def stop(self):
        if self.running():
            self.proc.terminate()
            self.log.append("--- 中断リクエスト送信")


JOB = BenchJob()

# --- 環境チェック（5秒キャッシュ。UIのポーリングで外部を叩きすぎない） ---
_health_cache = {"ts": 0.0, "data": None}


def health() -> dict:
    now = time.monotonic()
    if _health_cache["data"] and now - _health_cache["ts"] < 5:
        return _health_cache["data"]
    lm_ok, lm_model = False, None
    try:
        r = requests.get(f"{config.LOCAL_BASE_URL}/models", timeout=0.8)
        if r.ok:
            models = r.json().get("data", [])
            lm_ok = True
            lm_model = models[0]["id"] if models else None
    except requests.RequestException:
        pass
    data = {
        "lm_studio": lm_ok,
        "lm_model": lm_model,
        "claude_cli": shutil.which(config.CLAUDE_BIN) is not None,
    }
    _health_cache.update(ts=now, data=data)
    return data


def _task_dict(t):
    return {
        "id": t.id, "category": t.category, "target_file": t.target_file,
        "prompt": t.prompt,
        "budget": {"max_cost_usd": t.budget.max_cost_usd,
                   "max_turns": t.budget.max_turns,
                   "max_wall_s": t.budget.max_wall_s},
    }


def state() -> dict:
    rows = load()
    return {
        "arms": list(ARMS),
        "tasks": [_task_dict(t) for t in load_tasks()],
        "health": health(),
        "job": {"running": JOB.running(), "done": JOB.done(), "total": JOB.total},
        "log": list(JOB.log),
        "report": aggregate(rows),
        "recent": rows[-20:][::-1],
        "n_runs": len(rows),
    }


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # 標準のアクセスログは黙らせる
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/state":
            return self._json(state())
        name = "index.html" if self.path == "/" else self.path.lstrip("/")
        path = os.path.normpath(os.path.join(STATIC, name))
        if not path.startswith(STATIC) or not os.path.isfile(path):
            return self._json({"error": "not found"}, 404)
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        ext = os.path.splitext(path)[1]
        self.send_header("Content-Type", MIME.get(ext, "application/octet-stream") + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        n = int(self.headers.get("Content-Length") or 0)
        try:
            req = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "bad json"}, 400)

        if self.path == "/api/bench":
            arms = [a for a in req.get("arms", []) if a in ARMS]
            if not arms:
                return self._json({"error": "比較条件（arm）を1つ以上選んでください"}, 400)
            repeats = max(1, min(int(req.get("repeats", 1)), 20))
            task = req.get("task") or None
            n_tasks = len([t for t in load_tasks() if not task or t.id == task])
            if n_tasks == 0:
                return self._json({"error": "タスクが見つかりません"}, 400)
            total = n_tasks * len(arms) * repeats
            if not JOB.start(arms, repeats, task, total=total):
                return self._json({"error": "すでに実行中です。終了か中断を待ってください"}, 409)
            return self._json({"ok": True, "total": total})

        if self.path == "/api/stop":
            JOB.stop()
            return self._json({"ok": True})

        return self._json({"error": "not found"}, 404)


def serve(port: int = 8787):
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"master-llm UI: http://127.0.0.1:{port}  (Ctrl-C で終了)")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        JOB.stop()
