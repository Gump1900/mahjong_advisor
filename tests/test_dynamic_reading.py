"""Ordered evidence, counterevidence, hidden-information isolation and tactical use."""
from copy import deepcopy

import pytest

from src.core.tiles import GameState, parse_tile as T
from src.decision.belief import HiddenWorld
from src.decision.dynamic_reading import read_table, history_weight, public_events
from src.decision.ev_bot import build_state_from_observation
from src.decision.ev import deal_risks, sort_candidates, CandidateEV
from src.decision.call_pressure import advances_on_claim
from tests.test_ev_bot import _obs


def event(kind, tile=None, seat='right', **extras):
    return dict(kind=kind, seat=seat, **({'tile': tile} if tile else {}), **extras)


def world(hand):
    return HiddenWorld({'right': list(map(T, hand.split())), 'left': [], 'opposite': []}, {}, [])


SHAPE = '1万 3万 4万 5万 6万 7饼 8饼 9饼 2条 3条 8条 南 南'
NO_SHAPE = '1万 4万 5万 6万 7饼 8饼 9饼 2条 3条 8条 南 南 北'


def test_discarded_two_weakens_but_never_eliminates_one_three():
    state = GameState(public_events=[event('discard', '2万')])
    a, b = history_weight(world(SHAPE), state), history_weight(world(NO_SHAPE), state)
    assert 0.2 <= a < b <= 1
    assert '13万' in read_table(state)['right'].summary


def test_new_draws_and_calls_weaken_old_evidence():
    state = GameState(public_events=[event('discard', '2万')])
    before = history_weight(world(SHAPE), state)
    state.public_events += [event('draw')]*4 + [event('peng', tiles=['7条']*3)]
    assert history_weight(world(SHAPE), state) > before


def test_same_discard_multiset_different_order_changes_read():
    a = GameState(public_events=[event('discard', '2万'), event('draw'), event('discard', '北风')])
    b = GameState(public_events=[event('discard', '北风'), event('draw'), event('discard', '2万')])
    assert history_weight(world(SHAPE), a) > history_weight(world(SHAPE), b)
    assert read_table(a)['right'].summary != read_table(b)['right'].summary


def test_redundant_two_is_an_alternative_explanation():
    state = GameState(public_events=[event('discard', '2万')])
    extra = SHAPE.replace('8条', '2万')
    assert history_weight(world(extra), state) > history_weight(world(SHAPE), state)


def test_wind_to_number_phase_and_post_call_are_separate():
    state = GameState(public_events=[event('discard', t) for t in ['西风', '北风', '1万', '9条']])
    assert read_table(state)['right'].phase == 'organizing'
    assert '可能' in read_table(state)['right'].summary
    state.public_events += [event('peng', tiles=['3饼']*3), event('discard', '5条')]
    assert read_table(state)['right'].phase == 'after_call'
    assert '叫牌后打5条' in read_table(state)['right'].summary


def test_no_evidence_is_just_unable_to_infer():
    assert read_table(GameState())['right'].summary == '无法推断'
    assert history_weight(world(SHAPE), GameState()) == 1


def test_observer_rotation_and_private_fields_are_not_evidence():
    obs = _obs(seat=2)
    obs['events'] = [dict(kind='draw', seat=3, tile='1万', hand=['1万']*13),
                     dict(kind='an_gang', seat=0, tile='2万', tiles=['2万']*4, hidden=True),
                     dict(kind='discard', seat=1, tile='2万')]
    original = deepcopy(obs)
    a = build_state_from_observation(obs)
    assert a.public_events[0] == {'kind': 'draw', 'seat': 'right'}
    assert a.public_events[1] == {'kind': 'an_gang', 'seat': 'opposite'}
    assert a.public_events[2]['seat'] == 'left'
    assert obs == original
    obs['events'][0]['tile'] = '9条'
    obs['events'][0]['hand'] = ['9条']*13
    obs['events'][1]['tiles'] = ['7饼']*4
    obs['events'][1]['tile'] = '7饼'
    b = build_state_from_observation(obs)
    assert a.public_events == b.public_events
    assert history_weight(world(SHAPE), a) == history_weight(world(SHAPE), b)


