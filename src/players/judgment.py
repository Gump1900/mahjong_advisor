"""A bounded model opinion channel, distinct from code-owned facts.

References and a narrow contradiction screen are checkable. The causal quality
of prose is NOT mechanically verified; never describe this as strategy proof.
"""
import re

from ..core.scoring import PATTERN_VALUES
from .base import DecisionError

REFERENCE = re.compile(r'\[\[([^\[\]\n]+)\]\]')


def validate_judgment(frame, facts):
    text=frame.get('judgment')
    if not isinstance(text,str) or not 24<=len(text.strip())<=600:
        raise DecisionError('judgment须为24至600字符的主观取舍理由，不重抄事实')
    allowed=set()
    for comparison in frame['comparisons']:
        for key in ('selected_refs','alternative_refs','opponent_refs'):
            allowed.update(comparison[key])
    for opponent in frame['opponents']:
        allowed.update(opponent['evidence_ids'])
    refs=REFERENCE.findall(text)
    if any(ref not in allowed or ref not in facts for ref in refs):
        raise DecisionError('取舍理由引用必须来自本次比较或逐家判断已绑定的事实，不能另借分支')
    if not refs:
        raise DecisionError('取舍理由须用[[事实编号]]关联至少一项本次实际依据')
    prose=REFERENCE.sub('',text)
    if '[[' in prose or ']]' in prose:
        raise DecisionError('取舍理由的事实引用未闭合')
    # No second hand/score/wait transcript. Qualitative opinions may still be
    # wrong; these checks intentionally do not claim general semantic proof.
    tile=r'[一二三四五六七八九](?:万|饼|筒)|[一二三四五六七八九]条(?!路线|理由|建议|线索|信息|证据|规则|路径)|[东南西北]风|红中|白板|发财'
    if re.search(r'\d|[%％]|'+tile,prose) or any(pattern in prose for pattern in PATTERN_VALUES):
        raise DecisionError('主观理由不另抄牌名、牌型或数字；请引用对应代码事实')
    if re.search(r'(?:绝对|一定|肯定|保证|必然).{0,8}(?:安全|能胡|成牌|放炮|暗杠)|(?:已经|已然|确定)(?:听牌|成牌)|解除互锁|抢杠胡|摸牌前开杠|(?:可以|不能|只能|恢复)(?:接炮|碰牌|自摸)',prose):
        raise DecisionError('取舍理由不能另立资格规则或将未知风险说成确定事实')
    return {'text':text.strip(),'fact_refs':list(dict.fromkeys(refs)),
            'scope':'模型主观取舍；引用已核对，不等于因果论证正确、读牌准确或收益最优'}


def render_judgment(judgment, facts):
    return REFERENCE.sub(lambda m:'「'+facts[m[1]]['text']+'」',judgment['text'])
