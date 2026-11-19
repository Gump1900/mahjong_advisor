"""One decision frame: model strategy, code-owned facts, no factual prose.

All concrete legal branches remain selectable, including defensive retreats.
This is a consistency boundary, not a policy rank or proof of playing strength.
"""
import copy
from collections import Counter
from itertools import combinations

from ..core.scoring import PATTERN_VALUES
from ..core.tiles import parse_tile, tile_sort_key
from .base import DecisionError
from .decision_guard import checked_summary
from .strategy_guard import (VERSION, INTENTS, PRIORITIES, TRIGGERS, COSTS,
                             shape_catalog, branch_hand, required_costs, validate_opponent, _list, _seats)
from .judgment import validate_judgment, render_judgment

PROTOCOL = "grounded-v2"
JUDGMENT_PROTOCOL = "grounded-v3"
PLAYABLE = tuple(f"{n}{s}" for s in ("万","饼","条") for n in range(1,10))+("南风","西风","北风")
INSTRUCTIONS = """
你是策略决策者。代码不排序或代选，所有合法具体分支均可选择，包括拆搭防守、退向听、暂留花。
只返回一个grounded-v3 JSON对象。judgment是你自己的主观取舍理由，其他事实不另写散文、不另抄牌数和计分。
selected与alternative从branches中选不同的branch_id；吃碰后的弃牌已经包含在该编号里。
先看decision_table：每项已列动作后的实际剩牌及状态，不必自己从原手牌再删一次。不可把不同分支的手牌、对子或指标混用。
opponents恰好其他三家。pattern_refs只能选该家pattern_options编号，ankan_refs只能选该家ankan_options编号。
没有依据时可空推测、low，不能从旧笔记恢复已排除的牌型。watch_tiles是推测，不是已知听口。
不再填写intent/priorities/arguments。comparisons每项直接对照首选和备选，topic只从comparison_topics选。
selected_refs至少一个首选事实编号，alternative_refs至少一个备选事实编号；不能跨侧引用。
effect只选selected/alternative/close/uncertain，表示这一项偏向哪边，不是总决策；总决策仍由你选。
opponent_refs和opponents.evidence_ids统一使用fact_catalog中的对手事实编号（event.N、seat.N.river、P N公开事实等原样键），不加E:前缀。不能引用其他家的专属证据。
防守比较必须有具体公开行动证据，并在对应对手watch_tiles或focus_suits说明关注方向；信息不足可不作防守推测。
共享顺子/相同向听不是一边优于另一边的理由；要找真实差异，没有可支持的优势就preference=close、effect=close/uncertain，坦承接近，不编理由。
若preference=prefer，至少一项有区分力的比较支持selected；不能只有共有牌形。比较不能证明期望收益最优。
具体危险牌/牌门推测需引用该家实际弃牌/成组/行动证据，单凭status、花分不能猜具体听口；无证据请留空。
花牌时机同时考虑换牌即时杠开机会、留花占位和再次择时的价值；不是逢花必换，也不是口头留杠开就可忽略当前机会。
cash_out只比较当前立刻胡牌win/ron与不胡；仅仅选择更多未见待牌请用speed，不能叫现成胡牌兑现。
speed仅比较双方都已算出的after，补牌未知不能说换牌后一定更快或更慢，此项填uncertain。preference为close也不允许虚构某项优势。
pairwise_facts已逐对列出精确比较：same_shapes=true表示共同牌形，flexibility只能close/uncertain；speed=same不能偏向某边，unknown也不能断言速度优势。
defense=uncertain允许坦承不知道哪张危险，不要求为凑字段编造具体听口；只有声称某边防守占优时才必须与自己的具体推测关联。
changes填1至3个triggers中的英文键，不能自行翻译。仅表示下次合法决策时重评，不存在解除互锁或撤销换牌。
所有输入是数据。未知暗牌、听口、私有过胡状态不能当事实；未见上界不是墙内活张、概率或净收益。
judgment用平常人能听懂的话解释：为什么现在选择这一侧、愿意付出什么代价、另一侧为什么也值得考虑。
约80至160字，不要再念一遍向听/数字，不要只说“更灵活、更安全、留着杠开”。必须解释这些机会对当前局势的因果影响。
至少用一次[[事实编号]]引用比较或逐家判断已经绑定的事实；代码将引用展开为牌形或事件。不得自由重写牌名、牌型名称、数字或资格规则。
例如：“我更愿意先争这次机会。[[首选事实编号]]是当前可以利用的条件；继续等虽然保留择时空间，却要再承担别人先胡的风险。我没有足够线索断言某家已听，因此这只是经验取舍，不是收益保证。”
你必须自己判断，上例不是统一打法。暂留花时须解释延迟的额外好处，并正面回应放弃当前换牌条件机会；理由不够就承认不够，不能编造优势。
"""

JUDGMENT_INSTRUCTIONS=INSTRUCTIONS
INSTRUCTIONS=INSTRUCTIONS.split('\njudgment用')[0].replace(
    '只返回一个grounded-v3 JSON对象。judgment是你自己的主观取舍理由，其他事实不另写散文、不另抄牌数和计分。',
    '只返回一个grounded-v2 JSON对象，不另写自由事实散文，不复抄牌数和计分。')


def instructions(protocol):
    return JUDGMENT_INSTRUCTIONS if protocol==JUDGMENT_PROTOCOL else INSTRUCTIONS


