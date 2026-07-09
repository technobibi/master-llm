"""Web画面タスクの静的採点（docs/DESIGN-testplan.md §1 ui-static）。

headless chromium で生成物(index.html)を実際に開き、タスク同梱の採点器
tests/ui_check.py の checks(page) を呼ぶ。checks は (説明, 合否bool) のリストを返す。
機能(クリック→状態変化)・構造(DOM)・色(computed style)を、すべて
プログラム判定（決定的）で行う。LLM採点は使わない。

Playwright 未導入の環境では (0, 0, メッセージ) を返して落とさない（任意依存）。
"""
import importlib.util
import os


def _load_checker(task):
    path = os.path.join(task.dir, "tests", "ui_check.py")
    spec = importlib.util.spec_from_file_location(f"uicheck_{task.id}", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def score_ui(task, cwd: str):
    html = os.path.join(cwd, task.target_file or "index.html")
    if not os.path.isfile(html):
        return 0, 1, f"{task.target_file or 'index.html'} が作られていない"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return 0, 0, "playwright 未導入（pip install playwright && playwright install chromium）"

    try:
        checker = _load_checker(task)
    except (OSError, ImportError) as e:
        return 0, 1, f"採点器 ui_check.py を読めない: {e}"

    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1000, "height": 800})
            page.goto(f"file://{html}", wait_until="load", timeout=15000)
            try:
                results = checker.checks(page)
            finally:
                browser.close()
    except Exception as e:  # レンダリング/検査中の例外は失敗として記録（握りつぶさない）
        return 0, max(len(results), 1), f"UI検査中に例外: {e}"

    passed = sum(1 for _, ok in results if ok)
    log = "\n".join(f"[{'OK' if ok else '--'}] {desc}" for desc, ok in results)
    return passed, len(results), log
