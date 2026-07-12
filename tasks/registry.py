"""tasks/*/task.yaml と tasks_ui/*/task.yaml を読み込んで Task のリストを返す。

tasks/<id>/ に task.yaml・seed/・tests/ を置けば自動認識。
Web画面タスクは tasks_ui/<id>/ に置く（採点に Playwright を使うため分離。DESIGN-testplan §4）。
"""
import os

import yaml

from harness.models import Budget, Task

TASKS_ROOT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(TASKS_ROOT)
# tasks/ = 自作スイート、tasks_ui/ = Web画面、tasks_humaneval/ 等 = 公開ベンチの取り込み(gitignore)
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
