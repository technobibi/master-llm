import time


class ApiClient:
    def __init__(self, cache={}):          # bug1: 可変デフォルトで全インスタンス共有
        self.cache = cache

    def get(self, key, ttl=60):
        entry = self.cache.get(key)
        if entry and time.time() - entry[0] > ttl:   # bug2: 不等号が逆。期限切れを返す
            return entry[1]
        value = self._fetch(key)
        self.cache[key] = (time.time(), value)
        return value

    def _fetch(self, key):
        return f"value-of-{key}"
