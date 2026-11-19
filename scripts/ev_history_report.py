"""Read-only: run the EV math core over the 20 historical public cases.

Writes a descriptive JSON report (runs/ev-history/<date>-report.json). The
casebook has no gold answers; this report shows whether the EV layer
produces decisive, labeled separations between the paired candidates —
it is evidence for humans to inspect, not a pass/fail gate.
"""
import glob
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.decision.ev import rank_candidates          # noqa: E402
from src.decision.ev_bot import EVBot, build_state_from_observation  # noqa: E402

CASES = "runs/strategy-cases/taihu-history-v1-20261025/public/*.json"
SAMPLES = 64


def main() -> int:
    entries = []
    for path in sorted(glob.glob(CASES)):
        case = json.load(open(path, encoding="utf-8"))
        obs = case["input"]
        entry = {"case_id": case["case_id"], "category": case["category"]}
        try:
            state = build_state_from_observation(obs)
            ranked = rank_candidates(state, samples=SAMPLES, seed=0)
            bot = EVBot("均衡", samples=SAMPLES, seed=0)
            choice = bot.choose(obs)
            entry["choice"] = {"kind": None, "tile": None}
            for action in obs["legal_actions"]:
                if action["id"] == choice.action_id:
                    entry["choice"] = {"kind": action["kind"],
                                       "tile": action["tiles"][0] if action["tiles"] else None}
                    break
            entry["top3"] = [{
                "tile": c.tile and str(c.tile),
                "ev": round(c.ev, 3),
                "p_win_next": round(c.p_win_next, 3),
                "v_win": round(c.v_win, 1),
                "p_point": round(c.p_point, 3),
                "p_lo": round(c.p_lo, 3), "p_hi": round(c.p_hi, 3),
                "v_deal": round(c.v_deal, 1),
                "n_eff": round(c.exp_neff_1ply, 1),
            } for c in ranked[:3]]
            entry["ok"] = True
        except Exception as exc:  # noqa: BLE001 - descriptive report
            entry["ok"] = False
            entry["error"] = str(exc)
        entries.append(entry)
        status = "ok" if entry["ok"] else f"ERROR: {entry.get('error')}"
        top = entry.get("top3", [])
        top_desc = " | ".join(
            f"{t['tile']} ev={t['ev']} p={t['p_point']} lo/hi={t['p_lo']}/{t['p_hi']}"
            for t in top) if top else ""
        print(f"{entry['case_id']} [{entry['category']}] {status} "
              f"choice={entry.get('choice')} :: {top_desc}")

    out_dir = "runs/ev-history"
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{date.today()}-report.json")
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump({"samples": SAMPLES, "seed": 0, "entries": entries},
                  fh, ensure_ascii=False, indent=2)
    ok = sum(1 for e in entries if e["ok"])
    print(f"\n{ok}/{len(entries)} cases produced EV receipts -> {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
