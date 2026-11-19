"""Shared call comparison; evaluate the mandatory discard with current opponent reads."""
from copy import deepcopy

from ..players.analysis import analyze_actions
from ..core.tiles import parse_tile


def is_beneficial(candidate, baseline):
    if candidate['kind'] not in ('chi', 'peng', 'ming_gang'):
        return False
    gain = (candidate['shanten'], -candidate['unseen_improving']) < (baseline['shanten'], -baseline['unseen_improving'])
    return gain and not ((candidate.get('discards_claimed_kind') or candidate.get('creates_lock'))
                         and candidate['shanten'] >= baseline['shanten'])


def call_rank(candidate):
    return (candidate['shanten'], -candidate['unseen_improving'],
            candidate.get('followup_loss', 0.0), candidate.get('followup_next_progress', 0.0),
            bool(candidate.get('creates_lock')), candidate['action_id'])


def evaluate_calls(observation, *, samples=16, seed=0):
    from .ev_bot import build_state_from_observation
    from .ev import rank_candidates
    analysis = analyze_actions(observation)
    baseline = analysis['baseline']
    if any(parse_tile(t).is_flower for t in observation['self']['hand']):
        # 合法吃碰可发生在留花占位态；现有EV只支持完整结构手，不能硬塞进去。
        analysis['followup_limitation'] = '留花占位：先用结构比较，换花后再计算弃牌攻守'
        return analysis
    for candidate in analysis['candidates']:
        if not is_beneficial(candidate, baseline) or candidate['kind'] == 'ming_gang':
            continue
        # A public counterfactual, never a referee mutation or access to concealed hands.
        followup = deepcopy(observation)
        seat = observation['seat']
        source, tile = observation['pending']['source'], observation['pending']['tile']
        action = next(a for a in observation['legal_actions'] if a['id'] == candidate['action_id'])
        group = action['tiles'][:] if action['kind'] == 'chi' else [tile]*3
        needed = group.copy()
        needed.remove(tile)
        hand = followup['self']['hand']
        for held in needed:
            hand.remove(held)
        mine = next(p for p in followup['players'] if p['seat'] == seat)
        mine['melds'].append({'type': action['kind'], 'tiles': group})
        river = next(p for p in followup['players'] if p['seat'] == source)['river']
        if tile in river:
            river.reverse(); river.remove(tile); river.reverse()
        if candidate.get('creates_lock'):
            followup.setdefault('locked_pairs', []).append([seat, source])
        followup['events'].append({'kind': action['kind'], 'seat': seat, 'source': source, 'tiles': group})
        state = build_state_from_observation(followup)
        ranked = rank_candidates(state, samples=samples, seed=seed, refine_ties=False)
        eligible = [c for c in ranked if c.stand_shanten == candidate['shanten']]
        if eligible:
            best = eligible[0]
            candidate['best_discard'] = str(best.tile)
            facts = next(item for item in candidate['after_discards'] if item['tile'] == str(best.tile))
            candidate['unseen_improving'] = facts['unseen_improving']
            candidate['improving_tiles'] = facts['improving_tiles']
            candidate['discards_claimed_kind'] = str(best.tile) == tile
            candidate['followup_loss'] = best.p_point * best.v_deal
            candidate['followup_next_progress'] = best.p_next_progress
    return analysis
