"""tasks/*/task.yaml を読み込んで Task のリストを返す。

tasks/<id>/ に task.yaml・seed/・tests/ を置けば自動で認識される。
"""
import os

import yaml

from harness.models import Budget, Task

TASKS_ROOT = os.path.dirname(os.path.abspath(__file__))


def load_tasks():
    tasks = []
    for name in sorted(os.listdir(TASKS_ROOT)):
        d = os.path.join(TASKS_ROOT, name)
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