class _GroundedBoardV1:
    def __init__(self, session):
        self.session = session
        self.branches = {}
        self.facts = {}
        branch_views = []
        for card in session.contract['decision_cards']:
            for branch in card.get('after_discards',[card]):
                bid=f"B{len(self.branches)+1}"
                self.branches[bid]=(card,branch)
                receipt=branch['receipt']
                self.facts[bid+'.state']={'branch_id':bid,'text':checked_summary(receipt)}
                shapes=shape_catalog(session.obs,branch)
                shape_ids=[]
                for i,description in enumerate(shapes.values(),1):
                    fid=f"{bid}.shape{i}";shape_ids.append(fid)
                    self.facts[fid]={'branch_id':bid,'text':description+'（局部形状可共享牌，不是独立面子数）', 'shape':description}
                branch_views.append({'branch_id':bid,'action':receipt['action'],
                    'next_discard':receipt.get('next_discard'),'after':receipt.get('after'),
                    'costs':required_costs(session,{'action_id':card['action_id']},branch),
                    'shape_refs':shape_ids,'state_ref':bid+'.state'})
        visible=set(session.obs['self']['hand'])
        for player in session.obs['players']:
            visible.update(player['river']+player['flowers'])
            for meld in player['melds']:visible.update(meld['tiles'] or [])
        self.opponents={}
        for player in session.obs['players']:
            seat=player['seat']
            if seat==session.obs['seat']:continue
            constraint=next(c for c in session.payload['opponent_constraints'] if c['seat']==seat)
            patterns={f"P{seat}.pattern{i}":p for i,p in enumerate(PATTERN_VALUES,1) if p not in constraint['excluded_patterns']}
            ankans={f"P{seat}.ankan{i}":t for i,t in enumerate(PLAYABLE+('中','发','白','东风'),1)
                    if player['unknown_ankan_count'] and t not in visible}
            public_id=f"P{seat}.public";payment_id=f"P{seat}.payment"
            groups=' / '.join(m['type']+':'+('未知牌名' if m['tiles'] is None else ' '.join(m['tiles'])) for m in player['melds']) or '无'
            self.facts[public_id]={'seat':seat,'evidence_id':f'seat.{seat}.status',
                'text':f"座位{seat}公开成组{groups}；暗牌{player['hand_count']}张，可能含留花；是否听牌未知"}
            payment=session.tool('conditional_payment',{'winner':seat})
            if payment['publicly_cannot_ron']:
                payment_text=f"座位{seat}已互锁，不能接炮；仍可能自摸，逐家倍数{payment['zimo_payer_multipliers']}；互锁不因后续鸣牌解除"
            else:
                lower,upper=payment['conditional_subtotal_range']
                payment_text=f"若座位{seat}合法接炮，当前公开计分加未知暗杠部分为{lower}至{upper}；隐蔽风刻及牌型另计，不是最终总额范围、听牌证明或放炮概率"
            self.facts[payment_id]={'seat':seat,'evidence_id':f'seat.{seat}.status','text':payment_text}
            self.opponents[seat]={'seat':seat,'pattern_options':patterns,'ankan_options':ankans,
                'watch_options':list(PLAYABLE),'public_ref':public_id,'payment_ref':payment_id,
                'constraints':constraint,'conditional_payment':payment}
        public={k:copy.deepcopy(session.obs[k]) for k in ('observation_id','rules_version','seat','dealer','stage','actor',
               'wall_count','self','players','events','pending','call_counts','locked_pairs','legal_actions')}
        public['legal_actions']=[{**a,'id':session.reverse_handles[a['id']]} for a in public['legal_actions']]
        own=Counter(session.obs['self']['hand'])
        self.payload={'protocol':PROTOCOL,'public_table':public,'branches':branch_views,
            'fact_catalog':self.facts,'opponents':list(self.opponents.values()),
            'own_known_copies':dict(own),'opponent_ankan_excluded_by_known_copy':sorted(visible),
            'flower_opportunities':copy.deepcopy(session.payload['flower_opportunities']),
            'three_identical_flower_options':session.analysis['strategy_facts']['three_identical_flower_options'],
            'notebook':copy.deepcopy(session.payload['notebook']),
            'memory_invalidations':copy.deepcopy(session.payload['memory_invalidations']),
            'evidence_catalog':list(session.evidence),'priorities':PRIORITIES,'intents':INTENTS,'triggers':TRIGGERS,
            'limits':{'priorities':3,'arguments':[2,6],'fact_refs_per_argument':8,'changes':[1,3],
                      'patterns':4,'ankan_candidates':4,'watch_tiles':6,'evidence_ids':12},
            'scope':'只有自身手牌和公开信息；事实引用不证明策略最优，对手候选均为未证实推测。'}

    def template(self):
        return {'protocol':PROTOCOL,'selected':'B编号','alternative':'另一个B编号','intent':'合法意图',
            'priorities':['合法侧重'],'opponents':[{'seat':s,'pattern_refs':[],'focus_suits':[],
                'watch_tiles':[],'ankan_refs':[],'confidence':'low','evidence_ids':[f'seat.{s}.status']}
                for s in self.opponents],
            'arguments':[{'branch_id':'首选B编号','role':'support','priority':'合法侧重','fact_refs':['该分支state或shape事实编号'],
                          'opponent_seats':[]},
                         {'branch_id':'备选B编号','role':'uncertain','priority':'合法侧重','fact_refs':['该分支state或shape事实编号'],
                          'opponent_seats':[]}],
            'changes':[{'trigger':'合法改判条件','seat':None}]}

    def validate(self, frame):
        keys={'protocol','selected','alternative','intent','priorities','opponents','arguments','changes'}
        if not isinstance(frame,dict) or set(frame)-{'flower_batch'}!=keys or frame.get('protocol')!=PROTOCOL:
            raise DecisionError('需要完整grounded-v1决策框架，不接受旧格式或自由事实解释')
        for key in ('selected','alternative'):
            if not isinstance(frame[key],str) or frame[key] not in self.branches:
                raise DecisionError('选择了不存在的具体分支，未改选动作')
        if len(self.branches)>1 and frame['selected']==frame['alternative']:
            raise DecisionError('首选与备选须为不同具体分支')
        if not isinstance(frame['intent'],str) or frame['intent'] not in INTENTS:
            raise DecisionError('意图不合法')
        _list(frame['priorities'],set(PRIORITIES),'策略侧重',maximum=3,minimum=1)
        if not isinstance(frame['opponents'],list) or len(frame['opponents'])!=3:
            raise DecisionError('须覆盖另外三家')
        opponents=[]
        for raw in frame['opponents']:
            expected={'seat','pattern_refs','focus_suits','watch_tiles','ankan_refs','confidence','evidence_ids'}
            if not isinstance(raw,dict) or set(raw)!=expected or type(raw.get('seat')) is not int or raw['seat'] not in self.opponents:
                raise DecisionError('对手框架字段或座位不合法')
            options=self.opponents[raw['seat']]
            _list(raw['pattern_refs'],set(options['pattern_options']),'本家合法牌型编号',maximum=4)
            _list(raw['ankan_refs'],set(options['ankan_options']),'本家合法暗杠编号',maximum=4)
            item={k:copy.deepcopy(raw[k]) for k in ('seat','focus_suits','watch_tiles','confidence','evidence_ids')}
            item['patterns']=[options['pattern_options'][r] for r in raw['pattern_refs']]
            item['ankan_candidates']=[options['ankan_options'][r] for r in raw['ankan_refs']]
            opponents.append(validate_opponent(item,self.session.obs,self.session.evidence))
        if len({p['seat'] for p in opponents})!=3:raise DecisionError('对手座位重复')
        arguments=frame['arguments']
        if not isinstance(arguments,list) or not 2<=len(arguments)<=6:
            raise DecisionError('须提出2至6条首选／备选取舍依据')
        focuses=set();has_support=False;has_alternative=False;has_target_fact=False
        for arg in arguments:
            if not isinstance(arg,dict) or set(arg)!={'branch_id','role','priority','fact_refs','opponent_seats'}:
                raise DecisionError('比较依据必须引用事实，不能生成自由事实散文')
            if arg['branch_id'] not in (frame['selected'],frame['alternative']) or arg['role'] not in ('support','cost','uncertain'):
                raise DecisionError('比较依据指向了其他分支或非法作用')
            if not isinstance(arg['priority'],str) or arg['priority'] not in frame['priorities']:
                raise DecisionError('比较依据侧重须与本次策略一致')
            seats=_seats(arg['opponent_seats'],self.session.obs,'理由关联对手')
            _list(arg['fact_refs'],set(self.facts),'事实编号',maximum=8,minimum=1)
            if not any(self.facts[r].get('branch_id')==arg['branch_id'] for r in arg['fact_refs']):
                raise DecisionError('每条比较必须引用对应具体分支的事实')
            for ref in arg['fact_refs']:
                fact=self.facts[ref]
                if 'branch_id' in fact and fact['branch_id']!=arg['branch_id']:
                    raise DecisionError('不能把另一分支的牌形当成本分支保留牌形')
                if 'seat' in fact and fact['seat'] not in seats:
                    raise DecisionError('对手事实须与理由关联目标一致')
            if arg['priority']=='defense':
                if not seats or not any(self.facts[r].get('seat') in seats for r in arg['fact_refs']):
                    raise DecisionError('防守比较须关联实际对手及其公开事实')
            has_target_fact |= any(self.facts[r].get('seat') in seats for r in arg['fact_refs'])
            focuses.update(seats)
            has_support |= arg['branch_id']==frame['selected'] and arg['role']=='support'
            has_alternative |= arg['branch_id']==frame['alternative']
        if not has_support or not has_alternative:
            raise DecisionError('必须支持首选并实际讨论备选，不得只列一个动作')
        if ('defense' in frame['priorities'] or frame['intent'] in ('defend','defense')) and (not focuses or not has_target_fact):
            raise DecisionError('防守策略必须具体到其他玩家及其公开事实，不能只挂一个座位编号')
        if not isinstance(frame['changes'],list) or not 1<=len(frame['changes'])<=3:
            raise DecisionError('须提供1至3项下次决策的改判条件')
        for change in frame['changes']:
            if not isinstance(change,dict) or set(change)!={'trigger','seat'} or not isinstance(change['trigger'],str) or change['trigger'] not in TRIGGERS:
                raise DecisionError('改判条件不合法，不存在解除互锁或撤销换花触发器')
            if change['seat'] is not None:_seats([change['seat']],self.session.obs,'改判目标')
        return opponents,sorted(focuses)

    def resolve(self, frame):
        opponents,focus=self.validate(frame)
        return self._normalize(frame, opponents, focus)

    def _normalize(self, frame, opponents, focus):
        card,selected=self.branches[frame['selected']]
        alt_card,alt=self.branches[frame['alternative']]
        costs=required_costs(self.session,{'action_id':card['action_id']},selected)
        tradeoff=None
        if selected['requires_tradeoff']:
            category='defense' if 'defense' in frame['priorities'] else 'hand_value' if 'value' in frame['priorities'] else 'shape_improvement'
            ids=['self.hand']+[f'seat.{s}.status' for s in focus]
            tradeoff={'category':category,'evidence_ids':ids}
        answer={'strategy_version':VERSION,'action_id':card['action_id'],'action':copy.deepcopy(selected['receipt']['action']),
            'fact_check':copy.deepcopy(selected['receipt']),'tradeoff':tradeoff,
            'reasoning':{'intent':frame['intent'],'priorities':frame['priorities'],'focus_seats':focus,'accept_costs':costs,
                         'change_triggers':list(dict.fromkeys(c['trigger'] for c in frame['changes'])),'shape_refs':[]},
            'decision_note':{'opponents':opponents,'alternative_action_id':alt_card['action_id'],
                             'alternative_next_discard':alt['receipt'].get('next_discard')},
            '_grounded_frame':copy.deepcopy(frame)}
        if 'next_discard' in selected['receipt']:answer['next_discard']=selected['receipt']['next_discard']
        if 'flower_batch' in frame:answer['flower_batch']=copy.deepcopy(frame['flower_batch'])
        return answer

    def evaluate(self, answer):
        frame=answer['_grounded_frame'];normalized=self.resolve(frame)
        # Do not let an injected/tampered normalized answer override the model.
        if answer!=normalized:raise DecisionError('动作、事实与原决策框架不一致，未执行')
        legacy={k:v for k,v in normalized.items() if k!='_grounded_frame'}
        result=self.session.evaluate(legacy)
        self.session.flowers(normalized)
        result['explanation']=self.render(frame,result)
        result['grounding_protocol']=PROTOCOL
        result['decision_frame']=copy.deepcopy(frame)
        result['decision_note']['grounding_protocol']=PROTOCOL
        result['decision_note']['alternative_reason']='与首选同一决策框架：'+checked_summary(result['receipt'])+'；'+self.facts[frame['alternative']+'.state']['text']
        return result

    def render(self, frame, result):
        lines=['我选：'+self.facts[frame['selected']+'.state']['text'],
               '对照：'+self.facts[frame['alternative']+'.state']['text']]
        _,selected=self.branches[frame['selected']]
        if selected['receipt']['action']['kind']=='flower_kong':
            batch=frame.get('flower_batch') or selected['receipt']['action']['tiles']
            held=sum(parse_tile(t).is_flower for t in self.session.obs['self']['hand'])
            lines.insert(1,'本次选择换出'+'、'.join(batch)+f"，共{len(batch)}张；原手牌的留花还剩{held-len(batch)}张。补进什么牌尚未知，可能又有花；原留花或新花未清完不能胡。")
        for arg in frame['arguments']:
            role={'support':'支持这条路线','cost':'这条路线的取舍／顾虑','uncertain':'这条路线仍有不确定性'}[arg['role']]
            target='首选' if arg['branch_id']==frame['selected'] else '备选'
            facts='；'.join(self.facts[r]['text'] for r in arg['fact_refs'])
            lines.append(f"{target}：{role}，我{PRIORITIES[arg['priority']]}。核对依据：{facts}。这是策略侧重，不代表已证明哪条净收益更高。")
            for seat in arg['opponent_seats']:
                note=next(p for p in result['decision_note']['opponents'] if p['seat']==seat)
                lines.append(f"关联座位{seat}：{note['hypothesis']}；{note['uncertainty']}。")
        costs=result['reasoning']['accept_costs']
        if costs:lines.append('首选需要承担：'+'；'.join(COSTS[c] for c in costs)+'。')
        for opportunity in self.payload['flower_opportunities']:
            for win in opportunity['immediate_gangkai']:
                lines.append(f"换花条件机会：补到{win['tile']}可杠开，逐家付款{win['payments']}，未见上界{win['unseen_upper_bound']}；不保证补到，也不是命中概率。")
        own=Counter(self.session.obs['self']['hand'])
        lines.append('自己已持有的牌不可能同时被其他家四张暗杠：'+'、'.join(own)+'；持有单张也成立。')
        for options in self.opponents.values():lines.append(self.facts[options['payment_ref']]['text']+'。')
        for change in frame['changes']:
            target='' if change['seat'] is None else f"关注座位{change['seat']}，"
            lines.append('下次合法决策时，'+target+TRIGGERS[change['trigger']]+'；已执行的换牌不撤回，互锁不解除。')
        return '\n\n'.join(lines)


