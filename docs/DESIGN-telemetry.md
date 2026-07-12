# 設計書: 計測基盤（telemetry v2）

**目的**: 精度・時間・トークン・コスト・枠消費を、後から何度でも再分析できる形で記録する。
**状態**: **実装済み**。この文書はログスキーマの正（source of truth）。変えたら文書も更新する。

## 設計原則（4つ）

1. **追記のみ (append-only)**: JSONL に追記するだけ。書き換え・削除しない。
2. **1ファイル=1イベント種**: run / call / 判定 を別ファイルに分け、`run_id` で結合する。
3. **生データ > 派生値**: 特徴量や集計は後で計算し直せる。プロンプト・応答・diff の原文を artifacts に残す。
4. **スキーマにバージョン番号**: 全レコードに `"schema": 2`。形式を変えたら番号を上げ、古い行は変換せず読む。

## ファイル構成

```
runs/
├── runs.jsonl              # 1行 = 1 run（タスク × arm × 反復）の集計
├── calls.jsonl             # 1行 = モデル1呼び出し
├── router.jsonl            # 1行 = ルーティング判定1回（学習ルーターの教師データ）
└── artifacts/<run_id>/     # 原文置き場（gitignore）
    ├── prompt.txt          #   実際に送った指示文
    ├── call_<seq>.txt      #   各呼び出しの応答全文（エージェントは全対話）
    ├── diff.patch          #   seed → 最終状態の差分（絶対パスは a/seed・b/final に置換）
    └── pytest.txt          #   採点の出力全文
```

`run_id` = `{UTC時刻}_{task}_{arm}_{rep}`（例 `20260702T051300Z_fizzbuzz_router_0`）。
時刻だけで一意にせず task/arm/rep を含めるのは目視 grep のため。

## スキーマ

### runs.jsonl

```json
{
  "schema": 2,
  "run_id": "20260702T051300Z_fizzbuzz_router_0",
  "ts": "2026-07-02T05:13:00Z",
  "task": "fizzbuzz", "category": "edit", "arm": "router", "rep": 0,
  "success": true, "hit_cap": false, "cap_reason": null,
  "tests_passed": 5, "tests_total": 5,
  "in_tok": 912, "out_tok": 270,
  "cache_read_tok": 0, "cache_write_tok": 0,
  "cost_usd": 0.0, "api_equiv_usd": 0.012,
  "cloud_calls": 1, "cloud_out_tok": 250,
  "wall_s": 42.3, "turns": 3, "n_calls": 2,
  "env": {"local_model": "...", "cloud_model": "...", "billing": "subscription",
          "machine": "...", "router_version": "rule-v1", "agent_version": "local-agent-v2"}
}
```

**cost_usd と api_equiv_usd を分ける理由**: `claude -p` が返す `total_cost_usd` はサブスク下では
請求されない架空値。実支払（0）と API 換算を混ぜると「いくら節約したか」の主張が崩れるため別カラム。

### calls.jsonl

```json
{
  "schema": 2, "run_id": "...", "seq": 0,
  "provider": "local", "model": "qwen2.5-coder-7b-instruct", "role": "solo",
  "in_tok": 812, "out_tok": 220, "cache_read_tok": 0, "cache_write_tok": 0,
  "cost_usd": 0.0, "api_equiv_usd": 0.0,
  "wall_s": 9.1, "tok_per_s": 24.2, "turns": 1, "error": null,
  "artifact": "artifacts/.../call_0.txt"
}
```

- `provider`: `"local" | "cloud" | "mock"`。`model` は実モデル名。
- `role`: `"solo"`（単発）/ `"retry"`（構文再生成）/ `"agent"`（ツール使用ループ）。カスケード導入時に draft/review/escalation を追加（R1）。
- `tok_per_s`: ローカルの熱ドリフト検出用（R7）。
- `error`: 例外・タイムアウト・JSONパース失敗の要約。**失敗した呼び出しも必ず1行残す**。

### router.jsonl（学習ルーターの教師データ）

```json
{
  "schema": 2, "run_id": "...", "router_version": "rule-v1",
  "decision": "local", "confidence": null,
  "features": {"prompt_len": 84, "prompt_lang": "ja", "hint_hit": "rename",
               "category": "edit", "tier": "low", "scoring": "pytest", "modality": "text",
               "n_seed_files": 1, "seed_bytes": 320},
  "outcome_success": true, "escalated": false
}
```

- `features` は判定時のスナップショット。意味系（prompt）と規模系（n_seed_files/seed_bytes）の2系統。
  将来ここに意味ベクトルを足す（→ DESIGN-router）。原文は artifacts にあるので特徴量は作り直せる。
- `confidence`: ルールベースは null、学習器で予測確率。
- `outcome_success`/`escalated` は run 終了後に runner が最後に1行で書く（途中書き更新をしない）。

## 計測ルール

| 項目 | ルール |
|---|---|
| 時間 | `wall_s` は arm 全体、call 単位は各呼び出しを囲む |
| 精度 | 隠しテストの `tests_passed / tests_total`。全通過かつキャップ内で `success` |
| 反復 | 既定 3 回以上。集計は平均でなく **中央値 + 最小/最大**（LLM は外れ値が出る） |
| 枠消費 | `cloud_calls`・`cloud_out_tok` を第4の軸として常設 |

## report.py の集計（実装済み）

arm 別テーブル（中央値）: `success / tests% / api-eq(med) / sec(med) / cloud_calls / out_tok(med)`。
「**オラクル regret**」: task×rep ごとに全 arm の結果があるので最良 arm（成功 > 時間 > 枠消費）を選び
router との差を出す。

## v1 ログとの共存

schema フィールドの無い旧行は report 側で「v1」として読み替える（v1 の cost_usd は api_equiv に移す）。
変換スクリプトは作らない。
