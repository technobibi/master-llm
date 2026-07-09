"""G3 ダッシュボードの静的採点（レイアウト+色）。構造5 / 色1 = 6チェック。
JS無しの静的ページなので機能層は無い。位置は境界ボックスで相対判定する。"""
from harness.color import color_close


def _box(el):
    return el.bounding_box() if el else None


def checks(page):
    out = []
    vw = page.viewport_size["width"]

    # ヘッダー: 上端近く・幅が広い
    header = page.query_selector("header") or page.query_selector("[class*=header], [id*=header]")
    hb = _box(header)
    out.append(("ヘッダーがある", header is not None))
    out.append(("ヘッダーが上部にある", bool(hb and hb["y"] < 100)))
    out.append(("ヘッダーが横に広い", bool(hb and hb["width"] > vw * 0.6)))

    # サイドバー: 左寄り
    side = page.query_selector("aside") or page.query_selector("[class*=side], [id*=side], nav")
    sb = _box(side)
    out.append(("サイドバーが左側にある", bool(sb and sb["x"] < vw * 0.3)))

    # カード3枚
    cards = page.query_selector_all("[class*=card], [id*=card]")
    if len(cards) < 3:
        main = page.query_selector("main") or page.query_selector("[class*=main]")
        if main:
            cards = main.query_selector_all(":scope > *")
    out.append(("カードが3枚以上", len(cards) >= 3))

    # 色: ヘッダー背景が濃紺系
    hbg = header.evaluate("e => getComputedStyle(e).backgroundColor") if header else ""
    out.append(("ヘッダーが濃紺〜青系", color_close(hbg, "#1e293b", threshold=35)))
    return out
