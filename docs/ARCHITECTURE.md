# master-llm アーキテクチャ

ローカルLLM（LM Studio）と Claude（サブスク経由 `claude -p`）のオーケストレーションが
「Claude 単独」と比べてどれだけ有用かを、同一タスク・同一指示で計測する評価ハーネス。

このファイルが全ドキュメントの入口。**5分で全体を思い出す**ためのページ。

## ドキュメント索引

| 文書 | 内容 | 状態 |
|---|---|---|
| [README.md](../README.md) | セットアップと使い方 | 実装済みの範囲を記載 |
| [DESIGN-telemetry.md](DESIGN-telemetry.md) | 計測基盤 v2（精度・時間・トークン・コスト・枠消費のログ設計） | **実装済み**（2026-07-09） |
| [DESIGN-dataset.md](DESIGN-dataset.md) | 学習データ基盤（routing / sft / ambiguity の3データセット） | **実装済み**（build_dataset.py） |
| [DESIGN-testplan.md](DESIGN-testplan.md) | テストスイート設計（7カテゴリ22+タスク・静的採点・holdout分割） | **設計のみ・次の実装対象** |
| [RESEARCH-BACKLOG.md](RESEARCH-BACKLOG.md) | 本線に載せない研究テーマ R1〜R9（着手条件つき） | 記録のみ |
| [study/STUDY-1-llm.md](study/STUDY-1-llm.md) | 勉強ノート: LLMの仕組み（このプロジェクトに必要な分だけ） | 教材 |
| [study/STUDY-2-harness.md](study/STUDY-2-harness.md) | 勉強ノート: 計測ルールの「なぜ」= ML評価の設計思想 | 教材 |
| [study/STUDY-3-router.md](study/STUDY-3-router.md) | 勉強ノート: ルーター = 二値分類器。学習器への道筋 | 教材 |

## 全体図

```
                         scripts/run_bench.py（CLI 入口）
                                   │  タスク × arm × 反復 のループ
                                   ▼
  tasks/<id>/ ───────────▶ ┌───────────────┐
   ├ task.yaml  指示+予算   │ harness/runner │ 1 run の司令塔
   ├ seed/      初期コード  └───────┬───────┘
   └ tests/     隠しテスト          │ ① seed を temp へコピー（workspace）
     （エージェントには見せない）    │ ② arm 実行
                                   ▼
                          ┌────────────────┐
                          │  harness/arms  │ 比較条件: mock / local_only /
                          └───┬────────┬───┘            cloud_only / router
                              │        │
                 router arm のみ判定    │
                       ▼               │
                ┌──────────────┐       │
                │ harness/router│ 簡単? │        ← 将来: ログから学習した分類器に差し替え
                └───┬──────┬───┘       │           （これがこのプロジェクトの「脳」）
             簡単 ▼        ▼ 難しい    ▼
      ┌─────────────┐   ┌──────────────────┐
      │ LM Studio   │   │ claude -p        │      harness/clients が呼び出し境界
      │ /v1・$0     │   │ サブスク枠を消費  │      （トークン・時間はここで計測）
      │ 単発生成     │   │ エージェント動作  │
      └──────┬──────┘   └────────┬─────────┘
             │ applier がファイル反映│（claude は自分で編集）
             └──────────┬─────────┘
                        ▼
              ③ runner.verify(): 隠しテストを実行 → success 判定
                        │
                        ▼
      ┌─────────────────────────────────────────┐
      │ runs/  （計測ログ・append-only）          │
      │  runs.jsonl   1行 = 1 run の集計          │ ← 現在ここまで実装済み（v1）
      │  calls.jsonl  1行 = 1呼び出し   [設計]    │
      │  router.jsonl 1行 = 1判定       [設計]    │
      │  artifacts/   原文（prompt/応答/diff）[設計]│
      └───────┬─────────────────────┬───────────┘
              │                     │
              ▼                     ▼
   scripts/show_report.py   scripts/build_dataset.py [設計]
   3軸+枠消費の集計表         datasets/{routing,sft,ambiguity}/v<N>/
   （将来: オラクル regret）              │
                                        ▼
                            将来の学習（研究バックログ）
                            R2 学習ルーター ──── router.py へ差し替え（図の左上へ戻る）
                            R5 LoRA 蒸留 ────── ローカルモデル自体を強化
                            その先: 自作 nanoGPT の教材
```