def test_prefix_rebuild_does_not_mutate_prior_reads_or_other_games():
    state = GameState(public_events=[event('discard', '2万')])
    before = deepcopy(read_table(state))
    later = GameState(public_events=state.public_events+[event('draw'), event('discard', '5条')])
    read_table(later)
    assert read_table(state) == before
    assert read_table(GameState())['right'].summary == '无法推断'


def test_can_chi_does_not_mean_it_accelerates_a_ready_hand():
    ready = SHAPE.replace('8条', '4条')
    assert not advances_on_claim(list(map(T, ready.split())), 0, T('2万'), allow_chi=True)
    assert advances_on_claim(list(map(T, SHAPE.split())), 0, T('2万'), allow_chi=True)
    assert not advances_on_claim(list(map(T, SHAPE.split())), 0, T('2万'), allow_chi=False)


def test_seven_pairs_is_not_blindly_broken_by_call_pressure():
    hand = list(map(T, '1万 1万 2万 2万 3万 3万 4饼 4饼 5饼 5饼 6条 6条 南'.split()))
    assert not advances_on_claim(hand, 0, T('2万'), allow_chi=True)


def test_ordered_reads_change_sampled_feed_and_acceleration(monkeypatch):
    worlds = [world(SHAPE), world(NO_SHAPE)]
    def risks(state):
        cursor = iter(worlds)
        monkeypatch.setattr('src.decision.ev.sample_world', lambda *_: next(cursor))
        return deal_risks(state, [T('2万')], samples=2)[T('2万')]
    baseline = risks(GameState())
    updated = risks(GameState(public_events=[event('discard', '2万')]))
    assert baseline.p_feed_chi == baseline.p_next_progress == .5
    assert 0 < updated.p_next_progress < baseline.p_next_progress
    assert updated.p_feed_chi < baseline.p_feed_chi


def test_call_acceleration_breaks_equivalent_own_discards_tie():
    a = CandidateEV(T('2万'), 0, exp_neff_1ply=10, p_next_progress=.8)
    b = CandidateEV(T('9条'), 0, exp_neff_1ply=10, p_next_progress=.1)
    assert sort_candidates([a, b])[0] is b
    a.ev = 20
    assert sort_candidates([a, b])[0] is a


def test_calls_with_held_flower_do_not_enter_ordinary_hand_ev():
    from src.decision.call_decision import evaluate_calls
    from src.decision.ev_bot import EVBot
    from tests.test_ev_coach import TestCallAdvice
    obs = TestCallAdvice()._response(
        '1万 2万 3万 4万 5万 6万 7万 8万 春 5饼 5饼 2条 9条'.split(), '5饼')
    obs['self']['held_flower_count'] = 1
    before = deepcopy(obs)
    analysis = evaluate_calls(obs)
    assert '留花占位' in analysis['followup_limitation']
    assert EVBot(samples=4).choose(obs).action_id in {a['id'] for a in obs['legal_actions']}
    assert obs == before


def test_directional_call_counts_are_preserved_before_lock():
    obs = _obs()
    obs['players'] = [{'seat':i,'river':[],'flowers':[],'melds':[]} for i in range(4)]
    obs['call_counts'] = [[0,2,0,0],[0]*4,[0]*4,[0]*4]
    assert build_state_from_observation(obs).chi_peng_source_counts['me']['right'] == 2


def test_late_honor_is_counterevidence_to_waste_tiles_all_gone():
    state = GameState(public_events=[event('discard', t) for t in ['西风', '北风', '1万', '9条']])
    assert read_table(state)['right'].phase == 'organizing'
    state.public_events.append(event('discard', '南风'))
    revised = read_table(state)['right']
    assert revised.phase == 'reassess'
    assert revised.summary == '无法推断'
    assert '不能认定废牌已出尽' in revised.evidence[0]
