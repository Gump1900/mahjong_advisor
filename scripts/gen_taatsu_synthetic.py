"""合成拆搭题生成器：随机发牌 → 数学大脑精确标注 → 回归题库。

这些题考的是"引擎自己的最优"（自标注），用途是回归/压测/未来校准训练，
不是人类教学（教学题在 taatsu-bank-v1.jsonl 与牌谱题 taatsu-bank-prolog.jsonl）。
用法：python3 -I scripts/gen_taatsu_synthetic.py [题数=1000] [seed=20261116]
"""
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.core.tiles import GameState, parse_tile           # noqa: E402
from src.decision.ev import rank_candidates               # noqa: E402

OUT = os.path.join(REPO, "data", "banks", "taatsu-bank-synthetic.jsonl")

# 120 张可打牌墙：万饼条各9×4 + 南西北各4（本变体中发白东是花牌，不入决策手牌）
WALL = [f"{v}{s}" for s in ("万", "饼", "条") for v in range(1, 10) for _ in range(4)] \
     + [h for h in ("南风", "西风", "北风") for _ in range(4)]


def gen_problem(rng, idx):
    wall = list(WALL)
    rng.shuffle(wall)
    hand14 = wall[:14]
    state = GameState(my_hand=[parse_tile(t) for t in hand14])
    ranked = rank_candidates(state, samples=64, seed=idx)
    top = ranked[0]
    peers = [str(c.tile) for c in ranked
             if c is not top
             and c.stand_shanten == top.stand_shanten
             and abs(c.ev - top.ev) < 0.05
             and abs(c.exp_neff_1ply - top.exp_neff_1ply) < 2.0]
    return {
        "id": f"SYN-{idx:05d}",
        "tier": "synthetic",
        "scope": "universal",
        "source": "self-labeled",
        "hand": hand14,
        "answer": str(top.tile),
        "alt_ok": peers[:3],
        "principles": [f"shanten{top.stand_shanten}"],
        "reconstructed": False,
    }


def main(count=1000, seed=20261116):
    rng = random.Random(seed)
    with open(OUT, "w", encoding="utf-8") as fh:
        for i in range(count):
            fh.write(json.dumps(gen_problem(rng, i), ensure_ascii=False) + "\n")
            if (i + 1) % 200 == 0:
                print(f"  {i + 1}/{count}")
    print(f"合成题库已生成：{OUT}（{count} 题）")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 1000,
         int(sys.argv[2]) if len(sys.argv) > 2 else 20261116)
