"""Private referee state. Never hand these objects to players."""
from dataclasses import dataclass, field

from ..core.probability import TileCounter
from ..core.tiles import Meld, Tile

LEGACY_RULES_VERSION = "local-2026-10-21-desktop-v2"
PREVIOUS_RULES_VERSION = "local-2026-10-21-desktop-v3"
RULES_VERSION = "local-2026-10-22-desktop-v4"
SUPPORTED_RULES_VERSIONS = (RULES_VERSION, PREVIOUS_RULES_VERSION, LEGACY_RULES_VERSION)


def full_deck():
    return [tile for tile, count in TileCounter().all_counts().items() for _ in range(count)]


@dataclass
class SeatState:
    hand: list[Tile] = field(default_factory=list)  # Includes held flowers!
    melds: list[Meld] = field(default_factory=list)  # Includes four-flower ankan.
    flowers: list[Tile] = field(default_factory=list)  # Only singles already exchanged.
    river: list[Tile] = field(default_factory=list)
    ron_blocked: bool = False
    peng_blocked: set[Tile] = field(default_factory=set)


@dataclass(frozen=True)
class Action:
    id: str
    kind: str
    tiles: tuple[Tile, ...] = ()

    def json(self):
        return {"id": self.id, "kind": self.kind, "tiles": [str(t) for t in self.tiles]}