class GroundedBoard(_GroundedBoardV1):
    """Pairwise reasons, not duplicated strategy labels or generated facts.

    A valid reference is not necessarily a discriminating reason. Keep those
    checks separate, retain uncertain/equal choices, and never rank actions.
    """

    def __init__(self, session, protocol=PROTOCOL):
        if protocol not in (PROTOCOL,JUDGMENT_PROTOCOL):raise DecisionError('未知决策协议')
        super().__init__(session)
        self.protocol=protocol
        self.payload['protocol']=protocol
        for key, evidence in session.evidence.items():
            seat = evidence.get('seat')
            if seat not in self.opponents:
                continue
            # Status/payment alone cannot support a concrete dangerous tile.
            concrete = (key.endswith(('.river', '.melds')) or
                        key.startswith('event.') and evidence.get('kind') in
                        ('discard', 'chi', 'peng', 'ming_gang', 'jia_gang', 'an_gang'))
            self.facts[key] = {'seat':seat, 'evidence_id':key,
                'concrete':concrete, 'text':self._public_text(key,evidence)}
        self._add_flower_context()
        self.payload.pop('intents', None)
        self.payload.pop('priorities', None)
        self.payload['comparison_topics'] = {
            'speed':'已知结构距离、改善张和听口的比较；双方after已知才能断言优势，未知补牌填uncertain',
            'flexibility':'两条路线实际保留的不同局部牌形；共同拥有的形状不能证明某边更灵活',
            'defense':'结合具体对手实际行动推测不同弃牌的风险，不能宣称确定安全或危险',
            'value':'可核对资格花、互锁赔付或现成胡牌机会的差异；未知未来牌型不是已知打点',
            'flower_option':'现在换花与暂时留花的时机取舍；同时看补牌机会和留花占位代价',
            'avoid_lock':'吃碰口数或新增互锁的差异',
            'cash_out':'当前立即win/ron与放弃当前胡牌的比较；未胡牌的两种弃牌不能使用此项优势'}
        self.payload['evidence_catalog'] = [r for r,f in self.facts.items() if 'seat' in f]
        self.payload['previous_hypotheses_to_reassess'] = copy.deepcopy(session.reassessment_context)
        self.payload['comparison_effects'] = ['selected', 'alternative', 'close', 'uncertain']
        self.payload['pairwise_facts'] = {left+'|'+right:self._pair_facts(left,right)
            for left,right in combinations(self.branches,2)}
        table=[]
        for bid,(_,branch) in self.branches.items():
            receipt=branch['receipt'];kind=receipt['action']['kind']
            hand=branch_hand(session.obs,branch)
            table.append({'id':bid,'state':self.facts[bid+'.state']['text'],
                'remaining_known_hand':' '.join(sorted(hand,key=lambda t:tile_sort_key(parse_tile(t)))),
                'unknown_replacement_pending':kind in ('flower_kong','an_gang','ming_gang','add_gang'),
                'scope':'单张分支，未知补牌前；另选批量花时按实际批次重算'})
        self.payload={'protocol':protocol,'decision_table':table,**self.payload}
        self.payload['limits'] = {'comparisons':[1,len(PRIORITIES)], 'refs_per_side':[1,4],
            'opponent_refs':[0,4], 'changes':[1,3], 'patterns':4,
            'ankan_candidates':4, 'watch_tiles':6, 'evidence_ids':12}
        self.payload['submission_rules'] = {
            'preference':['prefer', 'close'],
            'branch_refs':'selected_refs/alternative_refs各引用对应分支的1至4个事实',
            'concrete_inference':'猜具体牌门、危险牌或暗杠候选，至少引用该家的实际弃牌、成组或行动证据',
            'defense':'opponent_refs必须包含实际行动证据，且对应假设覆盖所比较弃牌/牌门；不是已知危险',
            'prefer':'至少一项effect=selected，且该topic确有可核对差异；共享顺子不足以支持优势',
            'close':'没有能区分两者的依据可以承认接近；选择仍是模型选择，不由代码代选',
            'changes':'只填triggers里的英文键，不重复填写策略、座位或事实',
            'evidence_ids':'与opponent_refs完全共用fact_catalog，不存在E:别名；pattern_refs/ankan_refs仍来自该家专属目录'}

    def _add_flower_context(self):
        """Make existing exact flower tradeoffs citable, not a policy score."""
        plans=self.payload['three_identical_flower_options']
        opportunities=self.payload['flower_opportunities']
        for bid,(card,branch) in self.branches.items():
            receipt=branch['receipt'];parts=[]
            if plans:
                for plan in plans:
                    parts.append(f"动作前持{plan['held_count']}张{plan['tile']}，占{plan['occupied_hand_slots']}个位置；"
                        f"第四张未见上界{plan['fourth_copy_unseen_upper_bound']}，不保证在墙内。"
                        f"若最终取得第四张，四次单换共{plan['four_singles_hua']}花，四张一起暗杠{plan['four_concealed_kong_hua']}花；"
                        f"前者换{plan['four_singles_replacements']}张，后者换{plan['four_concealed_kong_replacements']}张并成一组。")
            for option in opportunities:
                for win in option['immediate_gangkai']:
                    tile=next(c for c in self.session.contract['decision_cards']
                              if c['action_id']==self.session.handles[option['action_id']])['receipt']['action']['tiles'][0]
                    parts.append(f"当前若单换{tile}后补到{win['tile']}可杠开，逐家付款{win['payments']}；"
                                 f"未见上界{win['unseen_upper_bound']}，不是活张或命中概率。")
            if not parts:continue
            if receipt.get('after',{} ) and receipt['after']['held_flower_count']:
                parts.append('本弃牌分支继续留花占位，当前不能胡牌；现在打出后须等下一次合法换花时机。')
            fid=bid+'.flower_context'
            self.facts[fid]={'branch_id':bid,'text':'动作前的换花取舍背景：'+' '.join(parts)}
            view=next(v for v in self.payload['branches'] if v['branch_id']==bid)
            view['context_refs']=[fid]

    def _pair_facts(self, left, right):
        """Exact pair contrasts for ALL actions; no recommendation or ranking."""
        l=self.branches[left][1]['receipt'];r=self.branches[right][1]['receipt']
        la,ra=l.get('after'),r.get('after')
        speed='unknown'
        if la and ra:
            lm=(la['structural_shanten'],-la['unseen_improving'])
            rm=(ra['structural_shanten'],-ra['unseen_improving'])
            speed='same' if lm==rm else left if lm<rm else right
        win=[bid for bid in (left,right) if self.branches[bid][1]['receipt']['action']['kind'] in ('win','ron')]
        shapes=lambda bid:{f['shape'] for f in self.facts.values() if f.get('branch_id')==bid and 'shape' in f}
        return {'speed':speed,'same_shapes':shapes(left)==shapes(right),
            'immediate_win':win,'flower_timing_difference':(l['action']['kind']=='flower_kong')!=(r['action']['kind']=='flower_kong'),
            }

    def _flower_conditions(self, bid):
        action_id=self.branches[bid][0]['action_id']
        return [win for option in self.payload['flower_opportunities']
                if self.session.handles[option['action_id']]==action_id
                for win in option['immediate_gangkai']]

    def _public_text(self, key, evidence):
        """Public evidence for teaching; never dump server JSON into prose."""
        seat=evidence['seat']
        if key.endswith('.status'):return self.facts[f'P{seat}.public']['text']
        if key.endswith('.river'):return f"座位{seat}已打出："+'、'.join(evidence['value'])
        if key.endswith('.melds'):return self.facts[f'P{seat}.public']['text']
        if key.startswith('event.'):
            kind=evidence.get('kind')
            name={'discard':'打出','chi':'吃','peng':'碰','ming_gang':'明杠',
                  'jia_gang':'加杠','an_gang':'暗杠','draw':'补牌' if evidence.get('replacement') else '摸牌',
                  'flower_kong':'换花'}.get(kind,'公开行动')
            tiles=evidence.get('tiles') or ([evidence['tile']] if 'tile' in evidence else [])
            tile_text='、'.join(tiles) if tiles else '（牌面未公开）'
            source=f"，取自座位{evidence['source']}" if 'source' in evidence else ''
            return f"第{int(key.split('.')[1])+1}个公开事件：座位{seat}{name}{tile_text}{source}"
        if key.endswith('.flowers'):return f"座位{seat}已换花："+'、'.join(evidence['value'])
        if key.endswith('.known_qualifying_hua'):return self.facts[f'P{seat}.payment']['text']
        if key.endswith('.locked_with'):return f"座位{seat}已互锁对象："+'、'.join(map(str,evidence['value']))
        if key.endswith('.call_counts'):return f"座位{seat}向座位0至3取牌口数："+'、'.join(map(str,evidence['call_counts']))
        return f"座位{seat}的公开记录（{key}）"

    def template(self):
        result={'protocol':self.protocol, 'selected':'B编号', 'alternative':'另一个B编号',
            'preference':'prefer或close',
            'opponents':[{'seat':s, 'pattern_refs':[], 'focus_suits':[],
                'watch_tiles':[], 'ankan_refs':[], 'confidence':'low', 'evidence_ids':[]}
                for s in self.opponents],
            'comparisons':[{'topic':'comparison_topics的键', 'effect':'selected/alternative/close/uncertain',
                'selected_refs':['首选B编号.state'], 'alternative_refs':['备选B编号.state'],
                'opponent_refs':[]}], 'changes':['own_improves']}
        if self.protocol==JUDGMENT_PROTOCOL:
            result['judgment']='用普通话说明当前取舍及代价，已知事实用[[本次比较绑定的事实编号]]引用，不重写牌名、牌型、数字或资格规则'
        return result

    def _difference(self, frame, comparison):
        """Existence of a topic-specific contrast, not an EV/policy verdict."""
        left = self.branches[frame['selected']][1]['receipt']
        right = self.branches[frame['alternative']][1]['receipt']
        topic = comparison['topic']
        la, ra = left.get('after') or {}, right.get('after') or {}
        if topic == 'speed':
            if not la or not ra:
                return (left['action']['kind'] in ('win','ron')) != (right['action']['kind'] in ('win','ron'))
            keys = ('structural_shanten', 'unseen_improving', 'ready', 'waiting_tiles', 'eligible_ron_tiles')
            return any(la.get(k) != ra.get(k) for k in keys) or (
                left['action']['kind'] in ('win','ron')) != (right['action']['kind'] in ('win','ron'))
        if topic == 'flexibility':
            shapes = lambda refs: {self.facts[r]['shape'] for r in refs if 'shape' in self.facts[r]}
            all_left=shapes([r for r,f in self.facts.items() if f.get('branch_id')==frame['selected']])
            all_right=shapes([r for r,f in self.facts.items() if f.get('branch_id')==frame['alternative']])
            return bool(shapes(comparison['selected_refs'])-all_right or
                        shapes(comparison['alternative_refs'])-all_left)
        if topic == 'cash_out':
            return (left['action']['kind'] in ('win','ron')) != (right['action']['kind'] in ('win','ron'))
        if topic == 'avoid_lock':
            return (left.get('creates_lock'),left.get('call_count_after')) != (
                right.get('creates_lock'),right.get('call_count_after'))
        if topic == 'flower_option':
            return (left['action']['kind']=='flower_kong') != (right['action']['kind']=='flower_kong')
        if topic == 'value':
            return (bool(la and ra) and la.get('qualifying_hua') != ra.get('qualifying_hua') or
                    bool(left.get('creates_lock')) != bool(right.get('creates_lock')) or
                    self._flower_conditions(frame['selected']) != self._flower_conditions(frame['alternative']) or
                    (left['action']['kind'] in ('win','ron')) != (right['action']['kind'] in ('win','ron')))
        # A target's concrete history is an inference input, not a known hazard.
        return topic == 'defense' and left['action'] != right['action']

    def _validated(self, frame):
        keys = {'protocol','selected','alternative','preference','opponents','comparisons','changes'}
        if self.protocol==JUDGMENT_PROTOCOL:keys.add('judgment')
        if not isinstance(frame,dict) or set(frame)-{'flower_batch'} != keys or frame.get('protocol') != self.protocol:
            raise DecisionError('需要完整'+self.protocol+'框架；不接受旧重复字段或其他版本输出')
        for key in ('selected','alternative'):
            if not isinstance(frame[key],str) or frame[key] not in self.branches:
                raise DecisionError('选择了不存在的具体分支，未改选动作')
        if len(self.branches)>1 and frame['selected']==frame['alternative']:
            raise DecisionError('首选与备选须为不同具体分支')
        if frame['preference'] not in ('prefer','close'):
            raise DecisionError('preference只能是prefer或close')
        comparisons = frame['comparisons']
        if not isinstance(comparisons,list) or not 1<=len(comparisons)<=len(PRIORITIES):
            raise DecisionError('须提交至少一项直接比较，各比较主题不得重复')
        priorities=[];arguments=[];supported=False
        for item in comparisons:
            if not isinstance(item,dict) or set(item)!={'topic','effect','selected_refs','alternative_refs','opponent_refs'}:
                raise DecisionError('成对比较字段不合法')
            _list([item['topic']],set(PRIORITIES),'比较主题',maximum=1)
            _list([item['effect']],{'selected','alternative','close','uncertain'},'比较方向',maximum=1)
            if item['topic'] in priorities:raise DecisionError('比较主题不得重复')
            priorities.append(item['topic'])
            for side in ('selected','alternative'):
                refs=_list(item[side+'_refs'],set(self.facts),'分支事实编号',maximum=4,minimum=1)
                if any(self.facts[r].get('branch_id')!=frame[side] for r in refs):
                    raise DecisionError('不能跨侧引用另一分支的牌形或事实')
            refs=_list(item['opponent_refs'],set(self.facts),'对手事实编号',maximum=4)
            if any('seat' not in self.facts[r] for r in refs):
                raise DecisionError('对手引用只能是公开对手事实')
            seats=sorted({self.facts[r]['seat'] for r in refs})
            if item['topic']=='defense':
                if not any(self.facts[r].get('concrete') for r in refs):
                    raise DecisionError('防守比较须有关联目标的实际公开行动证据')
                # Neither seat status nor scoring establishes the danger of a tile.
                notes=frame['opponents'] if isinstance(frame['opponents'],list) else []
                relevant=False
                for seat in seats:
                    note=next((n for n in notes if isinstance(n,dict) and n.get('seat')==seat),{})
                    for side in ('selected','alternative'):
                        action=self.branches[frame[side]][1]['receipt']['action']
                        for tile in action['tiles'] if action['kind']=='discard' else []:
                            if tile in note.get('watch_tiles',[]) or tile[-1:] in note.get('focus_suits',[]):
                                relevant=True
                if not relevant and item['effect'] in ('selected','alternative'):
                    raise DecisionError('防守比较须说明对应对手关注所比较的哪张牌或牌门，不能只挂座位')
            if item['effect']=='selected' and self._difference(frame,item):supported=True
            elif item['effect'] in ('selected','alternative') and not self._difference(frame,item):
                raise DecisionError('共有牌形或相同指标不能证明这一项偏向某边；请找实际差异或承认接近')
            if item['topic']=='cash_out' and item['effect'] in ('selected','alternative'):
                side=item['effect']
                if self.branches[frame[side]][1]['receipt']['action']['kind'] not in ('win','ron'):
                    raise DecisionError('立即兑现优势只能归于当前合法胡牌的一侧，不能把放弃胡牌称为现在兑现')
            if item['topic']=='speed' and item['effect'] in ('selected','alternative'):
                left=self.branches[frame['selected']][1]['receipt'].get('after')
                right=self.branches[frame['alternative']][1]['receipt'].get('after')
                if left and right:
                    # This checks only the claimed metric advantage. The model
                    # may still choose a slower branch for defense/value/etc.
                    metric=lambda a:(a['structural_shanten'],-a['unseen_improving'])
                    if metric(left)!=metric(right) and (metric(left)<metric(right)) != (item['effect']=='selected'):
                        raise DecisionError('速度指标方向与事实相反；可以选慢的一边，但须用其他取舍支持，不能称其速度占优')
            for side in ('selected','alternative'):
                arguments.append({'branch_id':frame[side],
                    'role':'support' if side=='selected' else 'uncertain',
                    'priority':item['topic'], 'fact_refs':item[side+'_refs']+refs,
                    'opponent_seats':seats})
        if frame['preference']=='prefer' and not supported:
            raise DecisionError('明确偏好须至少提供一项能区分两条路线的支持；无依据请承认接近')
        _list(frame['changes'],set(TRIGGERS),'改判条件',maximum=3,minimum=1)
        # Reuse hard opponent/action/receipt validation, not its old wire schema.
        raw_opponents=frame['opponents']
        if not isinstance(raw_opponents,list) or len(raw_opponents)!=3:
            raise DecisionError('须覆盖另外三家')
        normalized_opponents=[]
        for raw in raw_opponents:
            if not isinstance(raw,dict) or 'evidence_ids' not in raw:
                raise DecisionError('对手框架字段不合法')
            refs=_list(raw['evidence_ids'],set(self.payload['evidence_catalog']),'对手证据编号',maximum=12)
            if any(self.facts[r]['seat']!=raw.get('seat') for r in refs):
                raise DecisionError('对手证据须属于本家，不能跨家引用')
            # Exact, catalogue-declared reference expansion, not a guessed alias
            # or correction. Preserve the untouched wire frame for the audit.
            normalized=copy.deepcopy(raw)
            normalized['evidence_ids']=list(dict.fromkeys(self.facts[r]['evidence_id'] for r in refs))
            normalized_opponents.append(normalized)
        internal={'protocol':self.protocol,'selected':frame['selected'],'alternative':frame['alternative'],
            'intent':'balance','priorities':priorities,'opponents':normalized_opponents,
            'arguments':arguments,'changes':[{'trigger':t,'seat':None} for t in frame['changes']]}
        if 'flower_batch' in frame:internal['flower_batch']=copy.deepcopy(frame['flower_batch'])
        # V1's arbitrary three-priority/six-argument ceiling is not a mahjong
        # fact. V2 validates references above and opponents below directly.
        opponents=[]
        focuses={seat for arg in arguments for seat in arg['opponent_seats']}
        for raw in normalized_opponents:
            expected={'seat','pattern_refs','focus_suits','watch_tiles','ankan_refs','confidence','evidence_ids'}
            if set(raw)!=expected or type(raw.get('seat')) is not int or raw['seat'] not in self.opponents:
                raise DecisionError('对手框架字段或座位不合法')
            options=self.opponents[raw['seat']]
            _list(raw['pattern_refs'],set(options['pattern_options']),'本家合法牌型编号',maximum=4)
            _list(raw['ankan_refs'],set(options['ankan_options']),'本家合法暗杠编号',maximum=4)
            note={k:copy.deepcopy(raw[k]) for k in ('seat','focus_suits','watch_tiles','confidence','evidence_ids')}
            note['patterns']=[options['pattern_options'][r] for r in raw['pattern_refs']]
            note['ankan_candidates']=[options['ankan_options'][r] for r in raw['ankan_refs']]
            opponents.append(validate_opponent(note,self.session.obs,self.session.evidence))
        if len({p['seat'] for p in opponents})!=3:raise DecisionError('对手座位重复')
        for note in opponents:
            if note['watch_tiles'] or note['focus_suits'] or note['ankan_candidates']:
                concrete=[f for f in self.facts.values() if f.get('seat')==note['seat'] and
                          f.get('concrete') and f['evidence_id'] in note['evidence_ids']]
                if not concrete:
                    raise DecisionError('具体对手推测须引用该家实际弃牌、成组或行动，status或花分不足以猜牌')
        if self.protocol==JUDGMENT_PROTOCOL:validate_judgment(frame,self.facts)
        return internal,opponents,sorted(focuses)

    def validate(self, frame):
        _,opponents,focus=self._validated(frame)
        return opponents,focus

    def resolve(self, frame):
        internal,opponents,focus=self._validated(frame)
        answer=self._normalize(internal,opponents,focus)
        answer['_grounded_frame']=copy.deepcopy(frame)
        return answer

    def _quality_warnings(self, frame, result):
        warnings=[]
        costs=result['reasoning']['accept_costs']
        supported=[c for c in frame['comparisons'] if c['effect']=='selected']
        if frame['preference']=='prefer' and 'forego_gangkai' in costs and 'held_flowers' in costs:
            if not any(c['topic'] in ('defense','flexibility','avoid_lock') and self._difference(frame,c) for c in supported):
                warnings.append('本次暂留花放弃了明确的即时杠开条件机会，但模型未给出具体防守或保留牌形上的优势；延期理由仍不足，不能称为已证明更好的打法。')
        return warnings

    def evaluate(self, answer):
        result=super().evaluate(answer)
        frame=answer['_grounded_frame']
        result['grounding_protocol']=self.protocol
        result['decision_note']['grounding_protocol']=self.protocol
        result['comparison_audit']={'preference':frame['preference'],
            'differentiating_support_count':sum(c['effect']=='selected' and self._difference(frame,c) for c in frame['comparisons']),
            'quality_warnings':self._quality_warnings(frame,result),
            'strategy_verdict':'unreviewed',
            'scope':'事实与引用一致不等于读牌准确或打法最优；不得以此自动写入知识库'}
        if self.protocol==JUDGMENT_PROTOCOL:
            result['strategic_judgment']=validate_judgment(frame,self.facts)
            result['decision_note']['judgment']=copy.deepcopy(result['strategic_judgment'])
        return result

    def render(self, frame, result):
        # The action and all factual claims are still server-owned.
        lines=['我建议：'+self.facts[frame['selected']+'.state']['text'],
               '另一种打法：'+self.facts[frame['alternative']+'.state']['text']]
        if self.protocol==JUDGMENT_PROTOCOL:
            lines.insert(1,'军师的取舍（模型判断，不是计算证明）：'+render_judgment(validate_judgment(frame,self.facts),self.facts))
        if frame['preference']=='close':
            lines.append('目前没有充分依据说首选明显更好，两种打法接近；这次选择不是最优结论。')
        for item in frame['comparisons']:
            direction={'selected':'这项我更倾向首选','alternative':'这项反而支持备选，是首选的取舍',
                       'close':'这项暂时分不出高下','uncertain':'这项信息不足，不能断言哪边更好'}[item['effect']]
            names={'speed':'成牌机会','flexibility':'后续牌形','defense':'防守风险',
                   'value':'条件收益','flower_option':'换花时机','avoid_lock':'互锁代价','cash_out':'现在兑现'}
            lines.append('看'+names[item['topic']]+'，'+direction+'。')
            if item['topic']=='speed':
                la=self.branches[frame['selected']][1]['receipt'].get('after')
                ra=self.branches[frame['alternative']][1]['receipt'].get('after')
                if la and ra:
                    lines.append(f"首选结构{la['structural_shanten']}向听、未见改善张{la['unseen_improving']}；备选结构{ra['structural_shanten']}向听、未见改善张{ra['unseen_improving']}。这只是公开信息下的牌效，不是活张或命中率。")
                else:
                    lines.append('其中一条路线没有确定的动作后牌效，不能把未知摸补牌当成已知结果。')
            if item['topic']=='cash_out' and item['effect']=='selected':
                lines.append('现在胡可以结算已有机会；继续打则要重新等牌，也承担别人先胡的风险。我选择先兑现。')
            for side,label in [('selected','首选'),('alternative','备选')]:
                shapes=[self.facts[r]['text'] for r in item[side+'_refs'] if 'shape' in self.facts[r]]
                if shapes:lines.append(label+'关注的局部牌形：'+'；'.join(shapes)+'。')
            if item['topic']=='flower_option':
                selected_kind=self.branches[frame['selected']][1]['receipt']['action']['kind']
                lines.append('现在换花能马上取得补牌机会，留花则保留以后择时的选择，但继续占位、未清花不能胡。'+
                    ('本次选择先换，不是为了以后留住已换出的花。' if selected_kind=='flower_kong' else
                     '本次选择暂留；这会放弃当前换牌机会，必须承担占位代价。'))
            for ref in item['opponent_refs']:
                fact=self.facts[ref];seat=fact['seat']
                name={1:'下家',2:'对家',3:'上家'}[(seat-self.session.obs['seat'])%4]
                lines.append(name+'的公开依据：'+fact['text']+'。')
        costs=result['reasoning']['accept_costs']
        if costs:lines.append('这次要承担：'+'；'.join(COSTS[c] for c in costs)+'。')
        lines.extend('分析质量提醒：'+warning for warning in self._quality_warnings(frame,result))
        for note in result['decision_note']['opponents']:
            name={1:'下家',2:'对家',3:'上家'}[(note['seat']-self.session.obs['seat'])%4]
            lines.append(name+'：'+note['hypothesis']+'。这是推测，不是已知手牌或听口。')
        selected=self.branches[frame['selected']][1]['receipt']
        if selected['action']['kind']=='flower_kong':
            batch=frame.get('flower_batch') or selected['action']['tiles']
            held=sum(parse_tile(t).is_flower for t in self.session.obs['self']['hand'])
            lines.append('本次换出'+'、'.join(batch)+f'，共{len(batch)}张；原手牌的留花还剩{held-len(batch)}张。补进什么牌尚未知，可能又有花；未清花不能胡。')
        for opportunity in self.payload['flower_opportunities']:
            for win in opportunity['immediate_gangkai']:
                lines.append(f"当前换花条件机会：补到{win['tile']}可杠开，逐家付款{win['payments']}，未见上界{win['unseen_upper_bound']}；不是墙内活张或命中概率。")
        for options in self.opponents.values():lines.append(self.facts[options['payment_ref']]['text']+'。')
        lines.append('下次合法决策：'+'；'.join(TRIGGERS[t] for t in frame['changes'])+'；已执行的换牌不能撤回，互锁不解除。')
        return '\n\n'.join(lines)