**閉ループが本体**: 計測（runs/）→ データ化（datasets/）→ 学習 → ルーター差し替え → また計測。
差別化の核はルーター単体ではなく、この「自分のタスク分布で回る計測と学習の閉ループ」。

## モジュール一覧（コードを開く前の地図）

| ファイル | 責務 | 一言 |
|---|---|---|
| `harness/config.py` | 設定値（URL・モデル名・単価・既定値） | 環境変数で上書き可 |
| `harness/models.py` | データ型（Task / Budget / CallResult / RunResult） | ここだけ見れば流れるデータが分かる |
| `harness/clients.py` | モデル呼び出し境界（ローカル /v1・claude -p） | トークン・時間・$ の計測点 |
| `harness/applier.py` | 単発応答 → ファイル反映 | ローカル用の簡易エージェント |
| `harness/router.py` | ルーティング判定 | 今はキーワードルール。将来学習させる中核 |
| `harness/arms.py` | 比較条件（mock / local_only / cloud_only / router） | arm を足すならここ |
| `harness/workspace.py` | 実行ごとのまっさら作業コピー | 実行間の汚染防止 |
| `harness/runner.py` | 1 run の司令塔 + 隠しテスト検証 + ログ | 計測基盤 v2 の主な改修先 |
| `harness/report.py` | ログの集計表 | 中央値化・regret が今後の改修 |
| `tasks/registry.py` | tasks/*/task.yaml の読み込み | タスク追加はディレクトリを置くだけ |

## 不変の計測ルール（変えるときはこの文書ごと変える）

1. **同一タスク・同一指示**を全 arm に渡す（比較の土台）
2. **テストは隠す**（見せるとテストだけ通す不正が起きる）
3. **予算キャップ**超過は失敗扱い（暴走1回に平均を壊させない）
4. **3回以上反復・中央値**で見る（LLM は確率的）
5. **3軸+枠消費をセットで見る**: 精度 / API換算$ / 時間 / サブスク枠。単独の軸で語らない
6. **ログは append-only・生データ優先**（詳細は DESIGN-telemetry.md）

## 既知の設計課題（未解決のまま前提にしない）

- **arm の非対称性（緩和済み・未解消）**: local に「生成→構文チェック→再生成」ループは
  入った（2026-07-09）が、cloud のようなツール使用・実行結果の観察はまだない。
  完全対等ではないことをレポートの解釈時に忘れない。
- **タスクが1個**: fizzbuzz のみ。結論を出すにはカテゴリ横断で 10〜20 タスク必要。
- **ターン単位の usage 未取得**: `claude -p` の合計しか取っていない。コンテキスト
  成長曲線（曖昧さ研究の本丸）には `--output-format stream-json` への切り替えが要る。

## いま→次（ロードマップ、上から順）

1. ~~計測基盤 v2 の実装~~ ✅ 2026-07-09（runs/calls/router jsonl + artifacts + 中央値 + regret）
2. ~~local arm の修正ループ~~ ✅ 同上（構文チェックベース。実行観察はまだ）
3. ~~build_dataset.py~~ ✅ 同上（routing / sft / ambiguity）
4. ~~local_only / cloud_only の実弾検証~~ ✅ 2026-07-10（全経路live。7B導入済み、30Bは未DL）
5. **テストスイート suite v1 の実装（DESIGN-testplan.md の実装順序 1→7）** ← いまここ
6. suite v1 凍結 → 全arm×3反復のベースライン計測 → データ蓄積
7. ここから先は RESEARCH-BACKLOG.md（R1 カスケード → R2 学習ルーター…）
