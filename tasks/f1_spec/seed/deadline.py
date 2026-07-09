def mark(tasks, today):
    # tasks: [{'name':..., 'due':int or None}], today:int
    # 期限切れ (due < today) の name の先頭に '[期限切れ]' を付けて返す
    return [t['name'] for t in tasks]
