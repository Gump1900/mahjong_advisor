"""Regressions for missed self kongs and downstream-only chi opportunity."""
from copy import deepcopy

from src.core.tiles import parse_tile, Meld
from src.decision.belief import HiddenWorld
from src.decision.ev import deal_risks, CandidateEV, sort_candidates
from src.decision.ev_bot import EVBot
from src.decision.ev_coach import EVCoach
from tests.test_ev_bot import _obs
from tests.test_ev import _state


def north_peng():
    obs = _obs()
    obs['self']['hand'] = '1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 5条 北风'.split()
    obs['players'] = [{'seat': i, 'melds': [], 'river': [], 'flowers': []} for i in range(4)]
    obs['players'][0]['melds'] = [{'type': 'peng', 'tiles': ['北风'] * 3}]
    obs['legal_actions'] = [
        {'id': 'discard-north', 'kind': 'discard', 'tiles': ['北风']},
        {'id': 'kong-north', 'kind': 'add_gang', 'tiles': ['北风']}]
    return obs


def test_north_peng_fourth_tile_is_added_kong_for_all_personalities():
    for personality in ('稳', '均衡', '凶'):
        obs = north_peng()
        before = deepcopy(obs)
        choice = EVBot(personality).choose(obs)
        assert choice.action_id == 'kong-north'
        assert '须胡后结算' in choice.reason
        assert obs == before
    assert '加杠北风' in EVCoach().explain({'observation': obs})['summary']


def test_win_precedes_added_kong_and_no_invented_kong():
    obs = north_peng()
    obs['legal_actions'].append({'id': 'win', 'kind': 'win', 'tiles': []})
    assert EVBot().choose(obs).action_id == 'win'
    assert '胡牌' in EVCoach().explain({'observation': obs})['summary']
    obs['legal_actions'] = obs['legal_actions'][:1]
    assert EVBot(samples=4).choose(obs).action_id == 'discard-north'


def test_wind_concealed_kong_is_considered_before_discard():
    obs = _obs()
    obs['self']['hand'] = '北风 北风 北风 北风 1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 5条'.split()
    obs['legal_actions'] = [{'id': 'd', 'kind': 'discard', 'tiles': ['北风']},
                            {'id': 'k', 'kind': 'an_gang', 'tiles': ['北风']}]
    assert EVBot().choose(obs).action_id == 'k'
    assert '暗杠' in EVCoach().explain({'observation': obs})['summary']


def test_chi_opportunity_is_only_downstream_and_honors_cannot_chi(monkeypatch):
    state = _state()
    world = HiddenWorld(hands={'right': list(map(parse_tile, ['2万', '3万', '8饼', '9饼'])),
                               'left': list(map(parse_tile, ['4条', '5条', '7条'])),
                               'opposite': []}, flowers={}, wall=[])
    monkeypatch.setattr('src.decision.ev.sample_world', lambda *_: world)
    risks = deal_risks(state, list(map(parse_tile, ['1万', '6条', '北风'])), samples=2)
    assert risks[parse_tile('1万')].p_feed_chi == 1
    assert risks[parse_tile('6条')].p_feed_chi == 0
    assert risks[parse_tile('北风')].p_feed_chi == 0
    state.melds['right'] = [Meld('peng', [parse_tile('南风')]*3)] * 4
    assert deal_risks(state, [parse_tile('1万')], samples=1)[parse_tile('1万')].p_feed_chi == 0


def test_equal_efficiency_prefers_less_feeding_without_ignoring_attack():
    a = CandidateEV(parse_tile('1万'), ev=0, p_feed_chi=0.8, exp_neff_1ply=10)
    b = CandidateEV(parse_tile('9条'), ev=0, p_feed_chi=0.1, exp_neff_1ply=10)
    assert sort_candidates([a, b])[0] is b
    a.ev = 20
    assert sort_candidates([a, b])[0] is a


def test_coach_separates_public_facts_from_inference():
    obs = _obs()
    obs['players'] = [{'seat': i, 'melds': [], 'river': [], 'flowers': []} for i in range(4)]
    obs['players'][1]['river'] = ['1万', '4万', '9万']
    result = EVCoach().explain({'observation': obs})
    text = result['explanation']
    assert '下家【事实】' in text and '弃万3张' in text
    assert '【推测】' in text and '可能' in text
    assert '下家可吃机会' in text and '可吃不代表一定吃' in text
    assert '常等' not in text and '高频等待' not in text
    assert '采样为零也不代表安全' in text


def test_compact_coach_unknown_opponents_have_no_explanatory_padding():
    result = EVCoach().explain({'observation': _obs()})
    brief = result['brief']
    assert len(brief['action']) < 20
    assert len(brief['reason']) < 30
    assert [p['seat'] for p in brief['opponents']] == ['下家', '对家', '上家']
    assert all(p['text'] == '无法推断' for p in brief['opponents'])
    assert result['explanation']  # 详细依据保留，界面默认折叠。
