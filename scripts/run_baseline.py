"""ベースライン計測をバッチで少しずつ進める実行スクリプト。

616タスク全量を一気に回すと数時間かかるため:
  - 1回の起動で --batch 件（既定30 ≒ 30分）だけ実行して止まる
  - 実行済みタスク（同じ arm・同じ agent_version の記録が runs.jsonl にある）は自動スキップ
    → 何度でも起動すれば続きから進む（再開可能）
  - 選択順は「埋め込みベクトルの farthest-point」: 実行済み+選択済みから最も遠い
    タスクを貪欲に選ぶ。似たタスクは後のバッチに回るので、途中で止めても
    タスク空間を広くカバーしたデータになる（DESIGN-router §8 の task_vectors も同時に記録）

例:
  ./.venv/bin/python -m scripts.run_baseline --arm local_agent            # 30問だけ
  ./.venv/bin/python -m scripts.run_baseline --arm local_agent --batch 50
  ./.venv/bin/python -m scripts.run_baseline --arm local_agent --dry-run  # 選択だけ見る
"""
import argparse
import json
import math
import os
from datetime import datetime, timezone

import requests

from harness import agent, config
from harness.runner import run_task
from tasks.registry import load_tasks


# ---------- 実行済み判定（再開の要） ----------

def _runs(arm: str):
    """runs.jsonl から該当 arm の行を返す（壊れた行は読み飛ばす）。"""
    if not os.path.isfile(config.RUNS_FILE):
        return
    with open(config.RUNS_FILE) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("arm") == arm:
                yield r


def _done_task_ids(arm: str) -> set:
    """同じ条件で記録済みのタスク集合。local_agent/local_only は同じ local_model
    （local_agent はさらに同じ agent_version）、cloud_only は同じ cloud_model の
    行だけを「済み」と数える（器・モデルが変われば再計測）。"""
    done = set()
    for r in _runs(arm):
        env = r.get("env", {})
        if arm in ("local_agent", "local_only") and env.get("local_model") != config.LOCAL_MODEL:
            continue
        if arm == "local_agent" and env.get("agent_version") != agent.AGENT_VERSION:
            continue
        if arm == "cloud_only" and env.get("cloud_model") != config.CLOUD_MODEL:
            continue
        done.add(r.get("task"))
    return done


def _local_pair_results() -> dict:
    """1:1 ミラー用: local_agent（現行版・現行 LOCAL_MODEL）の task → success。
    失敗ペアを優先するのに使う。"""
    res = {}
    for r in _runs("local_agent"):
        env = r.get("env", {})
        if env.get("agent_version") != agent.AGENT_VERSION:
            continue
        if env.get("local_model") != config.LOCAL_MODEL:
            continue
        if r.get("category") == "swebench":
            continue  # SWE-bench は run_swebench 側で対で扱う
        res[r["task"]] = bool(r.get("success")) or res.get(r["task"], False)
    return res


# ---------- タスク埋め込み（キャッシュ付き） ----------

def _load_vectors() -> dict:
    vecs = {}
    if os.path.isfile(config.TASK_VECTORS_FILE):
        with open(config.TASK_VECTORS_FILE) as f:
            for line in f:
                try:
                    r = json.loads(line)
                    if r.get("model") == config.EMBED_MODEL:
                        vecs[r["task"]] = r["vec"]
                except (json.JSONDecodeError, KeyError):
                    continue
    return vecs


def _embed_missing(tasks, vecs: dict) -> dict:
    """未埋め込みのタスク指示文を LM Studio /v1/embeddings でベクトル化して追記保存。"""
    missing = [t for t in tasks if t.id not in vecs]
    if not missing:
        return vecs
    print(f"[embed] {len(missing)} 件をベクトル化（{config.EMBED_MODEL}）")
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    parent = os.path.dirname(config.TASK_VECTORS_FILE)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(config.TASK_VECTORS_FILE, "a") as out:
        for i in range(0, len(missing), 32):
            chunk = missing[i:i + 32]
            resp = requests.post(
                f"{config.LOCAL_BASE_URL}/embeddings",
                json={"model": config.EMBED_MODEL,
                      "input": [t.prompt for t in chunk]},
                timeout=120,
            )
            resp.raise_for_status()
            for t, d in zip(chunk, resp.json()["data"]):
                vecs[t.id] = d["embedding"]
                out.write(json.dumps({"task": t.id, "model": config.EMBED_MODEL,
                                      "dim": len(d["embedding"]), "vec": d["embedding"],
                                      "ts": ts}) + "\n")
    return vecs


# ---------- farthest-point 選択 ----------

def _norm(v):
    return math.sqrt(sum(x * x for x in v)) or 1.0


def _cos_dist(a, b, na, nb):
    return 1.0 - sum(x * y for x, y in zip(a, b)) / (na * nb)


