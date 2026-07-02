"""実行ごとに、まっさらな作業コピーを用意する。

各実行が独立した初期状態から始まるので、実行同士が汚染し合わない。
（git を使わず、seed/ を temp ディレクトリへコピーするだけの単純な方式）
"""
import os
import shutil
import tempfile


def fresh_workspace(task) -> str:
    """task の seed/ を使い捨ての temp ディレクトリへコピーし、そのパスを返す。"""
    seed = os.path.join(task.dir, "seed")
    tmp = tempfile.mkdtemp(prefix=f"mllm_{task.id}_")
    if os.path.isdir(seed):
        shutil.copytree(seed, tmp, dirs_exist_ok=True)
    return tmp


def cleanup(path: str) -> None:
    shutil.rmtree(path, ignore_errors=True)
