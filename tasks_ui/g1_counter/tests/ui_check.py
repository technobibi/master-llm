"""G1 カウンターの静的採点。機能4 / 構造3 / 色2 = 9チェック。"""
import re
from harness.color import color_close

MINUS = {"−", "-", "ー", "－"}
RESET = {"リセット", "reset", "Reset", "RESET", "クリア"}


def _btn(page, pred):
    for b in page.query_selector_all("button"):
        t = (b.inner_text() or "").strip()
        if pred(t):
            return b
    return None


def _num_value(page):
    """整数だけを表示している葉要素の値。見つからなければ None。"""
    for el in page.query_selector_all("body *"):
        if el.query_selector("*"):
            continue  # 子を持つ要素は飛ばす（葉だけ見る）
        t = (el.inner_text() or "").strip()
        if re.fullmatch(r"-?\d+", t):
            return int(t)
    return None


def _bg(el):
    return el.evaluate("e => getComputedStyle(e).backgroundColor") if el else ""


def checks(page):
    out = []
    plus = _btn(page, lambda t: t == "+")
    minus = _btn(page, lambda t: t in MINUS)
    reset = _btn(page, lambda t: t in RESET)

    # 構造
    out.append(("ボタンが3つ以上", len(page.query_selector_all("button")) >= 3))
    out.append(("+ / − / リセット のボタンが揃う", all([plus, minus, reset])))
    out.append(("数値表示がある", _num_value(page) is not None))

    # 機能
    out.append(("初期値が0", _num_value(page) == 0))
    if plus:
        before = _num_value(page)
        plus.click()
        out.append(("+ で1増える", before is not None and _num_value(page) == before + 1))
    else:
        out.append(("+ で1増える", False))
    if minus:
        before = _num_value(page)
        minus.click()
        out.append(("− で1減る", before is not None and _num_value(page) == before - 1))
    else:
        out.append(("− で1減る", False))
    if reset:
        reset.click()
        out.append(("リセットで0に戻る", _num_value(page) == 0))
    else:
        out.append(("リセットで0に戻る", False))

    # 色
    out.append(("+ ボタンが青系", color_close(_bg(plus), "#2563eb")))
    out.append(("リセットが赤系", color_close(_bg(reset), "#dc2626")))
    return out
