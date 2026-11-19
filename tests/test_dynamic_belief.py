"""Live read models must respect actual concealed slots and hidden kong entities."""
from collections import Counter
import random

from src.core.probability import count_remaining_tiles
from src.core.math_core import opp_structural_total
from src.core.tiles import GameState, Meld, parse_tile as T
from src.decision.belief import HiddenWorld, sample_world
from src.decision.ev import evaluate_world
from src.decision.ev_bot import build_state_from_observation
from src.simulation.engine import Table
from src.simulation.observation import observe


def test_live_observation_samples_preserve_physical_counts_and_wall_length():
    for seed in range(8):
        observation = observe(Table(seed=seed), 0)
        state = build_state_from_observation(observation)
        world = sample_world(state, random.Random(seed))
        sampled = Counter(world.wall)
        for seat in world.hands:
            sampled.update(world.hands[seat])
            sampled.update(world.flowers[seat])
            assert len(world.hands[seat]) + len(world.flowers[seat]) == state.opponent_hand_counts[seat]
        assert sampled == Counter(count_remaining_tiles(state))
        assert len(world.wall) == observation['wall_count']


def test_unknown_kong_uses_four_identical_unseen_copies_and_counts_as_group():
    state = GameState(my_hand=[T('1万')],
                      opponent_hand_counts={'right':10,'left':13,'opposite':13},
                      opponent_unknown_kongs={'right':1})
    world = sample_world(state, random.Random(4))
    kong = world.melds['right'][0]
    assert kong.type == 'an_gang' and len(kong.tiles) == 4 and len(set(kong.tiles)) == 1
    assert kong.tiles[0] != T('1万')  # We see one copy, so it cannot be an unseen quad.
    sampled = Counter(world.wall)
    for seat in world.hands:
        sampled.update(world.hands[seat]);sampled.update(world.flowers[seat])
        for meld in world.melds[seat]:
            sampled.update(meld.tiles)
    assert sampled == Counter(count_remaining_tiles(state))
    assert opp_structural_total(state) == 40


def test_retained_flowers_take_slots_instead_of_being_dealt_on_top():
    state = GameState(opponent_hand_counts={s:13 for s in ('right','left','opposite')})
    flower_seen = False
    for seed in range(5):
        world = sample_world(state, random.Random(seed))
        for seat in world.hands:
            assert len(world.hands[seat])+len(world.flowers[seat]) == 13
            flower_seen |= bool(world.flowers[seat])
    assert flower_seen


def test_unknown_kong_qualifies_without_exposing_its_tile_type():
    state = GameState(opponent_hand_counts={'right':10}, opponent_unknown_kongs={'right':1})
    hand = list(map(T, '1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 5条'.split()))
    world = HiddenWorld({'right':hand}, {'right':[]}, [],
                        {'right':[Meld('an_gang',[T('北风')]*4)]})
    result = evaluate_world(world,state,[T('5条')])
    assert result['ronners'][T('5条')] == {'right'}
    assert result['confirmed'][T('5条')] == {'right'}


def test_held_flower_prevents_immediate_ron_even_when_structural_subhand_completes():
    state = GameState(opponent_hand_counts={'right':11}, opponent_unknown_kongs={'right':1})
    hand = list(map(T, '1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 5条'.split()))
    world = HiddenWorld({'right':hand}, {'right':[T('春')]}, [],
                        {'right':[Meld('an_gang',[T('北风')]*4)]})
    assert not evaluate_world(world,state,[T('5条')])['ronners'][T('5条')]


def test_changing_referee_hidden_hands_does_not_change_visible_strategy_state():
    from copy import deepcopy
    from src.decision.ev import rank_candidates
    for seed in range(50):
        table = Table(seed=seed)
        observation = observe(table, 0)
        if not observation['self']['held_flower_count']:
            break
    other = deepcopy(table)
    other.seats[1].hand[0], other.seats[2].hand[0] = other.seats[2].hand[0], other.seats[1].hand[0]
    a = build_state_from_observation(observation)
    b = build_state_from_observation(observe(other, 0))
    assert a == b
    assert rank_candidates(a, samples=8, seed=2) == rank_candidates(b, samples=8, seed=2)
