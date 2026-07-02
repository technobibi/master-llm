"""ハーネス全体で使うデータ型。ここだけ見れば流れるデータが分かる。"""
from dataclasses import dataclass


@dataclass
class Budget:
    """1タスクの上限。当たったら未達=失敗として扱う。"""
    max_cost_usd: float = 0.50
    max_turns: int = 40
    max_wall_s: float = 600.0


@dataclass
class CallResult:
    """モデル1回呼び出しの計測結果。"""
    model: str                # "local" | "cloud" | "mock"
    in_tok: int = 0
    out_tok: int = 0
    cost_usd: float = 0.0
    wall_s: float = 0.0
    turns: int = 1            # クラウドは内部の num_turns、それ以外は1
    text: str = ""


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
    cost_usd: float
    wall_s: float
    turns: int
    hit_cap: bool
