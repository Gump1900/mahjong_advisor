"""Terminal-only Mahjong faces; never used in state, action IDs or replay data."""
from ..core.tiles import parse_tile

_HONORS_AND_FLOWERS = {
    "东风": 0x1F000, "南风": 0x1F001, "西风": 0x1F002, "北风": 0x1F003,
    "中": 0x1F004, "发": 0x1F005, "白": 0x1F006,
    "梅": 0x1F022, "兰": 0x1F023, "竹": 0x1F024, "菊": 0x1F025,
    "春": 0x1F026, "夏": 0x1F027, "秋": 0x1F028, "冬": 0x1F029,
}


def tile_face(name, style="unicode", *, with_name=False):
    tile = parse_tile(str(name))
    name = str(tile)
    if style == "text":
        return name
    if style != "unicode":
        raise ValueError("牌面样式须为unicode或text")
    if tile.suit in ("万", "饼", "条"):
        base = {"万": 0x1F007, "条": 0x1F010, "饼": 0x1F019}[tile.suit]
        face = chr(base+int(tile.value)-1)
    else:
        face = chr(_HONORS_AND_FLOWERS[name])
    return f"{face}（{name}）" if with_name else face


def tile_line(names, style="unicode"):
    return " ".join(tile_face(name, style) for name in names)
