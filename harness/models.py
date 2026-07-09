"""ハーネス全体で使うデータ型。ここだけ見れば流れるデータが分かる。

スキーマは docs/DESIGN-telemetry.md が正。変えるときは SCHEMA を上げ、
古い行は変換せず report 側で読み替える（append-only 原則）。
"""
from dataclasses import dataclass, field
from typing import Optional

SCHEMA = 2


@dataclass
class Budget:
    """1タスクの上限。当たったら未達=失敗として扱う。

    max_cost_usd は API換算額（api_equiv_usd）に対するキャップ。
    サブスクだと実支払 0 のままクラウドが暴走できてしまうため、換算額で縛る。
    """
    max_cost_usd: float = 2.00   # 実測: claude -p は最小タスクでも換算$1前後（固定費）
    max_turns: int = 40
    max_wall_s: float = 600.0


@dataclass
class CallResult:
    """モデル1回呼び出しの計測結果（calls.jsonl の1行のもと）。"""
    provider: str                       # "local" | "cloud" | "mock"
    model: str = ""                     # 実モデル名（例: qwen3-coder-30b-a3b）
    role: str = "solo"                  # solo / retry / draft / review / escalation
    in_tok: int = 0
    out_tok: int = 0
    cache_read_tok: int = 0             # キャッシュ読み（API課金 約1/10）
    cache_write_tok: int = 0            # キャッシュ書き込み（約1.25倍）
    cost_usd: float = 0.0               # 実支払額（サブスクなら 0）
    api_equiv_usd: float = 0.0          # API従量課金なら幾らかの換算値
    wall_s: float = 0.0
    tok_per_s: float = 0.0              # 出力速度（ローカルの熱ドリフト検出用）
    turns: int = 1                      # クラウドは内部の num_turns、それ以外は1
    error: Optional[str] = None         # 失敗も必ず記録する（握りつぶさない）
    text: str = ""                      # 応答本文。ログには載せず artifacts へ


@dataclass
class RouterDecision:
    """ルーティング判定1回の記録（router.jsonl の1行のもと）。"""
    decision: str                       # "local" | "cloud"
    features: dict                      # 判定時に見た特徴量のスナップショット
    router_version: str
    confidence: Optional[float] = None  # ルールベースは None。学習器で予測確率


@dataclass
class Task:
    """1つの評価タスク（パケット）。"""
    id: str
    category: str             # lookup / edit / translate / feature / debug ...
    prompt: str               # 全 arm に同一で渡す指示文
    target_file: str          # 解を置くべきファイル（単一ファイルタスク用）
    dir: str                  # タスクパケットの絶対パス
    budget: Budget


@dataclass
class RunResult:
    """1タスク×1arm×1反復の最終計測結果。1行=1レコードで runs.jsonl に追記。"""
    task: str
    category: str
    arm: str
    rep: int
    success: bool
    in_tok: int
    out_tok: int
    cost_usd: float           # 実支払額の合計（サブスクなら 0）
    wall_s: float
    turns: int
    hit_cap: bool
    # --- v2 追加フィールド ---
    schema: int = SCHEMA
    run_id: str = ""
    ts: str = ""              # ISO 8601 / UTC
    cap_reason: Optional[str] = None    # "cost" | "time" | "turns" | None
    tests_passed: int = 0
    tests_total: int = 0
    api_equiv_usd: float = 0.0
    cache_read_tok: int = 0
    cache_write_tok: int = 0
    cloud_calls: int = 0      # サブスク枠消費の代理指標①
    cloud_out_tok: int = 0    # 同②（出力トークンが枠を最も食う）
    n_calls: int = 1
    env: dict = field(default_factory=dict)  # 再現性のためのスナップショット
