"""Deterministic analysis, independent of any LLM provider."""
from collections import Counter
from typing import Dict, List

from ..core.hand_analyzer import (
    calculate_shanten,
    get_ukeire,
    get_waiting_tiles,
    rank_discards,
)
from ..core.probability import (
    count_remaining_tiles,
    discard_risk,
    estimate_discard_risks,
)
from ..core.scoring import HELD_FLOWER_TIERS, flower_hua, kong_value
from ..core.tiles import GameState, Meld, Tile

from .models import AnalysisBundle


def find_kong_opportunities(state: GameState) -> List[Dict]:
    """Kong-able assets the player can TIME (留花/择时杠 for the 杠开 shot).

    - 暗杠: 4 identical playable tiles concealed in hand
    - 加杠: a peng meld plus the drawn 4th copy in hand
    - 花牌自杠: 4 identical 中发白东 held un-konged (12花 vs 6花 held), and
      EVERY held season flower (春夏秋冬梅兰竹菊) — seasons score 1花 konged
      or held alike, so their kong value is purely the timing: kong at
      tenpai and win on the replacement draw = 杠开.
    """
    opps: List[Dict] = []
    hand_counts = Counter(t for t in state.my_hand if not t.is_flower)

    for tile, n in hand_counts.items():
        if n == 4:
            opps.append({
                "tile": tile, "kind": "暗杠", "hua": kong_value("an_gang", tile),
                "note": "4张在手，可留到听牌时再暗杠",
            })

    for m in state.my_melds:
        if m.type == "peng" and m.tiles and hand_counts.get(m.tiles[0], 0) >= 1:
            tile = m.tiles[0]
            opps.append({
                "tile": tile, "kind": "加杠", "hua": kong_value("ming_gang", tile),
                "note": f"碰{tile}后又摸到一张，可加杠（风刻+1升级为杠分）",
            })

    flower_counts = Counter(state.flowers_in_hand)
    for tile, n in flower_counts.items():
        if tile.suit == "三元" or (tile.suit == "风" and tile.value == "东"):
            if n >= 4:
                held = HELD_FLOWER_TIERS[4]
                opps.append({
                    "tile": tile, "kind": "花牌自杠", "hua": kong_value("an_gang", tile),
                    "count": 4,
                    "note": f"留4张={held}花 / 杠=12花（暗杠后不算花）；留到听牌杠搏杠开",
                })
            total = flower_hua(state.flowers_in_hand, state.konged_flowers,
                               state.flower_kong_groups or None)
            opps.append({
                "tile": tile, "kind": "花牌单杠", "hua": 0, "count": 1,
                "hua_basis": "flower_score_delta", "delta_hua": 0,
                "flower_hua_before": total, "flower_hua_after": total,
                "note": "本次花分增量0；持有与单张杠出的同款合并计分，单杠只增加补牌机会，不直接获得收入",
            })
        elif tile.suit == "季节":
            opps.append({
                "tile": tile, "kind": "花牌自杠", "hua": 1,
                "note": "季节花杠/留都是1花，价值在时机：留到听牌杠搏杠开",
            })
    return opps


def analyze(state: GameState) -> AnalysisBundle:
    """Run the engine over the state and collect every fact the advisor needs."""
    hand = state.my_hand
    fuuro = len(state.my_melds)  # each called meld is a finished mentsu
    shanten = calculate_shanten(hand, fuuro)
    is_tenpai = shanten == 0
    discards_ranked = rank_discards(hand, fuuro)
    remaining = count_remaining_tiles(state)

    # 一胡即终局 -> 速度优先：同向听时，打出后进张（种数/活张数）多的排前面
    discard_speed: Dict[Tile, Dict[str, int]] = {}
    for tile, _after in discards_ranked:
        remaining_hand = list(hand)
        remaining_hand.remove(tile)
        ukeire = get_ukeire(remaining_hand, fuuro)
        discard_speed[tile] = {
            "types": len(ukeire),
            "tiles": sum(remaining.get(u, 0) for u in ukeire),
        }
    discards_ranked.sort(
        key=lambda x: (x[1], -discard_speed[x[0]]["tiles"], str(x[0]))
    )

    risks = {tile: discard_risk(tile, state) for tile, _ in discards_ranked}
    risk_estimates = {
        tile: estimate_discard_risks(tile, state) for tile, _ in discards_ranked
    }
    return AnalysisBundle(
        shanten=shanten,
        is_tenpai=is_tenpai,
        ukeire=get_ukeire(hand, fuuro),
        waiting=get_waiting_tiles(hand, fuuro) if is_tenpai else [],
        discards_ranked=discards_ranked,
        risks=risks,
        risk_estimates=risk_estimates,
        remaining=remaining,
        remaining_total=sum(remaining.values()),
        kong_opportunities=find_kong_opportunities(state),
        discard_speed=discard_speed,
    )
