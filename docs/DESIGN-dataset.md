# 設計書: 学習データ基盤（dataset）

**目的**: 将来の学習（ルーター分類器 → LoRA 蒸留 → 自作 nanoGPT）に使えるデータを、
**いま走らせるベンチの副産物として自動で貯める**。学習そのものは研究バックログ
（R2, R5）であり本線ではないが、データは今日から貯めないと後で取り直せない。

## 基本構造: ログが正、データセットは派生

```
runs/*.jsonl + runs/artifacts/     ←  正（source of truth）。telemetry v2 が書く
        │
        │  scripts/build_dataset.py（読み取り専用。ログは変更しない）
        ▼
datasets/<種類>/v<N>/              ←  派生。バージョン付きで固定（immutable）
```

- **ログからデータセットを再生成できる**ことが要件。データセット側が壊れても失うものはない。
- `v1` を作ったら中身は二度と変更しない。作り方を変えたら `v2` を新規に作る。
  （どのモデルをどのデータで学習したかを後から追える＝再現性）
- `runs/artifacts/` と `datasets/` は gitignore。スキーマ（この文書）だけを git 管理。

## データセット1: routing（ルーター学習用）

**1行 = 1タスク×1反復のペア比較。** ベンチが全 arm を同一タスクで回すため、
「ローカルに送っていたらどうだったか」の反実仮想ラベルが揃う。
これは production ルーターには作れない、このハーネス固有の資産。

ペアの規則（2026-07-12 更新）:
- local 側は `--local-arm`（**既定 local_agent** = 現行ベースラインの器）、cloud 側は cloud_only
- **現行の agent_version / cloud_model の行だけ**で組む（器・モデルが変わると能力も別物。
  古い版の行は「版違いスキップ」として件数表示）
- 同じ (task, rep, side) に複数行あれば新しい方（ts）を採用
- 各行に出所（`local_arm` / `local_agent_version` / `cloud_model` / `source_run_ids`）を残す

`datasets/routing/v1/pairs.jsonl`:

```json
{
  "task": "fizzbuzz", "rep": 0,
  "prompt": "（原文全文。artifacts/prompt.txt から）",
  "features": {"prompt_len": 84, "prompt_lang": "ja", "category": "backend",
               "n_seed_files": 1, "seed_bytes": 320},
  "local_success": true,  "local_wall_s": 9.1,
  "cloud_success": true,  "cloud_wall_s": 42.3, "cloud_api_equiv_usd": 0.012,
  "oracle_arm": "local",
  "source_run_ids": ["…_local_only_0", "…_cloud_only_0"]
}
```

- ラベルの主役は `local_success`（分類器はこれを予測する）。
- `oracle_arm` は「成功 > 時間 > 枠消費」の辞書順で機械的に決める（regret 計算と同じ規則）。
- `source_run_ids` で元ログへ遡れるようにする（監査可能性）。

**成立条件**: 同一 task×rep で `local_only` と `cloud_only` の両方の run があること。
build スクリプトは揃っていないペアをスキップし、スキップ数を表示する（黙って欠損させない）。

## データセット2: sft（蒸留・自作モデル学習用）

**1行 = 成功 run の (指示, 最終diff) ペア。** クラウド成功例は「Claude が Qwen を教える」
LoRA 蒸留（R5）の教材になり、さらに先の自作モデル（nanoGPT 系）の SFT データにもなる。

`datasets/sft/v1/pairs.jsonl`:

```json
{
  "task": "fizzbuzz",
  "prompt": "（原文全文）",
  "seed_files": {"fizzbuzz.py": "（seed の原文）"},
  "diff": "（artifacts/diff.patch の全文）",
  "teacher": "cloud",
  "tests_passed": 5, "tests_total": 5,
  "source_run_id": "…_cloud_only_0"
}
```

- `success == true` の run だけを収録（失敗解を教材にしない）。
- `teacher` で「誰の解か」を区別（cloud / local）。ローカルの成功解も入れる。
  蒸留時に teacher でフィルタすればよい。

## データセット3: ambiguity（指示の曖昧さ研究用）

**狙い**: 「どんな指示が失敗・迷走を生むか」を測る。曖昧さは直接観測できないので、
**自動の代理シグナル**と**人手ラベル**の2層で貯める。

### 自動シグナル（build_dataset.py がログから計算）

| シグナル | 出所 | 曖昧さとの関係 |
|---|---|---|
| `turns`（クラウドの内部ターン数） | runs.jsonl | 迷走・試行錯誤の量 |
| `success` の反復間ばらつき | 同一 task の rep 間 | 指示が不安定な解釈を許す度合い |
| 応答間の食い違い | artifacts の応答原文 | 同じ指示で別解釈が出る=曖昧 |
| 逆質問の有無 | 応答原文に質問文があるか | モデル自身が曖昧と感じた証拠 |

`datasets/ambiguity/v1/signals.jsonl`（1行 = 1タスク）:

```json
{
  "task": "fizzbuzz",
  "prompt_sha256": "ab12…",
  "prompt": "（原文全文）",
  "reps": 3,
  "success_rate_local": 0.67, "success_rate_cloud": 1.0,
  "turns_median": 3,
  "asked_clarification": false
}
```

### 人手ラベル（唯一の手書きファイル）

`datasets/annotations/ambiguity.jsonl` に自分で追記する。**append-only・行の書き換え禁止**
（意見が変わったら新しい行を足す。`ts` が新しい行を採用）:

```json
{"prompt_sha256": "ab12…", "task": "fizzbuzz", "ambiguity": 2,
 "notes": "対象ファイルは明示済み。出力形式が未指定", "ts": "2026-07-02T05:20:00Z"}
```

- `ambiguity`: 1（完全に明確）〜 5（解釈が割れて当然）の5段階。
- プロンプトの同一性は `prompt_sha256` で判定（タスクを書き直したら別プロンプト扱い）。
- 将来「曖昧さの自動推定器」を作るとき（nanoGPT の練習台に良いサイズ）、
  自動シグナルが特徴量、この人手ラベルが教師になる。

## scripts/build_dataset.py（新規 CLI の仕様）

```bash
python -m scripts.build_dataset --kind routing   --ver 1
python -m scripts.build_dataset --kind sft       --ver 1
python -m scripts.build_dataset --kind ambiguity --ver 1
```

- 読み: `runs/*.jsonl` と `runs/artifacts/`。書き: `datasets/<kind>/v<ver>/` のみ。
- 出力先が既に存在したらエラーで止まる（immutable 原則の強制）。
- 最後に件数サマリを表示: 収録 N 件 / ペア不成立でスキップ M 件 / エラー K 件。

## 実装状況

`scripts/build_dataset.py`（routing / sft / ambiguity）は**実装済み**。holdout タスクは自動除外。
残る本線は「タスク数を増やす」＝データの原料を増やすこと（公開ベンチ取り込み → DESIGN-router §7）。
