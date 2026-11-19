"""Deterministic four-player referee for the user-confirmed local rules.

Normal draws use the front, replacements the back of ONE wall (no dead wall).
This draw-end convention is recorded as a test convention, not a local bonus rule.
"""
import copy
import hashlib
import json
import random
from collections import Counter
from dataclasses import asdict
from uuid import uuid4

from ..core.hand_analyzer import can_chi, is_agari
from ..core.round_rules import Claim, PLAYERS, resolve_claims, settle_round
from ..core.scoring import score_hand
from ..core.tiles import Meld
from .state import Action, RULES_VERSION, LEGACY_RULES_VERSION, SUPPORTED_RULES_VERSIONS, SeatState, full_deck


class Table:
    def __init__(self, seed=0, dealer=0, *, wall=None, game_id=None, rules_version=RULES_VERSION):
        if rules_version not in SUPPORTED_RULES_VERSIONS:
            raise ValueError("不支持的规则版本")
        self.rules_version = rules_version
        self.call_counts = [[0]*4 for _ in range(4)]  # claimant -> discarder; never merge directions.
        if isinstance(dealer, bool) or dealer not in range(4):
            raise ValueError("庄家座位须为0至3")
        self.seed, self.dealer = seed, dealer
        self.game_id = game_id or uuid4().hex
        deck = full_deck() if wall is None else list(wall)
        if Counter(deck) != Counter(full_deck()):
            raise ValueError("必须使用完整且副本正确的144张牌墙")
        if wall is None:
            random.Random(seed).shuffle(deck)
        self.initial_wall = list(deck)
        self.wall = deck
        self.seats = [SeatState() for _ in range(4)]
        for _ in range(13):
            for offset in range(4):
                self.seats[(dealer+offset) % 4].hand.append(self.wall.pop(0))
        self.seats[dealer].hand.append(self.wall.pop(0))
        self.actor = dealer
        self.stage = "turn"
        self.draw_source = "initial"
        self.drawn_tile = None
        self.can_kong = True
        self.revision = 0
        self.pending = None
        self.responses = {}
        self.events = []  # Private authoritative log, redacted by observation.py.
        self.decisions = []
        self.result = None
        self.metadata = {}  # Run configuration only; no credentials, not game state.
        self.assert_consistent()

    def _token(self):
        return f"response{self.pending['id']}" if self.stage == "responses" else f"turn{self.revision}"

    def waiting_seats(self):
        if self.stage == "ended":
            return []
        if self.stage == "turn":
            return [self.actor]
        return [p for p in range(4) if p != self.pending["source"] and p not in self.responses]

    def _score(self, seat, method, tile=None):
        player = self.seats[seat]
        if method == "dianpao" and (player.ron_blocked or self.locked_with(seat)):
            return None
        hand = player.hand + ([tile] if tile is not None else [])
        if (any(t.is_flower for t in hand) or len(hand) != 14-3*len(player.melds)
                or not is_agari(hand, len(player.melds))):
            return None
        try:
            # Four-flower kongs live in melds: no double scoring as flower singles.
            return score_hand(hand, player.melds, [], player.flowers, method,
                              flower_kong_groups=[[t] for t in player.flowers])
        except ValueError:
            return None

    def locked_pairs(self):
        if self.rules_version == LEGACY_RULES_VERSION:
            return []
        return [(a, b) for a in range(4) for b in range(a+1, 4)
                if self.call_counts[a][b] >= 3 or self.call_counts[b][a] >= 3]

    def locked_with(self, seat):
        return [b if a == seat else a for a, b in self.locked_pairs() if seat in (a, b)]

    def legal_actions(self, seat):
        if isinstance(seat, bool) or seat not in range(4) or seat not in self.waiting_seats():
            return []
        player = self.seats[seat]
        kinds = []
        counts = Counter(player.hand)
        if self.stage == "responses":
            tile = self.pending["tile"]
            kinds.append(("pass", ()))
            if self._score(seat, "dianpao", tile) is not None:
                kinds.append(("ron", (tile,)))
            if len(player.melds) < 4:
                if (counts[tile] >= 2 and sum(not t.is_flower for t in player.hand) > 2
                        and (self.rules_version != RULES_VERSION or tile not in player.peng_blocked)):
                    kinds.append(("peng", (tile,)))
                if counts[tile] >= 3 and self.wall:
                    kinds.append(("ming_gang", (tile,)))
                if seat == (self.pending["source"]+1) % 4:
                    for pair in can_chi(player.hand, tile):
                        if sum(not t.is_flower for t in player.hand) > 2:
                            kinds.append(("chi", tuple(sorted(pair+[tile], key=str))))
        else:
            method = "gangkai" if self.draw_source == "replacement" else "zimo"
            if self.draw_source != "claim" and self._score(seat, method) is not None:
                kinds.append(("win", ()))
            for tile in sorted(counts, key=str):
                if not tile.is_flower:
                    kinds.append(("discard", (tile,)))
                elif self.wall:
                    # 2026-11-18 用户定稿：换花不问回合来源（吃/碰接管后仍可换）
                    kinds.append(("flower_kong", (tile,)))
                if (self.wall and counts[tile] == 4
                        and len(player.melds) < 4):
                    kinds.append(("an_gang", (tile,)))
            if self.wall:
                for meld in player.melds:
                    if meld.type == "peng" and counts[meld.tiles[0]]:
                        kinds.append(("add_gang", (meld.tiles[0],)))
        token = self._token()
        return [Action(f"{self.game_id}:{token}:{seat}:{i}", kind, tiles)
                for i, (kind, tiles) in enumerate(kinds)]

    def apply(self, seat, action_id, *, controller="unknown", reason=""):
        actions = self.legal_actions(seat)
        action = next((a for a in actions if a.id == action_id), None)
        if action is None:
            raise ValueError("非法或过期动作，不改变牌局")
        if self.stage == "responses":
            # Private choices remain private until the entire window is resolved.
            if any(a.kind == "ron" for a in actions) and action.kind != "ron":
                self.seats[seat].ron_blocked = True
            if (self.rules_version == RULES_VERSION and any(a.kind == "peng" for a in actions)
                    and action.kind not in ("peng", "ming_gang", "ron")):
                self.seats[seat].peng_blocked.add(self.pending["tile"])
            self.responses[seat] = action
            if len(self.responses) == 3:
                self._resolve()
        else:
            self._turn(action)
        self.revision += 1
        self.assert_consistent()
        self.decisions.append({"seat": seat, "action": action.json(),
                               "controller": controller, "reason": reason,
                               "state_hash": self.state_hash()})

    def exchange_flowers(self, seat, tiles, *, controller="unknown:batch"):
        """Atomic explicit single-flower selection for ANY seat/controller.

        Each replacement is an ordinary replayable action. Newly drawn flowers
        never extend the selection. Four selected singles are NOT an ankan.
        """
        if type(seat) is not int or seat not in range(4):
            raise ValueError("未知座位")
        if (not isinstance(tiles, list) or not 1 <= len(tiles) <= 14
                or any(not isinstance(t, str) for t in tiles)):
            raise ValueError("请选择1至14张手中花牌")
        if self.stage != "turn" or self.actor != seat:
            raise ValueError("当前不是自己的合法换花时机")
        available = Counter(str(t) for t in self.seats[seat].hand if t.is_flower)
        if Counter(tiles) - available:
            raise ValueError("只能选择当前手里的花牌，不能超出实际张数")
        if len(tiles) > len(self.wall):
            raise ValueError("剩余牌墙不足以补回所选张数，请减少选择")
        trial, drawn = copy.deepcopy(self), []
        for tile in tiles:
            action = next((a for a in trial.legal_actions(seat)
                           if a.kind == "flower_kong" and str(a.tiles[0]) == tile), None)
            if action is None:
                raise ValueError("当前不能单张换花；批量操作未执行")
            trial.apply(seat, action.id, controller=controller,
                        reason="明确选择的单张换花，不自动处理新摸花")
            drawn.append(str(trial.drawn_tile))
        self.__dict__.update(trial.__dict__)
        return drawn

    def _turn(self, action):
        player = self.seats[self.actor]
        kind = action.kind
        tile = action.tiles[0] if action.tiles else None
        if kind == "win":
            method = "gangkai" if self.draw_source == "replacement" else "zimo"
            self._finish(method, [self.actor])
        elif kind == "discard":
            player.hand.remove(tile)
            player.river.append(tile)
            self.pending = {"id": self.revision+1, "source": self.actor, "tile": tile}
            self.responses = {}
            self.drawn_tile = None
            self.stage = "responses"
            self.events.append({"kind": kind, "seat": self.actor, "tile": str(tile)})
        elif kind == "flower_kong":
            player.hand.remove(tile)
            player.flowers.append(tile)
            self.events.append({"kind": kind, "seat": self.actor, "tile": str(tile)})
            self._draw(self.actor, replacement=True)
        elif kind == "an_gang":
            for _ in range(4):
                player.hand.remove(tile)
            player.melds.append(Meld("an_gang", [tile]*4))
            self.events.append({"kind": kind, "seat": self.actor, "tile": str(tile)})
            self._draw(self.actor, replacement=True)
        elif kind == "add_gang":
            player.hand.remove(tile)
            meld = next(m for m in player.melds if m.type == "peng" and m.tiles[0] == tile)
            meld.type = "ming_gang"
            meld.tiles.append(tile)
            self.events.append({"kind": kind, "seat": self.actor, "tile": str(tile)})
            self._draw(self.actor, replacement=True)  # No rob-kong response window.

    def _resolve(self):
        source, tile = self.pending["source"], self.pending["tile"]
        names = {"ron": "ron", "peng": "peng", "ming_gang": "gang", "chi": "chi"}
        claims = [Claim(PLAYERS[p], names[a.kind]) for p, a in self.responses.items() if a.kind != "pass"]
        selected = resolve_claims(PLAYERS[source], claims)
        if selected and selected[0].kind == "ron":
            self._finish("dianpao", [PLAYERS.index(c.player) for c in selected], source, tile)
            return
        if not selected:
            self.events.append({"kind": "all_pass", "source": source})
            self.pending, self.responses = None, {}
            self._draw((source+1) % 4)
            return
        seat = PLAYERS.index(selected[0].player)
        action = self.responses[seat]
        player = self.seats[seat]
        self.seats[source].river.pop()
        if action.kind in ("peng", "ming_gang"):
            n = 2 if action.kind == "peng" else 3
            for _ in range(n):
                player.hand.remove(tile)
            player.melds.append(Meld(action.kind, [tile]*(n+1)))
        else:
            needed = list(action.tiles)
            needed.remove(tile)
            for t in needed:
                player.hand.remove(t)
            player.melds.append(Meld("chi", list(action.tiles)))
        self.events.append({"kind": action.kind, "seat": seat, "source": source,
                            "tiles": [str(t) for t in player.melds[-1].tiles]})
        if self.rules_version != LEGACY_RULES_VERSION:
            was_locked = bool(self.call_counts[seat][source] >= 3 or self.call_counts[source][seat] >= 3)
            self.call_counts[seat][source] += 1
            if not was_locked and source in self.locked_with(seat):
                self.events.append({"kind": "three_calls_lock", "seat": seat, "source": source})
        player.ron_blocked = False  # Gaining a turn by calling clears the lock.
        player.peng_blocked.clear()
        self.actor, self.stage = seat, "turn"
        self.pending, self.responses = None, {}
        self.drawn_tile, self.draw_source, self.can_kong = None, "claim", False
        if action.kind == "ming_gang":
            self._draw(seat, replacement=True)

    def _draw(self, seat, replacement=False):
        self.actor = seat
        if not self.wall:
            self._finish("draw", [])
            return
        self.seats[seat].ron_blocked = False
        self.seats[seat].peng_blocked.clear()
        tile = self.wall.pop() if replacement else self.wall.pop(0)
        self.seats[seat].hand.append(tile)
        self.stage = "turn"
        self.can_kong = True
        self.drawn_tile = tile
        self.draw_source = "replacement" if replacement else "normal"
        self.events.append({"kind": "draw", "seat": seat, "tile": str(tile),
                            "replacement": replacement})
        if not self.wall and all(t.is_flower for t in self.seats[seat].hand):
            self._finish("draw", [])  # No playable discard and no remaining replacement.

    def _finish(self, method, winners, source=None, tile=None):
        scores = {}
        for seat in winners:
            score = self._score(seat, method, tile)
            if score is None:
                raise ValueError("裁判检测到非法胡牌")
            scores[str(seat)] = asdict(score)
        settlement = settle_round(method, {PLAYERS[p]: scores[str(p)]["hua"] for p in winners},
                                  PLAYERS[source] if source is not None else None,
                                  locked_pairs=[(PLAYERS[a], PLAYERS[b]) for a, b in self.locked_pairs()])
        self.result = {"method": method, "winners": winners, "source": source,
                       "tile": str(tile or self.drawn_tile) if (tile or self.drawn_tile) and method != "draw" else None,
                       "scores": scores, "net": [settlement.net[p] for p in PLAYERS]}
        if self.rules_version != LEGACY_RULES_VERSION:
            self.result["payments"] = [asdict(p) for p in settlement.payments]
            self.result["locked_pairs"] = [list(pair) for pair in self.locked_pairs()]
        self.stage = "ended"
        self.events.append({"kind": "end", "result": copy.deepcopy(self.result)})

    def assert_consistent(self):
        counts = Counter(self.wall)
        for p, player in enumerate(self.seats):
            counts.update(player.hand)
            counts.update(player.flowers)
            counts.update(player.river)
            if len(player.melds) > 4 or any(not t.is_flower for t in player.flowers):
                raise AssertionError("成组或花牌区域不合法")
            for meld in player.melds:
                counts.update(meld.tiles)
            if self.stage != "ended":
                expected = 13-3*len(player.melds) + int(self.stage == "turn" and p == self.actor)
                if len(player.hand) != expected:
                    raise AssertionError(f"座位{p}手牌张数错误：{len(player.hand)} != {expected}")
            else:
                base = 13-3*len(player.melds)
                allowed = (base, base+1) if p == self.actor else (base,)
                if len(player.hand) not in allowed:
                    raise AssertionError("终局手牌占位不合法")
        if counts != Counter(full_deck()):
            raise AssertionError("144张实体牌不守恒")
        if self.result and sum(self.result["net"]) != 0:
            raise AssertionError("结算不是零和")

    def snapshot(self):
        def meld_json(m):
            return {"type": m.type, "tiles": [str(t) for t in m.tiles]}
        result = {"rules_version": self.rules_version, "game_id": self.game_id,
                "revision": self.revision, "dealer": self.dealer,
                "wall": [str(t) for t in self.wall], "stage": self.stage, "actor": self.actor,
                "draw_source": self.draw_source, "drawn_tile": str(self.drawn_tile) if self.drawn_tile else None,
                "can_kong": self.can_kong,
                "pending": None if self.pending is None else {**self.pending, "tile": str(self.pending["tile"])},
                "responses": {str(p): a.json() for p, a in self.responses.items()},
                "seats": [{"hand": [str(t) for t in s.hand], "melds": [meld_json(m) for m in s.melds],
                           "flowers": [str(t) for t in s.flowers], "river": [str(t) for t in s.river],
                           "ron_blocked": s.ron_blocked} for s in self.seats],
                "result": copy.deepcopy(self.result)}
        if self.rules_version != LEGACY_RULES_VERSION:
            result["call_counts"] = copy.deepcopy(self.call_counts)
        if self.rules_version == RULES_VERSION:
            for shown, player in zip(result["seats"], self.seats):
                shown["peng_blocked"] = [str(t) for t in sorted(player.peng_blocked, key=str)]
        return result

    def state_hash(self):
        return hashlib.sha256(json.dumps(self.snapshot(), sort_keys=True,
                                         ensure_ascii=False).encode()).hexdigest()
