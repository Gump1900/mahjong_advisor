"""EV decision receipts: append-only JSONL per game, reloadable for replay.

Every receipt line: {"game_id", "revision", "candidates": [CandidateEV dicts]}.
Tiles serialize as str(tile) so files stay human-diffable.
"""
import json
import os
from typing import List

from .ev import CandidateEV

DEFAULT_ROOT = "runs/ev-receipts"


def _candidate_to_dict(cand: CandidateEV) -> dict:
    return {
        "tile": str(cand.tile),
        "ev": cand.ev,
        "p_win_next": cand.p_win_next,
        "v_win": cand.v_win,
        "p_point": cand.p_point,
        "p_feed_chi": cand.p_feed_chi,
        "p_next_progress": cand.p_next_progress,
        "p_call_progress": cand.p_call_progress,
        "p_lo": cand.p_lo,
        "p_hi": cand.p_hi,
        "v_deal": cand.v_deal,
        "exp_neff_1ply": cand.exp_neff_1ply,
        "exp_neff_exact": cand.exp_neff_exact,
        "labels": list(cand.labels),
    }


def save_receipt(game_id: str, revision: int, candidates: List[CandidateEV],
                 *, root: str = DEFAULT_ROOT) -> str:
    """Append one decision receipt; returns the file path."""
    os.makedirs(root, exist_ok=True)
    path = os.path.join(root, f"{game_id}.jsonl")
    line = {"game_id": game_id, "revision": revision,
            "candidates": [_candidate_to_dict(c) for c in candidates]}
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, ensure_ascii=False) + "\n")
    return path


def load_receipts(game_id: str, *, root: str = DEFAULT_ROOT) -> List[dict]:
    """All receipts of one game in append order; missing game -> []."""
    path = os.path.join(root, f"{game_id}.jsonl")
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]
