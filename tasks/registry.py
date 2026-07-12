"""tasks*/ 配下の task.yaml を読み込んで Task のリストを返す。

主な供給源は公開ベンチの取り込み（tasks_humaneval/ tasks_mbpp/。インポーターで生成）。
tasks/<id>/ に task.yaml・seed/・tests/ を置けば手作りタスクも自動認識される
（自作スイートは 2026-07-12 廃止。実体は git 履歴に残存）。
"""
import os

import yaml

from harness.models import Budget, Task

TASKS_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(TASKS_ROOT)
# tasks_humaneval/ 等 = 公開ベンチの取り込み(gitignore)。tasks_ui/ は廃止済み（欠損時は自動スキップ）
TASK_ROOTS = [TASKS_ROOT,
              os.path.join(_PROJECT_ROOT, "tasks_ui"),
              os.path.join(_PROJECT_ROOT, "tasks_humaneval"),
              os.path.join(_PROJECT_ROOT, "tasks_mbpp")]


def load_tasks():
    tasks = []
    entries = []
    for root in TASK_ROOTS:
        if os.path.isdir(root):
            entries += [os.path.join(root, n) for n in sorted(os.listdir(root))]
    for d in entries:
        meta = os.path.join(d, "task.yaml")
        if not os.path.isfile(meta):
            continue
        with open(meta) as f:
            spec = yaml.safe_load(f)
        b = spec.get("budget", {}) or {}
        tasks.append(Task(
            id=spec["id"],
            category=spec["category"],
            prompt=spec["prompt"],
            target_file=spec.get("target_file", "") or "",
            dir=d,
            budget=Budget(
                max_cost_usd=b.get("max_cost_usd", 2.00),
                max_turns=b.get("max_turns", 40),
                max_wall_s=b.get("max_wall_s", 600.0),
            ),
            tier=spec.get("tier", "low"),
            scoring=spec.get("scoring", "pytest"),
            holdout=spec.get("holdout", False),
            variant_of=spec.get("variant_of"),
            modality=spec.get("modality", "text"),
            answer_file=spec.get("answer_file"),
        ))
    return tasks
