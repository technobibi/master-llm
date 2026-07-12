#!/usr/bin/env python3
"""計測ログ（runs/ + artifacts/）から学習用データセットを生成する。

  python -m scripts.build_dataset --kind routing   --ver 1
  python -m scripts.build_dataset --kind sft       --ver 1
  python -m scripts.build_dataset --kind ambiguity --ver 1

原則（docs/DESIGN-dataset.md が正）:
- ログが正、データセットは派生。ここは読み取り専用でログを一切変更しない
- 出力先 datasets/<kind>/v<ver>/ が既にあればエラー（immutable。作り直すなら ver を上げる）
- スキップは黙って捨てず件数を表示する
- mock arm は配管確認なので全データセットから除外
"""
import argparse
import hashlib
import json
import os
from collections import defaultdict
from statistics import median

from harness import agent, config, router
from harness.report import load
from tasks.registry import load_tasks


def _read_artifact(run_id: str, name: str):
    path = os.path.join(config.ARTIFACTS_DIR, run_id, name)
    try:
        with open(path) as f:
            return f.read()
    except OSError:
        return None


def _holdout_ids():
    """holdout=true のタスクID集合。評価専用なので学習データから除外する
    （docs/DESIGN-testplan.md §0-3。ベンチマークへの過適合防止）。"""
    return {t.id for t in load_tasks() if getattr(t, "holdout", False)}


def _v2_rows():
    """schema v2・mock以外・holdout以外の run 行。(v2行, スキップ数) を返す。"""
    hold = _holdout_ids()
    rows = [r for r in load() if r["arm"] != "mock" and r["task"] not in hold]
    v2 = [r for r in rows if r.get("schema", 1) >= 2 and r.get("run_id")]
    return v2, len(rows) - len(v2)


def _write_out(kind: str, ver: int, name: str, records: list) -> str:
    outdir = os.path.join("datasets", kind, f"v{ver}")
    if os.path.exists(outdir):
        raise SystemExit(f"エラー: {outdir} は既に存在します。"
                         "データセットは作り直さず --ver を上げてください（immutable 原則）")
    os.makedirs(outdir)
    path = os.path.join(outdir, name)
    with open(path, "w") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return path


def build_routing(ver: int, local_arm: str = "local_agent"):
    """1行 = 同一 task×rep の local/cloud ペア（反実仮想ラベル）。

    local 側は --local-arm（既定 local_agent = 現行ベースラインの器）。
    器やモデルが変わると能力そのものが変わるため、**現行の agent_version /
    cloud_model の行だけ**でペアを組む（古い版の行は stale としてスキップ・件数表示）。
    同じ (task, rep, side) に複数行あるときは新しい方（ts が大きい方）を使う。
    """
    v2, n_v1 = _v2_rows()
    by_key = defaultdict(dict)
    n_stale = 0
    for r in v2:
        env = r.get("env", {})
        if r["arm"] == local_arm:
            if local_arm == "local_agent" and \
               env.get("agent_version") != agent.AGENT_VERSION:
                n_stale += 1
                continue
            side = "local"
        elif r["arm"] == "cloud_only":
            if env.get("cloud_model") != config.CLOUD_MODEL:
                n_stale += 1
                continue
            side = "cloud"
        else:
            continue
        key = (r["task"], r["rep"])
        prev = by_key[key].get(side)
        if prev is None or r.get("ts", "") > prev.get("ts", ""):
            by_key[key][side] = r

    records, skipped = [], 0
    for (task_id, rep), group in sorted(by_key.items()):
        if "local" not in group or "cloud" not in group:
            skipped += 1
            continue
        lo, cl = group["local"], group["cloud"]
        prompt = _read_artifact(lo["run_id"], "prompt.txt")
        if prompt is None:
            skipped += 1
            continue
        feats = router.extract_features(prompt)
        feats["category"] = lo["category"]
        oracle = min([lo, cl], key=lambda r: (not r["success"], r["wall_s"], r["cloud_out_tok"]))
        records.append({
            "task": task_id, "rep": rep,
            "prompt": prompt,
            "features": feats,
            "local_success": lo["success"], "local_wall_s": lo["wall_s"],
            "cloud_success": cl["success"], "cloud_wall_s": cl["wall_s"],
            "cloud_api_equiv_usd": cl["api_equiv_usd"],
            "oracle_arm": "local" if oracle is lo else "cloud",
            # provenance: どの器・どのモデルのペアかを行に残す（後から混ぜない・選べる）
            "local_arm": local_arm,
            "local_agent_version": lo.get("env", {}).get("agent_version"),
            "cloud_model": cl.get("env", {}).get("cloud_model"),
            "source_run_ids": [lo["run_id"], cl["run_id"]],
        })
    path = _write_out("routing", ver, "pairs.jsonl", records)
    print(f"routing v{ver}: 収録 {len(records)} ペア（local={local_arm}）"
          f" / ペア不成立スキップ {skipped} / 版違いスキップ {n_stale} / v1行スキップ {n_v1}")
    print(f"→ {path}")
    if records:
        print("※ 学習時の注意: train/test は必ず「タスク単位」で分けること（リーク防止。STUDY-3 罠2）")


