# 設計書: SWE-bench 取り込み（実リポ・複数ファイル課題の計測）

**目的**: 自作スイートに無い「実リポジトリ・大規模・複数ファイル」の課題を計測に加える
（[DESIGN-router.md](DESIGN-router.md) §8 の最重要ギャップ）。
**状態**: **v1 実装済み**（`scripts/run_swebench.py`、2026-07-12）。

## データ

- **SWE-bench Lite**（300問・12リポ: django 114 / sympy 77 / matplotlib 23 / scikit-learn 23 /
  pytest 17 / sphinx 16 ほか）。1問 = 実リポの GitHub issue + 正解パッチ + 隠しテスト
- 評価は公式ハーネス（`swebench` パッケージ）の **Docker コンテナ内**で行う:
  モデルのパッチを適用 → `FAIL_TO_PASS`（直せたか）+ `PASS_TO_PASS`（壊してないか）を実行
- Verified（500問・人手検証済み）への拡張は同じ流れで可能（`DATASET` 定数を差し替え）

## 流れ（1インスタンス × 1arm × 1反復 = 1 run）

```
swebench_repos/<repo>.git     ← bare クローンをキャッシュ（初回のみ DL）
        │ ① base_commit で temp へ checkout（まっさら作業コピー）
        ▼
   arm 実行 ②                 gold / local_agent / cloud_only
        │ ③ git diff でパッチ抽出 → predictions.jsonl
        ▼
   swebench Docker 評価 ④     隠しテストはコンテナ内でのみ適用
        │ ⑤ report.json を回収
        ▼
   runs/runs.jsonl ほか       既存スキーマ v2 のまま記録（category="swebench"）
```

- 生成物は `runs/swebench/<batch>/` に閉じる（predictions・評価ログ・レポート。gitignore 済み）
- artifacts には prompt / エージェント全対話 / model_patch.diff を保存（生データ優先の原則）
- **再開可能**: 同条件（同 arm・local は同 agent_version・cloud は同 cloud_model）で記録済みの
  インスタンスは自動スキップ（`--no-skip-done` で強制再実行）

## 計測ルールとの対応（docs/ARCHITECTURE.md「不変の計測ルール」）

| ルール | 対応 |
|---|---|
| 同一タスク・同一指示 | 全 arm 同一プロンプト（issue 本文 + 最小修正の指示のみ） |
| テストは隠す | モデルには problem_statement しか見せない。F2P/P2P はコンテナ内のみ |
| 予算キャップ | runner と同一基準で事後判定。エージェントは実行時にも wall 打ち切り |
| append-only | 既存の runs/calls/artifacts へ追記。スキーマ変更なし |
| 枠消費の保護 | `cloud_only` は `--yes-cloud` を明示したときだけ動く |

## arm

| arm | 中身 | 用途 |
|---|---|---|
| `gold` | 正解パッチを適用するだけ（モデル不要） | 自前パイプライン全体の無料検証（mock と同格） |
| `local_agent` | ローカルのツール使用ループ（agent v3: grep・範囲read） | 無料。ベースライン蓄積の主力 |
| `cloud_only` | `claude -p`（作業コピー内で自律動作） | 枠を消費。少数・日分割で |

## v1 の既知の限界（前提にしない）

- **評価は1問ずつ直列**（Docker）。1問あたり数分。大量に回すときは時間を見込む
- **local の run_tests はスモーク非対応**（SWE-bench にスモークは無い）。ローカルは
  実行確認なしでパッチを書く器になっている。リポの既存テストを叩かせる拡張は
  「クラウドとの対称性」と「リーク」の両面を検討してから（安易に足さない）
- **プロンプトは英語**（issue 原文が英語のため。自作タスクの日本語指示と条件が違う点は
  レポート解釈時に忘れない）
- 30B・32K コンテキストでは大リポの探索でコンテキストが埋まりやすい。失敗も
  ルーティングの学習信号として記録する（それが目的のデータ）

## 使い方

```bash
# 配管の検証（無料・モデル不要）
./.venv/bin/python -m scripts.run_swebench --arm gold --instances pallets__flask-4045

# ローカルエージェントで1問（無料）
./.venv/bin/python -m scripts.run_swebench --arm local_agent --repo flask --limit 1

# クラウドは明示フラグ必須（枠を消費する）
./.venv/bin/python -m scripts.run_swebench --arm cloud_only --instances <id> --yes-cloud
```
