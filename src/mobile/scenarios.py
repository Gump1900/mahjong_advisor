"""Reproducible adapter cases built from a complete physical deck, never fake scores."""
import random
from collections import Counter

from src.core.tiles import parse_tile
from src.simulation.engine import Table
from src.simulation.state import full_deck

HANDS = {
    'flowers': '1万 2万 3万 4万 5万 6万 2饼 3饼 4饼 2条 3条 南风 春 中',
    'chi': '1条 2条 4条 1万 2万 3万 4万 5万 6万 7饼 8饼 南风 南风',
    'peng': '5饼 5饼 1万 2万 3万 4万 5万 6万 2条 3条 4条 南风 南风',
    'ming': '北风 北风 北风 1万 2万 3万 4万 5万 6万 2条 3条 南风 南风',
    'an': '北风 北风 北风 北风 1万 2万 3万 4万 5万 6万 2条 3条 南风 南风',
    'tenpai': '1万 2万 3万 4万 5万 6万 2饼 3饼 4饼 2条 3条 南风 南风 8饼',
    'win': '1万 2万 3万 4万 5万 6万 2饼 3饼 4饼 1条 2条 3条 南风 南风',
}


def create_table(seed, scenario='random'):
    if scenario == 'random':
        return Table(seed)
    if scenario not in HANDS:
        raise ValueError('未知手机测试场景')
    claims = {'chi': (3, '3条'), 'peng': (1, '5饼'), 'ming': (1, '北风')}
    dealer, pending = claims.get(scenario, (0, None))
    hand = [parse_tile(t) for t in HANDS[scenario].split()]
    deck = full_deck()
    random.Random(seed).shuffle(deck)
    # Install chosen cards into the standard round-robin deal positions.
    fixed = {r*4+(0-dealer)%4: t for r, t in enumerate(hand[:13])}
    fixed[52] = parse_tile(pending) if pending else hand[13]
    remaining = Counter(deck) - Counter(fixed.values())
    rest = []
    for t in deck:
        if remaining[t]:
            rest.append(t)
            remaining[t] -= 1
    iterator = iter(rest)
    wall = [fixed[i] if i in fixed else next(iterator) for i in range(144)]
    table = Table(seed, dealer, wall=wall)
    if pending:
        action = next(a for a in table.legal_actions(dealer) if a.kind == 'discard' and str(a.tiles[0]) == pending)
        table.apply(dealer, action.id, controller='fixture:mobile')
    return table
