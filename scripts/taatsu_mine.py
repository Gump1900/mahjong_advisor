"""题库分歧模式挖掘：错题按特征聚类，区分真缺口与规则噪声。

对每道 FAIL 提取特征（我方弃牌 vs 标准答案）：
  - 牌类别：字/幺九/二八/中张
  - 是否拆对（弃牌在手牌里是2+张）
  - 打后手牌对子数
  - 向听差（我方是否退向听）
  - 巡目（t1-2 前期 / t3-6 中前期）
输出模式×计数矩阵 + 每模式两道实例。
用法：python3 -I scripts/taatsu_mine.py [--prolog N]
"""
import argparse
import json
import os
import random
import sys
from collections import Counter, defaultdict

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.core.tiles import GameState, parse_tile           # noqa: E402
from src.decision.ev import rank_candidates               # noqa: E402
from taatsu_quiz import BANKS, load, grade                # noqa: E402


def category(t):
    if t.endswith(("风",)):
        return "字"
    v = int(t[0])
    if v in (1, 9):
        return "幺九"
    if v in (2, 8):
        return "二八"
    return "中张"


def features(problem, top):
    hand = problem["hand"]
    ans = problem["answer"]
    mine = str(top.tile)
    f = {}
    f["我打类别"] = category(mine)
    f["答打类别"] = category(ans)
    f["我拆对"] = "是" if hand.count(mine) >= 2 else "否"
    f["答拆对"] = "是" if hand.count(ans) >= 2 else "否"
    f["退向听"] = "是" if False else "否"     # 榜首按定义不退向听
    f["巡目"] = "前期" if (problem.get("meta", {}).get("turn", 1) <= 2
                          or problem["id"].endswith("t1") or problem["id"].endswith("t2")) else "中前"
    return f


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prolog", type=int, default=300)
    args = ap.parse_args()

    rng = random.Random(7)
    problems = load(BANKS["teaching"])
    bank = load(BANKS["prolog"])
    if bank:
        problems += rng.sample(bank, min(args.prolog, len(bank)))

    patterns = defaultdict(list)
    for p in problems:
        verdict, top, _ = grade(p)
        if verdict != "FAIL":
            continue
        f = features(p, top)
        key = (f["我打类别"] + "→" + f["答打类别"],
               "我拆对" if f["我拆对"] == "是" and f["答拆对"] == "否" else
               ("答拆对" if f["答拆对"] == "是" and f["我拆对"] == "否" else "对等"),
               f["巡目"])
        patterns[key].append(p)

    total_fail = sum(len(v) for v in patterns.values())
    print(f"错题 {total_fail} 道的模式聚类：\n")
    for key, items in sorted(patterns.items(), key=lambda kv: -len(kv[1])):
        cat, pair, phase = key
        print(f"{len(items):>3} 道 | {cat:<9} | {pair:<4} | {phase}")
        for p in items[:2]:
            print(f"       例: {' '.join(p['hand'][:8])}… 答={p['answer']} 差={p['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
