"""単発モデル応答（テキスト）を実ファイルに反映する最小の「エージェント」。

ローカルの /v1 呼び出しはテキストを返すだけでファイルを編集しない。
単一ファイルタスクなら「応答中の最大のコードブロックを対象ファイルに書く」で足りる。
複数ファイル編集や本格的なツール使用ループは将来の課題。
"""
import os
import re

_CODE_BLOCK = re.compile(r"```(?:[a-zA-Z0-9_+.\-]*)\n(.*?)```", re.DOTALL)


def apply_code(text: str, cwd: str, target_file: str) -> bool:
    """応答から最大のコードブロックを取り出し cwd/target_file に書く。書けたら True。"""
    blocks = _CODE_BLOCK.findall(text)
    if blocks:
        code = max(blocks, key=len).strip()  # 最大ブロック=解とみなす
    else:
        code = text.strip()  # フェンス無しなら全文を解として扱う（ベストエフォート）
    if not code:
        return False

    path = os.path.join(cwd, target_file)
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    with open(path, "w") as f:
        f.write(code + "\n")
    return True
