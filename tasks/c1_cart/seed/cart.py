def total(items):
    s = 0
    for i in range(len(items) - 1):        # bug1: 最後の要素を数えない
        s += items[i]
    return s


def apply_discount(price, rate):
    return price + price * rate            # bug2: 割引なのに加算している


def add_item(item, items=[]):              # bug3: 可変デフォルト引数
    items.append(item)
    return items