def build_sft(ver: int):
    """1行 = 成功 run の (指示, seed, 最終diff)。蒸留・自作モデルの教材。"""
    v2, n_v1 = _v2_rows()
    seed_cache = {}
    for t in load_tasks():
        seeds = {}
        seed_dir = os.path.join(t.dir, "seed")
        if os.path.isdir(seed_dir):
            for root, _, files in os.walk(seed_dir):
                for fn in files:
                    p = os.path.join(root, fn)
                    with open(p) as f:
                        seeds[os.path.relpath(p, seed_dir)] = f.read()
        seed_cache[t.id] = seeds

    records, skipped = [], 0
    for r in v2:
        if not r["success"]:
            continue
        prompt = _read_artifact(r["run_id"], "prompt.txt")
        diff = _read_artifact(r["run_id"], "diff.patch")
        if not prompt or not diff or not diff.strip():
            skipped += 1
            continue
        records.append({
            "task": r["task"],
            "prompt": prompt,
            "seed_files": seed_cache.get(r["task"], {}),
            "diff": diff,
            "teacher": "cloud" if r["cloud_out_tok"] > 0 else "local",
            "tests_passed": r["tests_passed"], "tests_total": r["tests_total"],
            "source_run_id": r["run_id"],
        })
    path = _write_out("sft", ver, "pairs.jsonl", records)
    print(f"sft v{ver}: 収録 {len(records)} 件（成功runのみ）/ 原文欠損スキップ {skipped} / v1行スキップ {n_v1}")
    print(f"→ {path}")


def build_ambiguity(ver: int):
    """1行 = 1タスク。指示の曖昧さの代理シグナル（人手ラベルは annotations/ に別管理）。"""
    v2, n_v1 = _v2_rows()
    by_task = defaultdict(list)
    for r in v2:
        by_task[r["task"]].append(r)

    task_prompts = {t.id: t.prompt for t in load_tasks()}
    records = []
    for task_id, rs in sorted(by_task.items()):
        prompt = task_prompts.get(task_id)
        if prompt is None:  # タスク削除済みでも原文は artifacts に残っている
            prompt = _read_artifact(rs[0]["run_id"], "prompt.txt") or ""
        local = [r for r in rs if r["arm"] == "local_only"]
        cloud = [r for r in rs if r["arm"] == "cloud_only"]
        # 逆質問シグナル: 最初の応答に疑問符が含まれるか（粗い代理。原文は残っているので後で精緻化可能）
        asked = False
        for r in rs:
            text = _read_artifact(r["run_id"], "call_0.txt") or ""
            if "?" in text or "？" in text:
                asked = True
                break
        records.append({
            "task": task_id,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "prompt": prompt,
            "reps": len(rs),
            "success_rate_local": (sum(r["success"] for r in local) / len(local)) if local else None,
            "success_rate_cloud": (sum(r["success"] for r in cloud) / len(cloud)) if cloud else None,
            "turns_median": median(r["turns"] for r in rs),
            "asked_clarification": asked,
        })
    path = _write_out("ambiguity", ver, "signals.jsonl", records)
    print(f"ambiguity v{ver}: 収録 {len(records)} タスク / v1行スキップ {n_v1}")
    print(f"→ {path}")
    print("※ 人手ラベルは datasets/annotations/ambiguity.jsonl に追記（DESIGN-dataset.md 参照）")


BUILDERS = {"routing": build_routing, "sft": build_sft, "ambiguity": build_ambiguity}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--kind", required=True, choices=sorted(BUILDERS))
    ap.add_argument("--ver", type=int, required=True)
    ap.add_argument("--local-arm", default="local_agent",
                    choices=["local_agent", "local_only"],
                    help="routing のみ: local 側に使う arm（既定 local_agent）")
    args = ap.parse_args()
    if args.kind == "routing":
        build_routing(args.ver, args.local_arm)
    else:
        BUILDERS[args.kind](args.ver)


if __name__ == "__main__":
    main()
