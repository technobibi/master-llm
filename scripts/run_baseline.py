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

def _done_task_ids(arm: str) -> set:
    """同じ arm（local_agent はさらに同じ agent_version）で記録済みのタスク集合。"""
    done = set()
    if not os.path.isfile(config.RUNS_FILE):
        return done
    with open(config.RUNS_FILE) as f:
        for line in f:
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("arm") != arm:
                continue
            if arm == "local_agent" and \
               r.get("env", {}).get("agent_version") != agent.AGENT_VERSION:
                continue  # 器が変わったら再計測の対象（版の違いは比較で使う）
            done.add(r.get("task"))
    return done


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
                    choices=["local_agent", "local_only", "mock"],
                    help="クラウドは対象外（run_bench で少数・日分割で行う）")
    ap.add_argument("--batch", type=int, default=30, help="この起動で回す問数（既定30）")
    ap.add_argument("--order", choices=["diverse", "registry"], default="diverse",
                    help="diverse=埋め込みの farthest-point / registry=登録順")
    ap.add_argument("--category", default=None, help="カテゴリで絞る（例: humaneval）")
    ap.add_argument("--dry-run", action="store_true", help="選択結果の表示のみ（実行しない）")
    args = ap.parse_args()

    tasks = load_tasks()
    if args.category:
        tasks = [t for t in tasks if t.category == args.category]
    done = _done_task_ids(args.arm)
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

    est = len(batch_tasks) * 60
    print(f"このバッチ: {len(batch_tasks)} 問（概算 {est // 60} 分）")
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
              f"tests {res.tests_passed}/{res.tests_total} {res.wall_s:6.1f}s{cap}")

    remaining = len(cands) - len(batch_tasks)
    print(f"\nバッチ完了: 成功 {ok}/{len(batch_tasks)}  残り {remaining} 問"
          f"（続きは同じコマンドをもう一度）")


if __name__ == "__main__":
    main()
