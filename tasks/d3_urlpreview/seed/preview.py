import pickle
import subprocess
import urllib.request


def fetch(url):
    return urllib.request.urlopen(url).read()   # vuln1: SSRF（内部URL未ブロック）


def load_cache(blob):
    return pickle.loads(blob)                    # vuln2: 信頼できないpickle


def screenshot(url):
    cmd = "capture " + url
    return subprocess.run(cmd, shell=True)       # vuln3: shell=True へ入力連結
