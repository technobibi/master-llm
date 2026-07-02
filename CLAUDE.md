# CLAUDE.md

## ⚠️ このリポジトリは public（最優先ルール）

個人情報・機密情報を **絶対にコミット・push しないこと**。具体的には:

- **実トークン・APIキー**（`CLAUDE_CODE_OAUTH_TOKEN`、`sk-ant-...` 等）
  → 実値は `.env.local` に置く（gitignore 済み）。コード・ドキュメント・コミットメッセージにも書かない
- **個人情報**: 氏名・メールアドレス・電話番号・ローカルのホームパス（`/Users/<名前>/...`）
  → ドキュメント内のパスは相対パスで書く
- **プロンプト原文を含む生成物**: `runs/*.jsonl`・`runs/artifacts/`・`datasets/`
  → gitignore 済み。除外を外さない・強制追加（`git add -f`）しない

**コミット前の確認を必ず行う**: `git diff --cached` を目視し、
`git grep -iE "sk-ant|/Users/"` 等で漏れがないか検査してから push する。

## プロジェクト概要

ローカルLLM（LM Studio）と Claude（サブスク経由 `claude -p`）のオーケストレーションを
「Claude 単独」と同一タスク・同一指示で計測比較する評価ハーネス。
全体像・設計・ロードマップの入口は `docs/ARCHITECTURE.md`（変更前に必読）。

- 計測ルール（隠しテスト・予算キャップ・append-only ログ等）は `docs/ARCHITECTURE.md` の
  「不変の計測ルール」に従う。変える場合は文書ごと更新する
- ログスキーマは `docs/DESIGN-telemetry.md`、データセットは `docs/DESIGN-dataset.md` が正
- 新しいアイデアは実装せず `docs/RESEARCH-BACKLOG.md` に追記する（本線は計測基盤とデータ基盤）
- このプロジェクトは学習目的。中核ロジック（ルーター等）は所有者が自分で書くので、
  大きな実装を勝手に進めず、設計・レビュー・小さな雛形の提供に留める
