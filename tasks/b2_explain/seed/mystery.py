def f(n):
    a = [True] * (n + 1)
    a[0] = a[1] = False
    for i in range(2, int(n ** 0.5) + 1):
        if a[i]:
            for j in range(i * i, n + 1, i):
                a[j] = False
    return [i for i, v in enumerate(a) if v]
