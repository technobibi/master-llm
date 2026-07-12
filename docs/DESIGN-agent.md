# 設計書: ローカル・エージェント（ツール使用ループ）

**目的**: ローカルLLMを「素の単発生成」から「読んで書いて実行して直すエージェント」に上げ、
Claude（`claude -p`）と同じ土俵で計測し、かつ実際に使えるツールにする。
**状態**: **実装済み**（`harness/agent.py`、AGENT_VERSION=local-agent-v3）。
v2: 成果物ができるまで終わらせない解決ループ+保険。
v3: grep・list_files のディレクトリ指定・read_file の行範囲・壁時計の実行時打ち切り
（実リポ=SWE-bench 対応。DESIGN-swebench.md）。

## なぜ必要か

- **計測の公平性**: 従来は「エージェントのClaude」対「素のQwen」で、負けても
  モデルの差か手足の有無かを切り分けられなかった。ローカルもエージェントにして揃える。
- **ツールとしての実用**: 製品ビジョンはローカル/クラウドの振り分けオーケストレータ。
  振り分けた先が編集・実行できなければコーディング支援として機能しない。

## 3つの arm で「エージェント化の効果」を測る

| arm | 中身 | 位置づけ |
|---|---|---|
| `local_only` | 素の単発生成 + seed内容をプロンプト添付 + 構文/スモーク再生成 | 器なしローカルのベースライン |
| `local_agent` | ツール使用ループ（本設計） | 器ありローカル |
| `cloud` | `claude -p`（Claude Code のエージェント） | 製品が使うクラウド側 |

`local_agent` − `local_only` = **器（エージェント化）の効果**。
`cloud` − `local_agent` = 器を揃えた後の**モデルの実力差**（に近いもの）。

> 注意: `cloud` は Claude Code 独自のエージェントで、`local_agent` の器とは別物。
> 完全に同一の器ではない。ただし製品がクラウド側に claude -p を使う以上、これが正しい比較。
> 「器の違い」も含めて製品の実力を測っている、と解釈する。

## エージェントループの仕様

```
system(役割+ツール説明) + user(タスク指示)
  ↓ 繰り返し（最大 AGENT_MAX_STEPS、予算内）
モデルが tool_calls を返す → ハーネスがツール実行 → 結果を tool メッセージで返す
  ↓ モデルが finish を呼ぶ or ツール呼び出し無しのテキスト → 終了
```

### ツール（6つ。すべて作業ディレクトリ内に限定）

| ツール | 引数 | 動作 |
|---|---|---|
| `list_files` | path? | ファイル一覧（隠しテスト・.git は除外。400件で打ち切り→絞り込みを促す） |
| `read_file` | path, start_line?, end_line? | 行番号付きで返す。1回250行まで（大ファイルは範囲指定） |
| `grep` | pattern, path? | 正規表現検索で「ファイル:行番号: 内容」を返す（実リポの当たり付け用） |
| `write_file` | path, content | ファイルを書く（コード編集・BUGS.md 等の解答作成の両方） |
| `run_tests` | — | **公開スモークテスト**を実行して結果を返す |
| `finish` | summary | 完了宣言 |

**★ run_tests は公開スモーク（smoke_test.py）のみ。隠しテスト(tests/)は絶対に触らせない**
（触らせると最終評価へのリーク。DESIGN-testplan §0-1）。report系タスクにスモークは無いので
run_tests は「テスト無し」を返す＝調査系は read/write だけで完結する。

### 安全性

- パスは作業ディレクトリ内に正規化して制限（`../` での外部アクセスを拒否）
- ツール結果は上限文字数で切り詰め（AGENT_TOOL_RESULT_MAX、v3 で 4000→8000）
- ステップ上限 = min(task.budget.max_turns, AGENT_MAX_STEPS)。超えたら打ち切り＝失敗扱い
- 壁時計上限 = task.budget.max_wall_s を**実行時にも**強制（v3。従来は事後判定のみで、
  実リポでは1問が際限なく延びうるため）

## 計測への反映

- `agent_version`（例 `local-agent-v1`）を env スナップショットに記録。
  器を改良したら版を上げ、同じ suite を再実行して器の改良効果を差分で見る
- 1 run = 複数の内部ステップ。集計は cloud と同じく turns=ステップ数、トークンは合算
- 全ステップの生ログ（tool呼び出しと結果）は artifacts に保存（後から迷走を分析できる）

## 実装

- `harness/agent.py`: ループ本体とツール実行
- `harness/arms.py`: `arm_local_agent`
- `harness/config.py`: `AGENT_MAX_STEPS`, `AGENT_VERSION`
- ルーター（`router.py`）がどちらのローカル arm を使うかは所有者の領域（今は local_only のまま）
