"""設定値を一箇所に集約。環境変数で上書き可能。"""
import os

# --- ローカルモデル（LM Studio の OpenAI 互換サーバ） ---
LOCAL_BASE_URL = os.environ.get("LOCAL_BASE_URL", "http://localhost:1234/v1")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen/qwen3-coder-30b")  # LM Studio のモデルキー（lms ls で確認）

# --- クラウド（Claude Code CLI・サブスク接続） ---
CLAUDE_BIN = os.environ.get("CLAUDE_BIN", "claude")
CLOUD_MODEL = os.environ.get("CLOUD_MODEL", "claude-opus-4-8")  # 空なら CLI 既定モデル
CLOUD_ALLOWED_TOOLS = os.environ.get("CLOUD_ALLOWED_TOOLS", "Read,Edit,Write,Bash")

# --- 単価（USD / 100万トークン）。クラウドのみ課金、ローカルは $0 ---
# claude -p の JSON が total_cost_usd を返せばそれを優先。無ければこの表で概算。
# ↓ ルーティング先のモデルの実単価に置き換えること（下は仮の値）。
PRICING = {
    "cloud": {"in": 3.00, "out": 15.00},
}

# --- 課金モード ---
# "subscription": claude -p はサブスク接続。実支払 cost_usd は 0、CLI報告額は API換算値として記録
# "api":          従量課金API接続。CLI報告額がそのまま実支払
CLOUD_BILLING = os.environ.get("CLOUD_BILLING", "subscription")

# --- ローカルの修正ループ（クラウドとの非対称性を緩和） ---
LOCAL_MAX_RETRIES = int(os.environ.get("LOCAL_MAX_RETRIES", "2"))

# --- ローカル・エージェント（ツール使用ループ） ---
AGENT_MAX_STEPS = int(os.environ.get("AGENT_MAX_STEPS", "12"))
# 1回の生成の出力トークン上限（0=無効・従来挙動）。
# 特定プロンプトでモデルが EOS を出さず無限生成 → クライアント600s タイムアウト
# → サーバにゾンビ生成が残る事故を実測（Gemma4/Qwen3.6）。設定時のみ安全弁が入る
AGENT_MAX_OUT_TOKENS = int(os.environ.get("AGENT_MAX_OUT_TOKENS", "0"))
# ツール結果1件をモデルへ返すときの上限文字数。実リポ探索(SWE-bench)では
# 4000 だと読める範囲が狭すぎるため v3 で 8000 に拡大（器の変更は AGENT_VERSION で追跡）
AGENT_TOOL_RESULT_MAX = int(os.environ.get("AGENT_TOOL_RESULT_MAX", "8000"))

# --- タスク埋め込み（バッチ選択の多様性サンプリング・将来のルーター特徴量） ---
EMBED_MODEL = os.environ.get("EMBED_MODEL", "text-embedding-nomic-embed-text-v1.5")
TASK_VECTORS_FILE = os.environ.get("TASK_VECTORS_FILE", "runs/task_vectors.jsonl")

# --- 環境スナップショット用ラベル（個人情報を入れないこと） ---
MACHINE_LABEL = os.environ.get("MACHINE_LABEL", "unknown")

# --- 既定値 ---
RUNS_FILE = os.environ.get("RUNS_FILE", "runs/runs.jsonl")
# 計測条件違反（推論失速・並行実行など）の run を「行を消さずに」除外するための注釈ファイル。
# 行は runs.jsonl に残し、集計・skip-done だけがここを参照して除外する（append-only 原則の維持）
INVALID_RUNS_FILE = os.environ.get("INVALID_RUNS_FILE", "runs/invalid_runs.jsonl")
CALLS_FILE = os.environ.get("CALLS_FILE", "runs/calls.jsonl")
ROUTER_FILE = os.environ.get("ROUTER_FILE", "runs/router.jsonl")
ARTIFACTS_DIR = os.environ.get("ARTIFACTS_DIR", "runs/artifacts")
DEFAULT_REPEATS = int(os.environ.get("DEFAULT_REPEATS", "3"))
