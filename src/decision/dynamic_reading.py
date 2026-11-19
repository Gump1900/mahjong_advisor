"""Ordered public-action evidence, shared by coach and sampled-world weighting.

Soft, auditable hypotheses, never hard exclusions or calibrated human probabilities.
Rebuilt from the current redacted event prefix: no mutable cross-game memory.
"""
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
import math

from ..core.hand_analyzer import can_chi
from ..core.tiles import parse_tile

MODEL = 'public-action-history-v1'
SUITS = ('万', '饼', '条')
CALLS = ('chi', 'peng', 'ming_gang', 'add_gang', 'an_gang')
KINDS = (*CALLS, 'draw', 'discard', 'flower_kong')


def public_events(observation):
    """Copy only public fields needed for inference; hidden draws/closed kongs stay hidden."""
    me = observation['seat']
    result = []
    for event in observation.get('events', []):
        kind, seat = event.get('kind'), event.get('seat')
        if kind not in KINDS or type(seat) is not int or seat not in range(4):
            continue
        relative = ('me', 'right', 'opposite', 'left')[(seat-me) % 4]
        item = {'kind': kind, 'seat': relative}
        if kind == 'discard' and event.get('tile'):
            item['tile'] = str(parse_tile(event['tile']))
        # Even malformed inputs cannot turn private draw/closed-kong tiles into evidence.
        if kind in ('chi', 'peng', 'ming_gang') and not event.get('hidden'):
            item['tiles'] = [str(parse_tile(t)) for t in event.get('tiles', [])]
        result.append(item)
    return result


@dataclass(frozen=True)
class DiscardEvidence:
    tile: str
    age: int
    after_call: bool


@dataclass(frozen=True)
class SeatRead:
    discards: tuple
    phase: str
    calls: int
    summary: str
    evidence: tuple


def read_table(state):
    packed = tuple((e['kind'], e['seat'], e.get('tile', ''), tuple(e.get('tiles', [])))
                   for e in state.public_events)
    return _read(packed)


@lru_cache(maxsize=256)
def _read(events):
    out = {}
    for seat in ('right', 'opposite', 'left'):
        clock, calls, last_action = 0, 0, ''
        discards = []
        for kind, actor, tile, tiles in events:
            if actor != seat:
                continue
            if kind in ('draw', *CALLS, 'flower_kong'):
                clock += 1
            if kind in CALLS:
                calls += 1
            if kind == 'discard' and tile:
                discards.append((tile, clock, last_action in CALLS))
            last_action = kind
        records = tuple(DiscardEvidence(tile, clock-when, after) for tile, when, after in discards)
        phase, summary, evidence = 'unknown', '无法推断', []
        if records:
            latest = records[-1]
            numeric = [i for i, r in enumerate(records) if parse_tile(r.tile).suit in SUITS]
            # Transition is a weak change-of-phase signal, not proof of tenpai.
            if len(numeric) >= 2 and numeric[-2:] == [len(records)-2, len(records)-1] and numeric[0] >= 2 and all(
                    parse_tile(r.tile).suit == '风' for r in records[:numeric[0]]):
                phase = 'organizing'
                summary = '风牌后转打数牌，可能在收拢结构'
                evidence.append(summary)
            t = parse_tile(latest.tile)
            if t.suit == '风' and len(numeric) >= 2:
                phase = 'reassess'
                evidence.append('数牌后又打风牌，不能认定废牌已出尽；需重看先前的收拢判断')
            if latest.after_call:
                phase = 'after_call'
                summary = f'叫牌后打{t}，正在调整余牌'
                evidence.append(summary)
            elif t.suit in SUITS and int(t.value) in range(2, 9):
                pair = f'{int(t.value)-1}{int(t.value)+1}{t.suit}'
                if phase == 'unknown':
                    summary = f'刚打{t}，{pair}搭子可能性降低'
                evidence.append(f'刚打{t}：降低保留{pair}搭子的假设，仍允许冗余牌、拆搭和后摸解释')
            recent = Counter(parse_tile(r.tile).suit for r in records[-5:])
            suit, count = max(((s, recent[s]) for s in SUITS), key=lambda x: x[1])
            if count >= 3:
                if phase == 'unknown':
                    summary = f'近五次弃{suit}{count}张，可能少留{suit}'
                evidence.append(f'近五次弃{suit}{count}张')
        out[seat] = SeatRead(records, phase, calls, summary, tuple(evidence))
    return out


def history_weight(world, state):
    """Recent discarded completions weaken retained-shape hypotheses; later actions age them."""
    log_weight = 0.0
    for seat, read in read_table(state).items():
        hand = world.hands.get(seat, [])
        counts = Counter(hand)
        for record in read.discards:
            discarded = parse_tile(record.tile)
            recency = 0.78 ** record.age
            strength = recency * (1.2 if record.after_call else 1.0)
            if discarded.suit in SUITS:
                # Shape evidence, not the false assertion that neither neighbor exists.
                combinations = can_chi(hand, discarded)
                redundant = 0.4 if counts[discarded] else 1.0
                shape_penalty = sum(0.65 if abs(int(a.value)-int(b.value)) == 2 else 0.35
                                    for a, b in combinations)
                log_weight -= strength * redundant * min(shape_penalty, 1.2)
                same_suit = sum(t.suit == discarded.suit for t in hand)
                log_weight -= 0.12 * strength * same_suit / max(1, len(hand))
            elif counts[discarded] >= 2:
                log_weight -= 0.2 * strength  # Honors also carry weak information.
    # Keep a substantial uniform mixture: deceptive play and alternative explanations survive.
    return 0.2 + 0.8 * math.exp(max(-30.0, log_weight))
