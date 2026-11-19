"""拆搭题库判卷机：拿数学大脑(rank_candidates)做题库的卷子。

多题库分层判卷：
  teaching  教学字幕提取的人类标准答案（v1 21题，最权威）
  prolog    天凤凤凰桌强手实战弃牌（量大，含riichi残留噪声，已滤镜）
  synthetic 自标注回归库（考引擎自身稳定性，非人类教学）
判级：PASS / TIE-PASS（答案在榜首等价组内，判据与军师显示同源）/ FAIL
用法：python3 -I scripts/taatsu_quiz.py [--sample-prolog N] [--sample-syn N]
"""
import argparse
import json
import os
import random
import sys

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.core.tiles import GameState, parse_tile           # noqa: E402
from src.decision.ev import rank_candidates               # noqa: E402

BANKS = {
    "teaching": os.path.join(REPO, "data", "banks", "taatsu-bank-v1.jsonl"),
    "prolog": os.path.join(REPO, "data", "banks", "taatsu-bank-prolog.jsonl"),
    "synthetic": os.path.join(REPO, "data", "banks", "taatsu-bank-synthetic.jsonl"),
}


def load(path):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def grade(problem, *, samples=64, seed=0):
    state = GameState(my_hand=[parse_tile(t) for t in problem["hand"]])
    for seat, river in (problem.get("rivers") or {}).items():
        state.discards[seat] = [parse_tile(t) for t in river]
    ranked = rank_candidates(state, samples=samples, seed=seed)
    top = ranked[0]
    alts = set(problem.get("alt_ok", [])) | {problem["answer"]}
    if str(top.tile) in alts:
        return "PASS", top, ranked
    peers = [c for c in ranked
             if c.stand_shanten == top.stand_shanten
             and abs(c.ev - top.ev) < 0.05
             and abs(c.exp_neff_1ply - top.exp_neff_1ply) < 2.0]
    if any(str(c.tile) in alts for c in peers):
        return "TIE-PASS", top, ranked
    return "FAIL", top, ranked


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample-prolog", type=int, default=300)
    ap.add_argument("--sample-syn", type=int, default=0,
                    help="合成库抽样量（0=本轮不跑）")
    ap.add_argument("--samples", type=int, default=64)
    args = ap.parse_args()

    rng = random.Random(7)
    picks = {"teaching": load(BANKS["teaching"])}  # 教学库全量
    if args.sample_prolog:
        bank = load(BANKS["prolog"])
        picks["prolog"] = rng.sample(bank, min(args.sample_prolog, len(bank))) if bank else []
    if args.sample_syn:
        bank = load(BANKS["synthetic"])
        picks["synthetic"] = rng.sample(bank, min(args.sample_syn, len(bank))) if bank else []

    print("=" * 62)
    for tier, problems in picks.items():
        if not problems:
            if tier == "teaching":
                print("!! 教学库缺失"); return 1
            continue
        stats = {"PASS": 0, "TIE-PASS": 0, "FAIL": 0}
        fails = []
        for p in problems:
            verdict, top, ranked = grade(p, samples=args.samples)
            stats[verdict] += 1
            if verdict == "FAIL" and tier != "synthetic":
                rank = next((i for i, c in enumerate(ranked)
                             if str(c.tile) == p["answer"]), -1)
                fails.append(f"    [{p['id']}] 答={p['answer']} 我={top.tile}"
                             f"(向听{top.stand_shanten}) 答案排位{rank + 1 if rank >= 0 else '-'}"
                             f" {'/'.join(p['principles'][:2])}")
        n = len(problems)
        score = (stats["PASS"] + stats["TIE-PASS"]) / n
        print(f"[{tier}] {n} 题: PASS {stats['PASS']} TIE {stats['TIE-PASS']} "
              f"FAIL {stats['FAIL']}  → 得分 {score:.0%}")
        for f in fails[:8]:
            print(f)
        if len(fails) > 8:
            print(f"    …另 {len(fails) - 8} 题分歧略")
        print("-" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
