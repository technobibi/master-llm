from config import MAX_RETRIES


def fetch(url):
    for _ in range(MAX_RETRIES):
        pass
    return url
