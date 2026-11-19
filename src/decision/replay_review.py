"""Dual-channel replay: decision-time prior receipts vs post-reveal truth.

`truth` maps seat -> concealed tiles at reveal (摊牌)：["9万",...] 或 {"hand":[...],"melds":4}。
True_p is a STRUCTURAL fact (was any truth-hand waiting on the recommended
tile); eligibility flowers are usually unrevealed, so the fact is labeled
`真值:结构`（含资格需完整花观测，bot 局由引擎喂）。truth missing any of the
three seats -> true_p/delta are None（`真值不全`），对照保持先验值。
"""
from typing import Dict, List, Optional

from ..core.hand_analyzer import get_waiting_tiles
from ..core.tiles import parse_tile

OPPONENTS = ("left", "opposite", "right")


def _seat_truth(entry):
    """truth 每家两项格式：["9万", ...] 或 {"hand": [...], "melds": 4}。"""
    if isinstance(entry, dict):
        return [parse_tile(t) for t in entry.get("hand", [])], int(entry.get("melds", 0))
    return [parse_tile(t) for t in (entry or [])], 0


def _structural_ron(truth: Dict[str, object], tile) -> Optional[int]:
    """1 if any truth hand waits on tile, 0 if none, None if truth partial."""
    if any(not truth.get(seat) for seat in OPPONENTS):
        return None
    for seat in OPPONENTS:
        hand, melds = _seat_truth(truth[seat])
        if tile in get_waiting_tiles(hand, melds):
            return 1
    return 0


def dual_review(receipts: List[dict],
                truth: Optional[Dict[str, object]]) -> List[dict]:
    """For each receipt decision point: prior vs truth on the recommendation."""
    out: List[dict] = []
    for receipt in receipts:
        top = receipt["candidates"][0]
        tile = parse_tile(top["tile"])
        prior = top["p_point"]
        true_p = _structural_ron(truth, tile) if truth else None
        entry = {
            "game_id": receipt["game_id"],
            "revision": receipt["revision"],
            "tile": top["tile"],
            "prior_p": prior,
            "true_p": true_p,
            "delta": (prior - true_p) if true_p is not None else None,
            "labels": ["真值:结构"] if true_p is not None else ["真值不全"],
        }
        out.append(entry)
    return out
