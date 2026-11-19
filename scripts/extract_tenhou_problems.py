"""天凤凤凰桌牌谱 → 拆搭题库提取器。

输入：houou-logs export 导出的天凤 XML 牌谱目录
输出：data/banks/taatsu-bank-prolog.jsonl（tier=prolog，答案=强者实战弃牌）

提取规则（保证题目是"纯效率"可迁移的）：
  - 该家无副露无立直、手牌完整可从初始手牌推演（14张决策点）
  - 自己的第≤6次摸牌（前期效率阶段）
  - 手牌不含花牌位（东南西北中发白里我们的花=东南中发白）→ 无花牌手牌
  - 手牌不含赤5（宝牌价值扭曲）且不与宝牌指示牌相邻（宝牌滤镜：含宝牌或字宝牌局整题剔除）
用法：python3 -I scripts/extract_tenhou_problems.py <xml目录> [输出路径] [最大题数]
"""
import glob
import json
import os
import sys
import xml.etree.ElementTree as ET

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

DEFAULT_OUT = os.path.join(REPO, "data", "banks", "taatsu-bank-prolog.jsonl")

SUITS = "万饼条"
FLOWERS = {"东", "中", "发", "白"}          # 本变体花牌（北/南/西可打，但我们只用南西北…见下）
HONOR_NAMES = ["东", "南风", "西风", "北风", "中", "发", "白"]
# 注：天凤的西/北可打；我们的变体同样可打。东/中/发/白是我们的花牌 → 剔题。


