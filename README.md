# master-llm — ローカル/クラウド オーケストレーション評価ハーネス

ローカルLLM（LM Studio）と Claude（Claude Code CLI・サブスク経由）を組み合わせた
オーケストレーションが「Claude だけでやる場合」と比べてどれだけ有用かを、
**同一タスク・同一指示**で計測・比較するための評価ハーネス。

計測する3軸（必ずセットで見る）:

| 軸 | 指標 | 良い方向 |
|---|---|---|
| 精度 | 隠しテストのクリア率 (`success`) | 高い |
| 金  | クラウドトークンの $ (`cost_usd`、ローカルは $0) | 低い |
| 速度 | 最初から最後までの実時間 (`wall_s`) | 短い |

## ドキュメント

全体像・設計・研究計画は `docs/` にある。**入口は [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**（図解+索引）。

- [docs/DESIGN-telemetry.md](docs/DESIGN-telemetry.md) — ログスキーマ（実装済み・source of truth）
- [docs/DESIGN-testplan.md](docs/DESIGN-testplan.md) — テストスイート（A〜G・静的採点・妥当性の限界）
- [docs/DESIGN-agent.md](docs/DESIGN-agent.md) — ローカル・エージェント（ツール使用ループ）
- [docs/DESIGN-router.md](docs/DESIGN-router.md) — ②ルーティングデータと判定（天秤）の確定設計
- [docs/DESIGN-learning-loop.md](docs/DESIGN-learning-loop.md) — 学習ループ・データ共有・実行隔離
- [docs/DESIGN-dataset.md](docs/DESIGN-dataset.md) — 学習データ基盤（routing / sft / ambiguity）
- [docs/RESEARCH-BACKLOG.md](docs/RESEARCH-BACKLOG.md) — 本線に載せない研究テーマの記録

## ディレクトリ構成

```
master-llm/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.local.example      # 秘密情報の雛形（実値は .env.local へ。コミット禁止）
├── docs/                   # 設計書・図解・研究バックログ（入口: ARCHITECTURE.md）
├── harness/                # 計測エンジン（責務ごとに分割）
│   ├── config.py           #   設定値（URL・モデル名・単価・既定キャップ）
│   ├── models.py           #   データ型（Task / Budget / CallResult / RunResult）
│   ├── clients.py          #   モデル呼び出し境界（ローカル /v1 ・ claude -p）
│   ├── applier.py          #   単発応答→ファイル反映（簡易エージェント）
│   ├── router.py           #   ルーティング判定（← いずれ学習させる中核）
│   ├── agent.py            #   ローカルのツール使用エージェント
│   ├── arms.py             #   条件（mock / local_only / local_agent / cloud_only / router）
│   ├── scoring.py          #   採点の振り分け（pytest / report-match / manifest-recall / ui-static）
│   ├── workspace.py        #   実行ごとにまっさらな作業コピーを用意
│   ├── runner.py           #   1タスク実行 + 隠しテスト検証 + ログ追記
│   └── report.py           #   runs.jsonl を arm 別に集計
├── tasks/                  # 自作タスクスイート suite v1（A〜F + fizzbuzz）+ SUITE-v1.yaml
│   ├── registry.py         #   tasks / tasks_ui / tasks_humaneval を走査
│   └── <id>/               #   task.yaml + seed/ + tests/（隠し採点）+ mock_solution.txt
├── tasks_ui/               # Web画面タスク G（ui-static採点・Playwright）
├── scripts/                # CLI 入口
│   ├── run_bench.py        #   全タスク × arm × 反復 を実行
│   ├── build_dataset.py    #   ログから学習データ生成（routing / sft / ambiguity）
│   ├── import_humaneval.py #   公開ベンチ取り込み → tasks_humaneval/（gitignore）
│   ├── show_report.py      #   集計テーブルを表示
│   └── serve_ui.py         #   ブラウザUI起動（http://127.0.0.1:8787）
├── webui/                  # 簡易UI（標準ライブラリのみ・localhost限定）
│   ├── server.py           #   APIサーバ + run_bench のサブプロセス起動
│   └── static/             #   index.html / style.css / app.js
└── runs/                   # 出力（runs.jsonl、gitignore 済み）
```

## セットアップ

```bash
cd master-llm
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### クラウド側（Claude Code CLI・サブスク接続）

トークン等の秘密情報は `.env.local` に置く（**gitignore 済み・コミット禁止**。公開リポジトリのため）:

```bash
claude setup-token            # 一度だけ。Pro/Max で 1年 OAuth トークンを発行
cp .env.local.example .env.local   # 発行されたトークンを .env.local に書き込む
source .env.local             # ベンチ実行前に毎回読み込む
```

`.env.local` は `unset ANTHROPIC_API_KEY` も行う（★これが残ると黙って従量課金APIになる）。

### ローカル側（LM Studio）

GUIを開かなくても CLI（`lms`）で完結する:

```bash
brew install --cask lm-studio          # 初回のみ。GUIを一度起動して lms を bootstrap
lms server start                       # OpenAI互換サーバを :1234 で起動
lms get "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"   # 高速枠（約4.3GB）
# 本命の30Bを使うなら: lms get "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit"
lms load <モデル名> 
export LOCAL_MODEL=<ロードしたモデルのID>   # /v1/models で表示される id に合わせる
```

GUI派は: LM Studio を起動 → モデルをロード → Developer タブで Server を Start でも同じ。

## これは何であって何でないか

**CLIツール**（`python -m scripts.run_bench` が本体）。Webアプリではない。
付属の「ブラウザUI」は TensorBoard や `mlflow ui` と同じ**手元専用のダッシュボード**で、
127.0.0.1 のみで動き、外部公開・デプロイ・アカウント・DBはない。
サーバを止めれば消える、CLIの操作パネルにすぎない。

## 使い方（ブラウザUI = ローカルダッシュボード）

```bash
python -m scripts.serve_ui     # → http://127.0.0.1:8787 を開く（起動中だけ使える）
```

タスク確認・arm選択・ベンチ実行・ログ表示・集計・履歴が1画面で使える。
CLI と同じ `scripts.run_bench` を裏で呼ぶだけなので、計測結果は完全に同一。

## 使い方（CLI・3段階）

```bash
# 1) まず配管確認：モデル不要。模範解を書いて全パイプラインが動くか見る
python -m scripts.run_bench --arms mock
python -m scripts.show_report

# 2) ローカルだけ（LM Studio 起動が必要）
python -m scripts.run_bench --arms local_only

# 3) 本番比較：Claude だけ vs ルーター
python -m scripts.run_bench --arms cloud_only,router --repeats 3
python -m scripts.show_report
```

## 計測方法のルール（結果を信用できるものにする4点）

1. **完了定義 + 予算キャップ**: `task.yaml` の `budget` で上限（コスト/ターン/時間）を置き、
   当たったら未達=失敗としてカウント。暴走した1回が平均を壊すのを防ぐ。
2. **テストは隠す**: `tests/` はエージェントに渡さず、実行後に `runner.verify()` が回す。
   見せると問題を解かずにテストだけ通す不正が起きる。
3. **複数回**: LLM は確率的。`--repeats 3`（以上）で中央値・ばらつきを見る。
4. **3軸まとめて**: 精度・$・時間を単独で語らない。「精度を保ったままコスト何%減か」で判断。

## タスクの増やし方

`tasks/<新id>/` を作り、`task.yaml`・`seed/`・`tests/` を置くだけで自動認識される。
まずは pytest で客観判定できる backend タスクから。UI タスク（Playwright 検証）は後から。
