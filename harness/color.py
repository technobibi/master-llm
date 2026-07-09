"""色の知覚的な近さを静的に測る（Web画面採点の色層）。

CSS の色文字列 → sRGB → CIELAB に変換し、Lab空間のユークリッド距離(ΔE, CIE76)で比較する。
ΔE は「人間が感じる色差」に近い尺度。純粋なRGB距離より知覚に沿う。
（より精密な CIEDE2000 もあるが、粗いしきい値判定には CIE76 で十分。実装も単純で誤りにくい。）
"""
import re

_HEX = re.compile(r"#([0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
_RGB = re.compile(r"rgba?\(([^)]+)\)")


def parse_color(s: str):
    """'#2563eb' や 'rgb(37,99,235)' を (r,g,b) 0-255 に。失敗したら None。"""
    if not s:
        return None
    s = s.strip()
    m = _HEX.match(s)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = _RGB.match(s)
    if m:
        parts = [p.strip() for p in m.group(1).split(",")]
        try:
            return tuple(int(round(float(parts[i]))) for i in range(3))
        except (ValueError, IndexError):
            return None
    return None


def _srgb_to_lab(rgb):
    def lin(c):
        c /= 255.0
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(x) for x in rgb)
    # sRGB(D65) → XYZ
    x = r * 0.4124 + g * 0.3576 + b * 0.1805
    y = r * 0.2126 + g * 0.7152 + b * 0.0722
    z = r * 0.0193 + g * 0.1192 + b * 0.9505
    # 正規化（D65白色点）
    x, y, z = x / 0.95047, y / 1.0, z / 1.08883

    def f(t):
        return t ** (1 / 3) if t > 0.008856 else 7.787 * t + 16 / 116
    fx, fy, fz = f(x), f(y), f(z)
    return (116 * fy - 16, 500 * (fx - fy), 200 * (fy - fz))


def delta_e(c1: str, c2: str):
    """2つの色文字列の ΔE(CIE76)。どちらか解釈不能なら None。"""
    rgb1, rgb2 = parse_color(c1), parse_color(c2)
    if rgb1 is None or rgb2 is None:
        return None
    l1, a1, b1 = _srgb_to_lab(rgb1)
    l2, a2, b2 = _srgb_to_lab(rgb2)
    return ((l1 - l2) ** 2 + (a1 - a2) ** 2 + (b1 - b2) ** 2) ** 0.5


def color_close(actual: str, target: str, threshold: float = 20.0) -> bool:
    """actual が target に知覚的に十分近いか。ΔE<threshold で合格。
    threshold=20 は「見て同系色」程度の緩さ（正確な一致は求めない）。"""
    d = delta_e(actual, target)
    return d is not None and d < threshold
