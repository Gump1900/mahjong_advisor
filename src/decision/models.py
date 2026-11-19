"""Shared decision contracts. Context snapshots never contain inferred hands."""
import copy
from dataclasses import dataclass, field
from typing import Dict, List, Tuple
from ..core.tiles import GameState, Tile


@dataclass
class AnalysisBundle:
    """Deterministic analysis of a game state, fed to the prompt and the UI."""

    shanten: int
    is_tenpai: bool
    ukeire: List[Tile]
    waiting: List[Tile]
    discards_ranked: List[Tuple[Tile, int]]
    risks: Dict[Tile, str]                    # coarse label, kept for the UI
    risk_estimates: Dict[Tile, Dict[str, float]]  # {chi, peng, ron, label}
    remaining: Dict[Tile, int]
    remaining_total: int
    kong_opportunities: List[Dict] = field(default_factory=list)
    discard_speed: Dict[Tile, Dict[str, int]] = field(default_factory=dict)  # 进张 per discard


@dataclass(frozen=True)
class DecisionContext:
    game_id: str
    revision: int
    state: GameState
    phase: str
    pending: dict | None
    drawn_tile: Tile | None
    replacement_draw_pending: bool
    last_draw_was_replacement: bool
    events: tuple

    @classmethod
    def from_session(cls, session):
        return cls(
            session.game_id, session.revision, copy.deepcopy(session.state),
            session.phase, copy.deepcopy(session.pending), session.drawn_tile,
            session.replacement_draw_pending, session.last_draw_was_replacement,
            tuple(copy.deepcopy(session.events)),
        )
