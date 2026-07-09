"""G2 TODOリストの静的採点。構造3 / 機能4 = 7チェック。"""


def _has_line_through(el):
    d = el.evaluate("e => getComputedStyle(e).textDecorationLine") or ""
    return "line-through" in d


def checks(page):
    out = []
    inp = page.query_selector("input[type=text]") or page.query_selector("input")
    add = None
    for b in page.query_selector_all("button"):
        t = (b.inner_text() or "").strip()
        if "追加" in t or t.lower() in ("add", "+"):
            add = b
            break

    # 構造
    out.append(("入力欄がある", inp is not None))
    out.append(("追加ボタンがある", add is not None))
    out.append(("リスト表示領域がある",
                bool(page.query_selector("ul, ol") or page.query_selector("[class*=list], [id*=list]"))))

    # 機能: 追加
    added_ok = False
    if inp and add:
        inp.fill("牛乳を買う")
        add.click()
        page.wait_for_timeout(100)
        added_ok = page.get_by_text("牛乳を買う").count() > 0
    out.append(("入力→追加でリストに項目が出る", added_ok))

    # 機能: 2件目追加でリストが増える
    grew_ok = False
    if inp and add and added_ok:
        inp.fill("卵を買う")
        add.click()
        page.wait_for_timeout(100)
        grew_ok = page.get_by_text("卵を買う").count() > 0
    out.append(("2件目も追加できる", grew_ok))

    # 機能: クリックで取り消し線トグル
    strike_ok = False
    if added_ok:
        item = page.get_by_text("牛乳を買う").first
        try:
            item.click()
            page.wait_for_timeout(100)
            strike_ok = _has_line_through(item.element_handle())
        except Exception:
            strike_ok = False
    out.append(("項目クリックで取り消し線が付く", strike_ok))

    # 機能: 残り件数の表示が存在する（数字を含むテキスト）
    import re
    has_count = any(re.search(r"\d", (el.inner_text() or ""))
                    for el in page.query_selector_all("body *")
                    if not el.query_selector("*"))
    out.append(("残り件数らしき数字表示がある", has_count))
    return out