def _select_diverse(cands, done_vecs, vecs, batch: int):
    """実行済み＋選択済みの集合から最も遠いタスクを貪欲に選ぶ（max-min 距離）。"""
    norms = {tid: _norm(v) for tid, v in vecs.items()}
    # 各候補の「集合への最短距離」を持ち、選ぶたびに更新する（O(batch × 候補数)）
    mind = {}
    for t in cands:
        v, n = vecs[t.id], norms[t.id]
        if done_vecs:
            mind[t.id] = min(_cos_dist(v, vecs[d], n, norms[d]) for d in done_vecs)
        else:
            mind[t.id] = float("inf")  # 実行済みが無ければ最初はどれでもよい
    picked = []
    pool = list(cands)
    while pool and len(picked) < batch:
        best = max(pool, key=lambda t: mind[t.id])
        picked.append(best)
        pool.remove(best)
        bv, bn = vecs[best.id], norms[best.id]
        for t in pool:  # 新しく選んだ点までの距離で最短距離を締める
            d = _cos_dist(vecs[t.id], bv, norms[t.id], bn)
            if d < mind[t.id]:
                mind[t.id] = d
    return picked


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--arm", default="local_agent",
                    choices=["local_agent", "local_only", "mock", "cloud_only"],
                    help="cloud_only は 1:1 ミラー（local_agent 実行済みの問だけを同条件で回す）")
    ap.add_argument("--batch", type=int, default=30, help="この起動で回す問数（既定30）")
    ap.add_argument("--order", choices=["diverse", "registry"], default="diverse",
                    help="diverse=埋め込みの farthest-point / registry=登録順")
    ap.add_argument("--category", default=None, help="カテゴリで絞る（例: humaneval）")
    ap.add_argument("--yes-cloud", action="store_true",
                    help="cloud_only の実行に必須（サブスク枠を消費する自覚の明示）")
    ap.add_argument("--dry-run", action="store_true", help="選択結果の表示のみ（実行しない）")
    args = ap.parse_args()

    tasks = load_tasks()
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]
    done = _done_task_ids(args.arm)

    if args.arm == "cloud_only":
        # 1:1 ミラー: ローカル（現行版）で結果があり、クラウド（現行モデル）が未の問だけ。
        # 「ローカル失敗」ペアを先に回す — 失敗帰属 2×2（DESIGN-router §5）で最も情報量が多い
        if not args.dry_run and not args.yes_cloud:
            raise SystemExit("cloud_only はサブスク枠を消費します。意図的なら --yes-cloud を付けてください。")
        local = _local_pair_results()
        cands = [t for t in tasks if t.id in local and t.id not in done]
        cands.sort(key=lambda t: (local[t.id], t.id))  # False（ローカル失敗）が先
        n_fail = sum(1 for t in cands if not local[t.id])
        est = 0.7 * min(args.batch, len(cands))
        print(f"1:1 ミラー対象 {len(cands)} 問（うちローカル失敗 {n_fail} を優先）"
              f" / cloud={config.CLOUD_MODEL} / このバッチのAPI換算 概算 ${est:.0f}（実支払$0）")
        batch_tasks = cands[: args.batch]
        if not batch_tasks:
            print("ミラー対象がありません（先に local_agent のバッチを進めてください）。")
            return
        _print_and_run(batch_tasks, args, len(cands))
        return

    cands = [t for t in tasks if t.id not in done]
    print(f"全 {len(tasks)} 問中 実行済み {len(tasks) - len(cands)} / 残り {len(cands)}"
          f"（arm={args.arm}, agent={agent.AGENT_VERSION}）")
    if not cands:
        print("残りはありません。")
        return

    if args.order == "diverse":
        try:
            vecs = _embed_missing(tasks, _load_vectors())
            done_vecs = [tid for tid in done if tid in vecs]
            batch_tasks = _select_diverse(cands, done_vecs, vecs, args.batch)
        except requests.RequestException as e:
            print(f"[warn] 埋め込みが使えないため登録順で実行: {e}")
            batch_tasks = cands[: args.batch]
    else:
        batch_tasks = cands[: args.batch]

    _print_and_run(batch_tasks, args, len(cands))


def _print_and_run(batch_tasks, args, n_candidates: int):
    print(f"このバッチ: {len(batch_tasks)} 問（ローカル概算 {len(batch_tasks)} 分）")
    for t in batch_tasks:
        print(f"  {t.id:<28} {t.category}")
    if args.dry_run:
        return

    ok = 0
    for i, task in enumerate(batch_tasks, 1):
        res = run_task(task, args.arm, 0)
        ok += 1 if res.success else 0
        flag = "ok  " if res.success else "FAIL"
        cap = f" (cap:{res.cap_reason})" if res.hit_cap else ""
        print(f"[{flag}] {i:3d}/{len(batch_tasks)} {task.id:<28} "
              f"tests {res.tests_passed}/{res.tests_total} {res.wall_s:6.1f}s "
              f"$eq{res.api_equiv_usd:.4f}{cap}")

    remaining = n_candidates - len(batch_tasks)
    print(f"\nバッチ完了: 成功 {ok}/{len(batch_tasks)}  残り {remaining} 問"
          f"（続きは同じコマンドをもう一度）")


if __name__ == "__main__":
    main()
