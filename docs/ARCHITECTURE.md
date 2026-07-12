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
| [DESIGN-testplan.md](DESIGN-testplan.md) | テストスイート設計（旧・自作7カテゴリ。設計記録として保持） | **廃止**（2026-07-12。公開ベンチに全面移行） |
| [DESIGN-agent.md](DESIGN-agent.md) | ローカル・エージェント（ツール使用ループ）。3arm比較で器の効果を測る | **実装済み**（v3、2026-07-12） |
| [DESIGN-swebench.md](DESIGN-swebench.md) | SWE-bench 取り込み（実リポ・複数ファイル課題を Docker 評価で計測） | **v1 実装済み**（2026-07-12） |
| [DESIGN-learning-loop.md](DESIGN-learning-loop.md) | 学習ループ（振り分け×モデル強化）とデータ共有・実行隔離の設計 | **設計のみ**（着手条件つき） |
| [DESIGN-router.md](DESIGN-router.md) | ②ルーティングデータと判定（天秤）・失敗帰属・指示コストの確定設計 | **設計のみ**（判定本体は所有者が実装） |
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
                          └───┬────────┬───┘   local_agent / cloud_only / router
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
| `harness/arms.py` | 比較条件（mock / local_only / local_agent / cloud_only / router） | arm を足すならここ |
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

## 実装済み（2026-07 時点）

計測基盤 v2（runs/calls/router jsonl + artifacts + 中央値 + オラクル regret）／
タスクは公開ベンチのみ 591問（HumanEval 164 + MBPP 427。自作スイートは 2026-07-12 廃止）／
3 arm（local_only=素・local_agent=ツール使用エージェント v3（grep・範囲read・wall打ち切り）・
cloud=claude -p）／ SWE-bench Lite 実行系（run_swebench.py）／ バッチベースライン+1:1ミラー
（run_baseline.py）／ ブラウザUI。

## 既知の設計課題（未解決のまま前提にしない）

- **arm の非対称性（緩和済み・未解消）**: local_agent でツール使用の器は揃えたが、
  cloud（claude -p）とは器が別物。完全対等ではないことをレポート解釈時に忘れない。
- **タスクの規模が小さい（緩和済み・未解消）**: HumanEval/MBPP は関数レベル。SWE-bench Lite
  実行系で実リポ課題は回せるようになった（DESIGN-swebench）が、計測データはまだ薄い。
- **公開ベンチの仕様品質**: MBPP は一行仕様で、テストだけが知る暗黙仮定がある
  （実測: Opus でも落ちる仕様欠陥を確認。mbpp_454 / mbpp_626）。数字を解釈する際は
  「能力不足」と「仕様不足」を混同しない（失敗帰属 2×2 = DESIGN-router §5）。
- **カテゴリの幅が狭い**: 自作スイート廃止（2026-07-12）により、調査系・UI・曖昧ペア等の
  軸は当面計測対象外。関数レベル（HumanEval/MBPP）+ 実リポ（SWE-bench）の2軸で見る。
- **ターン単位の usage 未取得**: `claude -p` の合計のみ。コンテキスト成長曲線には stream-json が要る。

## いま→次

- **ベースライン計測**: 公開ベンチ 591問 + SWE-bench を 30B エージェントで回してデータ蓄積
  （run_baseline で30問ずつ。ローカル先行 → 同じ問を cloud で 1:1 ミラー、日分割で）
- **学習ルーター**（所有者の領域）: 設計は DESIGN-router、着手条件は RESEARCH-BACKLOG R2
- 研究テーマは RESEARCH-BACKLOG.md（R1 カスケード → R2 学習ルーター → R5 蒸留 …）
