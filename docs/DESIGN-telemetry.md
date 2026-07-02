# 設計書: 計測基盤（telemetry v2）

**目的**: 性能（精度）・時間・トークン消費・コストを、後から何度でも再分析できる形で記録する。
**状態**: 設計のみ。現行実装は runs.jsonl（集計1行）だけの v1。

## 設計原則（4つ）

1. **追記のみ (append-only)**: ログは JSONL に追記するだけ。書き換え・削除しない。
2. **1ファイル=1イベント種**: run / call / 判定 を別ファイルに分け、`run_id` で結合する。
3. **生データ > 派生値**: 特徴量や集計は後で計算し直せる。プロンプト・応答・diff の原文を artifacts に残す。
4. **スキーマにバージョン番号**: 全レコードに `"schema": 2` を入れる。形式を変えたら番号を上げ、古い行は変換せずそのまま読む。

## ファイル構成

```
runs/
├── runs.jsonl              # 1行 = 1 run（タスク × arm × 反復）の集計   ← v1 から拡張
├── calls.jsonl             # 1行 = モデル1呼び出し                      ← 新規
├── router.jsonl            # 1行 = ルーティング判定1回（将来の教師データ）← 新規
└── artifacts/<run_id>/     # 原文置き場（gitignore）                    ← 新規
    ├── prompt.txt          #   実際に送った指示文
    ├── call_<seq>.txt      #   各呼び出しの応答全文
    ├── diff.patch          #   seed → 最終状態の差分（成功時の学習データの種）
    └── pytest.txt          #   隠しテストの出力全文
```

### run_id

`{UTC時刻}_{task}_{arm}_{rep}` 形式。例: `20260702T051300Z_fizzbuzz_router_0`。
時刻だけで一意にせず task/arm/rep を含めるのは、ログを目視 grep しやすくするため。

## スキーマ

### runs.jsonl（v1 に追加するフィールドに ★）

```json
{
  "schema": 2,                                   ★
  "run_id": "20260702T051300Z_fizzbuzz_router_0", ★
  "ts": "2026-07-02T05:13:00Z",                  ★ ISO 8601 / UTC
  "task": "fizzbuzz", "category": "backend",
  "arm": "router", "rep": 0,
  "success": true,
  "hit_cap": false,
  "cap_reason": null,                            ★ "cost" | "time" | "turns" | null
  "tests_passed": 5, "tests_total": 5,           ★ 精度をテスト粒度で（pytest 出力から取得）
  "in_tok": 912, "out_tok": 270,
  "cost_usd": 0.0,                                  実際の支払額（サブスクなら 0）
  "api_equiv_usd": 0.012,                        ★ API 換算額（比較用の仮想値）
  "cloud_calls": 1, "cloud_out_tok": 250,        ★ サブスク枠消費の代理指標
  "wall_s": 42.3, "turns": 3, "n_calls": 2,      ★ n_calls
  "env": {                                       ★ 再現性のためのスナップショット
    "local_model": "qwen3-coder-30b-a3b",
    "cloud_model": "default",
    "machine": "m5-air-32gb",
    "router_version": "rule-v1"
  }
}
```

**cost_usd と api_equiv_usd を分ける理由**: `claude -p` が返す `total_cost_usd` は
サブスク下では実際には請求されない架空の数字。実支払額（0）と API 換算額を
混ぜると「いくら節約できたか」の主張が崩れるため、必ず別カラムにする。

### calls.jsonl（新規）

```json
{
  "schema": 2,
  "run_id": "20260702T051300Z_fizzbuzz_router_0",
  "seq": 0,
  "provider": "local",
  "model": "qwen3-coder-30b-a3b",
  "role": "solo",
  "in_tok": 812, "out_tok": 220,
  "wall_s": 9.1,
  "tok_per_s": 24.2,
  "cost_usd": 0.0, "api_equiv_usd": 0.0,
  "turns": 1,
  "error": null,
  "artifact": "artifacts/20260702T051300Z_fizzbuzz_router_0/call_0.txt"
}
```

- `provider`: `"local" | "cloud" | "mock"`。`model` は実モデル名（現行の `"local"` という値をやめる）。
- `role`: その呼び出しの役割。`"solo"`（単独）から始め、カスケード導入時に
  `"draft" | "review" | "escalation"` を追加（→ RESEARCH-BACKLOG R1）。
- `tok_per_s`: `out_tok / wall_s`。ローカルの熱ドリフト検出用（→ R7）。
- `error`: 例外・タイムアウト・JSON パース失敗の要約文字列。成功時は null。
  **失敗した呼び出しも必ず1行残す**（現行 v1 は握りつぶし気味）。

### router.jsonl（新規・将来の学習ルーターの教師データ）

```json
{
  "schema": 2,
  "run_id": "20260702T051300Z_fizzbuzz_router_0",
  "router_version": "rule-v1",
  "decision": "local",
  "confidence": null,
  "features": {
    "prompt_len": 84,
    "prompt_lang": "ja",
    "hint_hit": "rename",
    "category": "backend",
    "n_seed_files": 1,
    "seed_bytes": 320
  },
  "outcome_success": true,
  "escalated": false
}
```

- `features` は判定時に見た値のスナップショット。**原文は artifacts にあるので、
  後で特徴量を作り直せる**（原則3）。
- `confidence`: ルールベースでは null。学習ルーターに差し替えたら予測確率を入れる。
- `outcome_success` / `escalated` は run 終了後に **runner が最後に1行で書く**
  （途中書き→更新をしない。追記のみ原則を守る）。

## 計測ルール

| 項目 | ルール |
|---|---|
| 時間 | `wall_s` は arm 全体を囲む（現行踏襲）。call 単位の `wall_s` は各呼び出しを囲む |
| 精度 | 隠しテストの `tests_passed / tests_total`。全通過かつキャップ内で `success` |
| 反復 | 既定 3 回以上。集計は平均でなく **中央値 + 最小/最大**（LLM は外れ値が出る） |
| トークン | API/サーバ報告の usage を正とする。取れない場合は 0 でなく null |
| 枠消費 | `cloud_calls` と `cloud_out_tok` を第4の軸としてレポートに常設 |

## report.py への反映（集計仕様）

現行の arm 別テーブルを次の列に変更:

```
arm          runs  success  tests%   $api-eq(med)  sec(med)  cloud_calls  out_tok(med)
```

- 平均 → 中央値。`runs >= 5` になったら min–max も併記。
- 追加集計「**オラクル regret**」: タスク×rep ごとに全 arm の結果があるので、
  最良 arm（成功 > 時間 > 枠消費の辞書順）を選び、router との差を出す（→ R6。実装は軽い）。

## 実装ステップ（この順で。各ステップ単体で動く）

1. `models.py`: `RunResult` に ★ フィールド追加、`CallResult` に `provider/model/role/tok_per_s/error/api_equiv_usd` 追加
2. `runner.py`: run_id 生成・artifacts 保存（prompt / 応答 / diff / pytest 出力）・calls.jsonl 追記
3. `clients.py`: 実モデル名の記録・エラー時も CallResult を返して必ずログに載せる（現行の except 経路を統合）
4. `router.py`: `is_simple()` を「判定 + features dict」を返す `decide()` に置き換え → runner が router.jsonl へ
5. `report.py`: 中央値化・api_equiv 列・枠消費列（regret は後回しで可）

## v1 ログの扱い

既存の `runs/runs.jsonl`（schema フィールドなし）は捨てず、report 側で
「`schema` キーがなければ v1」として読む。変換スクリプトは作らない。