def tile_str(t: int) -> str:
    if t < 108:
        suit = t // 36
        v = t % 36 // 4 + 1
        return f"{v}{SUITS[suit]}"
    return HONOR_NAMES[(t - 108) // 4]


def is_red5(t: int) -> bool:
    return t in (16, 52, 88)               # 赤5万/饼/条


def dora_of(indicator: int):
    """指示牌的宝牌（None=字宝牌，调用方整题剔除）。"""
    if indicator < 108:
        suit, v = indicator // 36, indicator % 36 // 4 + 1
        return (suit, 1 if v == 9 else v + 1)
    return None


DRAW_TAGS = {ord("T"): 0, ord("U"): 1, ord("V"): 2, ord("W"): 3,
             ord("t"): 0, ord("u"): 1, ord("v"): 2, ord("w"): 3}
DISCARD_TAGS = {ord("D"): 0, ord("E"): 1, ord("F"): 2, ord("G"): 3,
                ord("d"): 0, ord("e"): 1, ord("f"): 2, ord("g"): 3}


def extract_game(xml_path):
    """根层平铺事件流：INIT 开新局，AGARI/RYUUKYOKU 收局。"""
    problems = []
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError:
        return problems
    rates = dans = None
    game_id = os.path.basename(xml_path).rsplit(".", 1)[0]
    state = None
    for ev in root:
        tag = ev.tag
        if tag == "UN":
            if ev.get("rate"):
                rates = [float(x) for x in ev.get("rate").split(",")]
                dans = [int(x) for x in ev.get("dan").split(",")]
        elif tag == "INIT":
            state = new_kyoku(ev, game_id, rates, dans)
        elif tag in ("AGARI", "RYUUKYOKU"):
            if state:
                problems.extend(state.pop("sink"))
            state = None
        elif state is not None:
            step_kyoku(state, ev, tag)
    return problems


def new_kyoku(init, game_id, rates, dans):
    seed_parts = (init.get("seed") or "").split(",")
    kyoku = seed_parts[0] if seed_parts else "?"
    # 此导出格式 seed=6字段，宝牌指示牌在第6位（0-135）；旧4字段格式在第4位
    try:
        indicator = int(seed_parts[5]) if len(seed_parts) >= 6 else (
            int(seed_parts[3]) if len(seed_parts) >= 4 else -1)
    except ValueError:
        indicator = -1
    raw_hands = {i: (init.get(f"hai{i}") or "") for i in range(4)}
    if not all(raw_hands[i] for i in range(4)):
        return None                            # 三麻（hai3为空）跳过：策略不可迁移
    return {
        "game_id": game_id, "kyoku": kyoku, "dora": dora_of(indicator),
        "hands": {i: [int(x) for x in raw_hands[i].split(",")] for i in range(4)},
        "riichi": [False] * 4, "melded": [False] * 4,
        "draw_count": [0] * 4, "rivers": [[] for _ in range(4)],
        "pending": [None] * 4, "sink": [],
        "rates": rates, "dans": dans,
    }


def step_kyoku(state, ev, tag):
    if tag == "N":
        state["melded"][int(ev.get("who"))] = True
        return
    if tag == "REACH":
        state["riichi"][int(ev.get("who"))] = True
        return
    if tag[0] in "TUVWtuvw" and tag[1:].isdigit():
        seat = DRAW_TAGS[ord(tag[0])]
        tile = int(tag[1:])
        state["hands"][seat].append(tile)
        state["pending"][seat] = tile
        state["draw_count"][seat] += 1
        return
    if tag[0] in "DEFGrdefg" and tag[1:].isdigit():
        seat = DISCARD_TAGS[ord(tag[0])]
        tile = int(tag[1:])
        st = state
        if st["pending"][seat] is None:
            return                              # 副露后的弃牌：手牌推演已断
        hand14 = list(st["hands"][seat])
        if (not st["melded"][seat] and not st["riichi"][seat]
                and len(hand14) == 14 and st["draw_count"][seat] <= 6
                and not any(is_red5(t) for t in hand14)):
            strs = [tile_str(t) for t in hand14]
            flowerish = {s for s in strs if s in FLOWERS}
            dora = st["dora"]
            dora_s = dora and f"{dora[1]}{SUITS[dora[0]]}"
            if (not flowerish and (dora is None or dora_s not in strs)):
                st["sink"].append(make_problem(
                    st, seat, st["draw_count"][seat], strs, tile_str(tile)))
        st["hands"][seat].remove(tile)
        st["rivers"][seat].append(tile)
        st["pending"][seat] = None
def make_problem(st, seat, turn, hand_strs, answer):
    # 河​里只保留可读张（万饼条+南西北）；花牌位对读牌层无意义，赤5按普通5并入
    river_map = {
        f"p{other}": [tile_str(t) for t in st["rivers"][other]
                      if tile_str(t) not in FLOWERS]
        for other in range(4) if other != seat and st["rivers"][other]
    }
    meta = {"game_id": st["game_id"], "kyoku": st["kyoku"],
            "turn": turn, "seat": seat}
    if st["rates"]:
        meta["rate"] = st["rates"][seat]
    if st["dans"]:
        meta["dan"] = st["dans"][seat]
    return {
        "id": f"{st['game_id'][:12]}-k{st['kyoku']}-s{seat}-t{turn}",
        "tier": "prolog", "scope": "efficiency",
        "source": "tenhou-houou(凤凰桌实战)",
        "hand": hand_strs, "answer": answer, "alt_ok": [],
        "principles": ["强手实战"],
        "reason": f"凤凰桌R{meta.get('rate', '?')} 第{turn}巡实战弃牌",
        "rivers": river_map, "meta": meta, "reconstructed": False,
    }


def main(xml_dir, out_path=DEFAULT_OUT, max_problems=8000):
    files = sorted(glob.glob(os.path.join(xml_dir, "**", "*.xml"), recursive=True))
    problems = []
    for i, path in enumerate(files):
        problems.extend(extract_game(path))
        if len(problems) >= max_problems:
            break
        if (i + 1) % 50 == 0:
            print(f"  {i + 1}/{len(files)} 局 → {len(problems)} 题")
    problems = problems[:max_problems]
    with open(out_path, "w", encoding="utf-8") as fh:
        for p in problems:
            fh.write(json.dumps(p, ensure_ascii=False) + "\n")
    print(f"牌谱题库：{out_path}（{len(problems)} 题，来自 {min(i + 1, len(files))} 局）")


if __name__ == "__main__":
    main(sys.argv[1],
         sys.argv[2] if len(sys.argv) > 2 else DEFAULT_OUT,
         int(sys.argv[3]) if len(sys.argv) > 3 else 8000)
