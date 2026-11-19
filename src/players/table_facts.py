"""Small, deterministic fact ledger and bounded prose checks for table-v1.

No action ranking, hidden information, model retry or strategic verdict. A
matched contradiction withholds commentary, never substitutes another action.
Natural language outside these explicit claim forms remains unverified.
"""
from collections import Counter
import re

from ..core.tiles import parse_tile
from .base import DecisionError
from .decision_guard import _melds, _qualification
from .strategy_guard import branch_hand


def current_facts(obs):
    hand = [parse_tile(t) for t in obs['self']['hand']]
    melds = _melds(obs)
    player = obs['players'][obs['seat']]
    flowers = [parse_tile(t) for t in player['flowers']]
    qualifying = _qualification(hand, melds, flowers)
    wind_facts = {}
    for name in ('南风', '西风', '北风'):
        tile = parse_tile(name)
        matching = [m for m in melds if m.tiles[0] == tile]
        same_hand = [t for t in hand if t == tile]
        contribution = _qualification(same_hand, matching, [])['total']
        wind_facts[name] = {'hand_copies': len(same_hand),
            'meld_types': [m.type for m in matching], 'qualifying_hua': contribution}
    return {'hand_count_including_held_flowers': len(hand),
        'held_flower_count': sum(t.is_flower for t in hand),
        'exchanged_flower_counts': dict(Counter(player['flowers'])),
        'qualifying_hua': qualifying, 'winds': wind_facts,
        'scope': '当前已知资格花，未含胡法底分/牌型加分，不是已获收入；留花未换出不计这里的资格花。'}


def action_effect(obs, branch, batch=None):
    """Known count changes; replacement TILE is deliberately never predicted.

    For a single/batch flower exchange counts describe a completed exchange,
    not the intermediate remove-before-draw state. Chi/peng include the exact
    planned discard. Pass/win do not project a future own draw.
    """
    action = branch['receipt']['action']
    kind = action['kind']
    before = len(obs['self']['hand'])
    known = branch_hand(obs, branch)
    replacements = int(kind in ('flower_kong', 'an_gang', 'ming_gang', 'add_gang'))
    if kind == 'flower_kong' and batch:
        # Callers first validate the entire physical batch with session.flowers.
        replacements = len(batch)
        known = list(obs['self']['hand'])
        for tile in batch:
            known.remove(tile)
    return {'hand_count_before': before,
        'known_hand_count_before_replacement': len(known),
        'replacement_count': replacements,
        'hand_count_after_completed_action': len(known)+replacements,
        'held_flower_count_before_replacement': sum(parse_tile(t).is_flower for t in known),
        'replacement_contents': 'unknown' if replacements else 'not_applicable',
        'scope': '吃碰含计划弃牌；补牌可能仍是花，补后留花数/向听/资格花不预报。过/胡不包含下一次摸牌。'}


def fact_summary(facts, effect):
    q = facts['qualifying_hua']
    lines = [f"当前手牌{facts['hand_count_including_held_flowers']}张（含留花{facts['held_flower_count']}张）。",
        f"当前可核对资格花{q['total']}：已换花{q['flowers']}、明风刻{q['wind_triplets']}、暗风刻{q['concealed_wind_triplets']}、杠{q['kongs']}；未胡尚未兑现。"]
    if effect['replacement_count']:
        lines.append(f"本动作补{effect['replacement_count']}张，完成后手牌{effect['hand_count_after_completed_action']}张；补牌内容未知。")
    return ''.join(lines)


def _number(text):
    if text.isdecimal():
        return int(text)
    digits = {'零': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4,
              '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
    if '十' in text:
        a, b = text.split('十', 1)
        return (digits.get(a, 1) if a else 1)*10+(digits.get(b, 0) if b else 0)
    return digits.get(text)


NUM = r'(?:\d+|[零一二两三四五六七八九十]+)'


def check_table_claims(text, facts, effect):
    """Only explicit current/count claims, with local negation/future scope.

    Conditional clauses and before-draw counts are not reinterpreted as
    current/final claims. Do not let '如果' in another sentence exempt a false
    current assertion. This is a limited screen, not general language proof.
    """
    text = text.replace('餅', '饼').replace('條', '条')
    for clause in re.split(r'[，,。；;！!？?\n]', text):
        if not clause.strip():
            continue
        future = bool(re.search(r'如果|假如|假设|若|一旦|等到|以后|将来|凑成|凑齐|才能|才会|不是说|并非|不代表|不意味着', clause))
        if future:
            continue
        if effect['replacement_count']:
            # Counts explicitly associated with the unknown replacement's
            # absence refer to an intermediate state, not a smaller final hand.
            before_draw = bool(re.search(r'补牌前|补回前|尚未补|未补牌|补牌之前|补回之前', clause))
            expected = effect['known_hand_count_before_replacement'] if before_draw else effect['hand_count_after_completed_action']
            match = re.search(r'(?:手牌|暗牌)(?:总共|共|会|将|仍|还是|保持|只有|仅有|变成|变为|缩回|缩到|减至|减为|回到|剩下|剩|数是|张数为|为|是|降到|缩减到|恢复为|补回到|补至|补到|含花|含留花|变回|回归|仍为|仅剩|还剩|就|有|的|只|仅|还|从'+NUM+r'张)*\s*('+NUM+r')张', clause)
            # “手牌四张花占位” counts a SUBSET, not the whole hand.
            # Do not compare this against the completed hand's total count.
            if match and re.match(r'\s*(?:留花|花牌|花)', clause[match.end():]):
                match = None
            other_subject = bool(match and re.search(r'对手|上家|下家|对家|别人|座位[0-3]', clause[:match.start()]))
            if match and not other_subject and _number(match[1]) != expected:
                raise DecisionError('换花/杠的手牌张数与代码事实冲突；移出与补牌不能混为完成后的张数')
        for wind, info in facts['winds'].items():
            if wind in clause and re.search(r'对手|上家|下家|对家|别人|座位[0-3]', clause[:clause.index(wind)]):
                continue  # Never apply OWN wind counts to another player's claim.
            # Generic rules ('南风刻子算1花') are true; screen only explicit
            # present attribution or a claim that an isolated wind itself scores.
            claims = (rf'{wind}.{{0,16}}(?:已|已经)(?:经|被|算作|算进|计入|算入|算|有|是).{{0,8}}(?:资格花|花分|花)',
                      rf'{wind}(?:本身|单张|孤张).{{0,12}}(?:算|计|提供|属于|就是).{{0,6}}(?:资格花|花分|{NUM}花)')
            if not info['qualifying_hua'] and any(re.search(p, clause) for p in claims):
                if not re.search(r'不(?:能|会|可|算|是)|没有|未计|未算|不计|不能算', clause):
                    raise DecisionError(f'{wind}当前没有可计分风刻/杠；不能把单张风牌算成已有资格花')
