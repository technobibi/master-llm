"""設定値を一箇所に集約。環境変数で上書き可能。"""
import os

# --- ローカルモデル（LM Studio の OpenAI 互換サーバ） ---
LOCAL_BASE_URL = os.environ.get("LOCAL_BASE_URL", "http://localhost:1234/v1")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen3-coder-30b-a3b")

# --- クラウド（Claude Code CLI・サブスク接続） ---
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "")  # 空なら CLI 既定モデル
CLOUD_ALLOWED_TOOLS = os.environ.get("CLOUD_ALLOWED_TOOLS", "Read,Edit,Write,Bash")

# --- 単価（USD / 100万トークン）。クラウドのみ課金、ローカルは $0 ---
# claude -p の JSON が total_cost_usd を返せばそれを優先。無ければこの表で概算。
# ↓ ルーティング先のモデルの実単価に置き換えること（下は仮の値）。
PRICING = {
    "cloud": {"in": 3.00, "out": 15.00},
}

# --- 既定値 ---
RUNS_FILE = os.environ.get("RUNS_FILE", "runs/runs.jsonl")
DEFAULT_REPEATS = int(os.environ.get("DEFAULT_REPEATS", "3"))
