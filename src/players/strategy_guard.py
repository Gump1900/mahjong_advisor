"""Bounded strategic choices, not unrestricted factual prose or a policy rank.

The model picks the action, hypotheses, priorities and accepted costs. Code
checks possibility and renders known facts. Old free text is never rendered or
reused as memory. This does NOT establish optimal play or calibrated inference.
"""
import copy
import hashlib
import json
from collections import Counter

from ..core.scoring import PATTERN_VALUES
from ..core.tiles import parse_tile
from .base import DecisionError
from .decision_guard import checked_summary
from .tactical_facts import opponent_constraints
from .strategy_facts import pair_completions

VERSION = "strategy-v2"
PRIORITIES = {"speed":"更看重先成牌的机会", "defense":"愿意为防守让出一些进攻机会",
              "value":"更看重成牌后的收益", "flexibility":"更看重后续调整空间",
              "flower_option":"更看重留花后再选择换牌的机会", "avoid_lock":"希望避免新增互锁",
              "cash_out":"倾向先兑现已有机会，不继续等待更大的收益"}
# A priority can also be the model's primary intent. Preserve its exact choice
# instead of translating speed into attack or guessing intent from free prose.
# Legacy intent names remain valid for saved replies and historical reviews.
INTENTS = {**PRIORITIES, "attack":"争取先成牌", "defend":"优先控制放炮风险",
           "balance":"兼顾推进和风险", "value":"保留更高收益的机会",
           "flower_timing":"权衡现在换花与留花的时机"}
DEFENSIVE_INTENTS = frozenset({"defend", "defense"})
TRIGGERS = {"opponent_claims":"对手新增吃碰杠时重新评估", "opponent_value_rises":"对手公开花分增加时重新评估",
            "own_improves":"自己得到新的成组或待牌机会时重新评估", "unseen_changes":"目标牌的公开副本变化时重新评估",
            "lock_changes":"互锁关系变化时重新评估", "wall_shrinks":"牌墙进一步变少时重新评估"}
COSTS = {"speed_loss":"接受结构距离或未见改善张上的损失", "held_flowers":"接受留花占位、当前不能胡牌",
         "lock":"接受新增互锁及其接炮／赔付限制", "decline_win":"放弃当前合法胡牌机会",
         "forego_gangkai":"放弃当前明确列出的换花即时杠开机会"}
OPPONENT_FIELDS = {"seat", "patterns", "focus_suits", "watch_tiles", "ankan_candidates", "confidence", "evidence_ids"}


def _list(value, allowed, label, *, maximum=12, minimum=0):
    if isinstance(value,list) and all(isinstance(v,str) for v in value):
        unknown=[v for v in value if v not in allowed]
        if unknown:
            raise DecisionError(f"{label}含未提供选项："+"、".join(unknown)+
                                "；合法选项："+"、".join(sorted(allowed)))
    if (not isinstance(value, list) or not minimum <= len(value) <= maximum
            or any(not isinstance(v, str) or v not in allowed for v in value)
            or len(value) != len(set(value))):
        raise DecisionError(f"{label}必须为不重复的合法选项")
    return list(value)


def _seats(value, obs, label):
    other = {p["seat"] for p in obs["players"] if p["seat"] != obs["seat"]}
    if (not isinstance(value, list) or len(value)>3 or any(type(s) is not int or s not in other for s in value)
            or len(value) != len(set(value))):
        raise DecisionError(f"{label}只能引用其他三家且不得重复")
    return list(value)


def _fingerprint(player):
    # Allow-listed public data only, including fully opaque ankan markers.
    return hashlib.sha256(json.dumps(player, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _visible(obs):
    names = set(obs["self"]["hand"])
    for p in obs["players"]:
        names.update(p["river"]+p["flowers"])
        for m in p["melds"]:
            names.update(m["tiles"] or [])
    return names


def validate_opponent(item, obs, evidence):
    """No prose assertions: every hypothesis is bounded and possible, not true."""
    if not isinstance(item, dict) or set(item) != OPPONENT_FIELDS:
        raise DecisionError("对手假设必须使用结构化字段，不接受自由牌型描述")
    seat = item["seat"]
    if type(seat) is not int or seat not in {p["seat"] for p in obs["players"] if p["seat"] != obs["seat"]}:
        raise DecisionError("对手笔记座位错误")
    try:
        patterns = _list(item["patterns"], set(PATTERN_VALUES), "可能牌型", maximum=4)
    except DecisionError:
        raise DecisionError("可能牌型patterns仅可选计分牌型："+"、".join(PATTERN_VALUES)+
                            "；最多4项不重复，不确定填[]；防守、做牌速度、花分高不是牌型") from None
    constraint = next(c for c in opponent_constraints(obs) if c["seat"] == seat)
    impossible = set(patterns) & set(constraint["excluded_patterns"])
    if impossible:
        public = next(p for p in obs["players"] if p["seat"]==seat)
        raise DecisionError("对手公开信息已排除牌型："+"、".join(sorted(impossible))+
                            f"；目标座位{seat}，公开成组"+
                            json.dumps(public["melds"],ensure_ascii=False)+
                            "；必须按该座位opponent_constraints.excluded_patterns排除，不确定填[]")
    suits = _list(item["focus_suits"], {"万","饼","条"}, "关注牌门", maximum=3)
    playable = {f"{n}{s}" for s in ("万","饼","条") for n in range(1,10)} | {"南风","西风","北风"}
    watched = _list(item["watch_tiles"], playable, "推测危险牌", maximum=6)
    ankan = _list(item["ankan_candidates"], playable | {"中","发","白","东风"}, "暗杠候选", maximum=4)
    p = next(p for p in obs["players"] if p["seat"] == seat)
    if ankan and (not p["unknown_ankan_count"] or set(ankan) & _visible(obs)):
        raise DecisionError("未知暗杠候选与暗杠记录或已知副本冲突")
    confidence = item["confidence"]
    if confidence not in ("low","medium","high"):
        raise DecisionError("推断只能使用定性把握，不伪造概率")
    ids = _list(item["evidence_ids"], set(evidence), "推断证据", maximum=12)
    if not ids and (confidence != "low" or patterns or suits or watched or ankan):
        raise DecisionError("无证据只能低把握并明确信息不足")
    # Evidence belonging only to a different player cannot support this target.
    def belongs(key):
        value = evidence[key]
        return value.get("seat") == seat or value.get("source") == seat
    if ids and not any(belongs(k) for k in ids):
        raise DecisionError("推断证据未关联被分析的对手")
    return {"seat":seat,"patterns":patterns,"focus_suits":suits,"watch_tiles":watched,
            "ankan_candidates":ankan,"confidence":confidence,"evidence_ids":ids}


def render_opponent(item):
    parts = []
    if item["patterns"]:
        parts.append("可能的牌型路线："+"、".join(item["patterns"]))
    if item["focus_suits"]:
        parts.append("推测需留意"+"、".join(item["focus_suits"])+"门")
    if item["watch_tiles"]:
        parts.append("推测需留意的牌："+"、".join(item["watch_tiles"]))
    if item["ankan_candidates"]:
        parts.append("未知暗杠的候选："+"、".join(item["ankan_candidates"])+"，不是已知牌名")
    return {**copy.deepcopy(item), "hypothesis":"；".join(parts) if parts else "信息不足，暂不锁定牌型或听口",
            "uncertainty":"以上只是模型假设；是否听牌、具体暗牌和私有过胡状态未知",
            "revision_trigger":"公开弃牌、吃碰杠、花分或互锁变化后重新核对"}


def refresh_memory(notebook, obs, evidence):
    """Drop free-form legacy notes; expire changed targets before API input."""
    if notebook is None:
        return None, []
    if not isinstance(notebook, dict) or notebook.get("version") != VERSION:
        return None, [{"reason":"legacy_unstructured_memory"}]
    result = {"version":VERSION, "opponents":[]}
    invalidations = []
    players = {p["seat"]:p for p in obs["players"]}
    seen = set()
    if not isinstance(notebook.get("opponents"),list):
        return None,[{"reason":"invalid_memory_record"}]
    for old in notebook["opponents"]:
        if not isinstance(old,dict) or type(old.get("seat")) is not int or old["seat"] not in players or old["seat"] in seen:
            invalidations.append({"reason":"invalid_memory_record"});continue
        seat = old["seat"];seen.add(seat)
        raw = {k:copy.deepcopy(old.get(k)) for k in OPPONENT_FIELDS}
        try:
            validate_opponent(raw,obs,evidence)
            if old.get("public_fingerprint") != _fingerprint(players[seat]):
                raise DecisionError("public_state_changed")
        except DecisionError as exc:
            # Do not carry the old false assertion even in the invalidation text.
            invalidations.append({"seat":seat,"reason":"public_state_changed_or_hypothesis_invalid"})
            continue
        result["opponents"].append({**raw,"public_fingerprint":old["public_fingerprint"]})
    return result, invalidations


def memory_note(note, obs):
    players = {p["seat"]:p for p in obs["players"]}
    return {"version":VERSION,"observed_event_count":len(obs['events']),"opponents":[
        {**{k:copy.deepcopy(p[k]) for k in OPPONENT_FIELDS},"public_fingerprint":_fingerprint(players[p["seat"]])}
        for p in note["opponents"]]}


def required_costs(session, answer, branch):
    costs = []
    if branch["requires_tradeoff"]:
        costs.append("speed_loss")
    receipt = branch["receipt"]
    if receipt.get("after",{} ) and receipt["after"]["held_flower_count"]:
        costs.append("held_flowers")
    if receipt.get("creates_lock"):
        costs.append("lock")
    kind = receipt["action"]["kind"]
    if kind not in ("win","ron") and any(a["kind"] in ("win","ron") for a in session.obs["legal_actions"]):
        costs.append("decline_win")
    if any(f["immediate_gangkai"] and session.handles[f["action_id"]] != answer["action_id"]
           for f in session.payload["flower_opportunities"]):
        costs.append("forego_gangkai")
    return costs


def branch_for(session, action_id, discard=None):
    card = next((c for c in session.contract["decision_cards"] if c["action_id"] == action_id),None)
    if card is None:
        raise DecisionError("策略引用非法或过期动作")
    if not card.get("after_discards"):
        return card
    branch = next((b for b in card["after_discards"] if b["tile"] == discard),None)
    if branch is None:
        raise DecisionError("吃碰对照必须填写合法后续弃牌")
    return branch


def branch_hand(obs, branch):
    """Known hand after an action, before any unknown replacement.

    Shared by shape checks and input so models need not subtract twice.
    """
    receipt = branch["receipt"]; action = receipt["action"]
    hand = list(obs["self"]["hand"]);kind = action["kind"]
    if kind in ("discard","flower_kong","add_gang"):
        hand.remove(action["tiles"][0])
    elif kind in ("an_gang","ming_gang"):
        for _ in range(4 if kind=="an_gang" else 3):
            hand.remove(action["tiles"][0])
    elif kind in ("chi","peng"):
        claimed = obs["pending"]["tile"]
        needed = list(action["tiles"]) if kind == "chi" else [claimed]*3
        needed.remove(claimed)
        for t in needed:
            hand.remove(t)
        hand.remove(receipt["next_discard"])
    return hand


def shape_catalog(obs, branch):
    """Local shapes in this specific branch, never counted as disjoint sets."""
    hand=branch_hand(obs,branch)
    counts = Counter(t for t in hand if not parse_tile(t).is_flower)
    catalog = {}
    for t,n in counts.items():
        if n>=2:
            catalog["pair:"+t] = t+"对子"
        if n>=3:
            catalog["triplet:"+t] = t+"暗刻"
    for suit in ("万","饼","条"):
        values = [n for n in range(1,10) if counts[f"{n}{suit}"]]
        for a in values:
            if a<=7 and all(counts[f"{n}{suit}"] for n in range(a,a+3)):
                tiles = [f"{n}{suit}" for n in range(a,a+3)]
                catalog["sequence:"+"+".join(tiles)] = "、".join(tiles)+"顺子"
            for b in values:
                waits = pair_completions((a,b)) if a<b else set()
                if not waits:
                    continue
                label = "坎张" if b-a==2 else "边张" if (a,b) in ((1,2),(8,9)) else "两面"
                catalog[f"taatsu:{a}{suit}+{b}{suit}"] = f"{a}{suit}、{b}{suit}{label}搭，等"+"、".join(f"{n}{suit}" for n in sorted(waits))
    return catalog


def validate_strategy(answer, session):
    if answer.get("strategy_version") != VERSION:
        raise DecisionError("需要strategy-v2结构化策略；旧自由文字不能绕过约束")
    strategy = answer.get("reasoning")
    keys = {"intent","priorities","focus_seats","accept_costs","change_triggers","shape_refs"}
    if (not isinstance(strategy,dict) or set(strategy) != keys
            or not isinstance(strategy.get("intent"),str) or strategy["intent"] not in INTENTS):
        raise DecisionError("策略判断字段或意图不合法")
    priorities = _list(strategy["priorities"], set(PRIORITIES), "策略侧重",maximum=len(PRIORITIES),minimum=1)
    focus = _seats(strategy["focus_seats"],session.obs,"重点防范")
    if (strategy["intent"] in DEFENSIVE_INTENTS or "defense" in priorities) and not focus:
        raise DecisionError("防守判断必须指明关注哪一家")
    _list(strategy["change_triggers"],set(TRIGGERS),"改判条件",maximum=3,minimum=1)
    accepted = _list(strategy["accept_costs"],set(COSTS),"接受代价",maximum=len(COSTS))
    branch = branch_for(session,answer.get("action_id"),answer.get("next_discard"))
    catalog = shape_catalog(session.obs,branch)
    # Cardinality is not a mahjong rule: every distinct, actually present local
    # shape may be cited. Overlap is explicitly labelled, never summed as sets.
    refs = strategy["shape_refs"]
    if isinstance(refs,list) and all(isinstance(r,str) for r in refs):
        invalid = [r for r in refs if r not in catalog]
        if invalid:
            raise DecisionError("保留牌形引用不属于所选动作处理后的手牌："+"、".join(invalid)+
                                "；只可引用该分支shape_catalog，不可引用弃牌前或其他候选的形状")
    _list(refs,set(catalog),"保留牌形引用",maximum=len(catalog))
    costs = required_costs(session,answer,branch)
    if set(accepted) != set(costs):
        raise DecisionError("接受代价须与所选分支事实一致："+(",".join(costs) if costs else "无额外硬性代价，填空列表"))
    note = answer.get("decision_note")
    if not isinstance(note,dict):
        raise DecisionError("缺少局势判断笔记，未执行")
    raw = note.get("opponents")
    if not isinstance(raw,list) or len(raw) != 3:
        raise DecisionError("局势笔记必须逐家分析三名对手")
    opponents = [validate_opponent(p,session.obs,session.evidence) for p in raw]
    if len({p["seat"] for p in opponents}) != 3:
        raise DecisionError("对手笔记座位错误")
    alt = branch_for(session,note.get("alternative_action_id"),note.get("alternative_next_discard"))
    # Distinct concrete branches, not just root action IDs.
    if len(session.obs["legal_actions"])>1 and (
            note["alternative_action_id"],note.get("alternative_next_discard")) == (
            answer["action_id"],answer.get("next_discard")):
        raise DecisionError("必须比较另一项合法备选")
    return copy.deepcopy(strategy), opponents, branch, alt


def render_strategy(answer, session):
    strategy, opponents, branch, alternative = validate_strategy(answer,session)
    own = session.obs["seat"]
    relative = lambda s: {1:"下家",2:"对家",3:"上家"}[(s-own)%4]
    text = ["这手我倾向"+INTENTS[strategy["intent"]]+"；"+"，".join(PRIORITIES[p] for p in strategy["priorities"])+"。"]
    costs = strategy["accept_costs"]
    if costs:
        text.append("这是主动取舍："+"；".join(COSTS[c] for c in costs)+"。")
    else:
        text.append("所选分支没有需要额外承认的牌效、留花占位或互锁代价；这不代表没有放炮风险。")
    shapes = shape_catalog(session.obs,branch)
    if strategy["shape_refs"]:
        text.append("本动作处理后、未知摸牌前，我希望利用的局部形状是："+
                    "；".join(shapes[k] for k in strategy["shape_refs"])+"。这些形状可能共享牌，不能当成独立组数相加。")
    for opportunity in session.payload["flower_opportunities"]:
        for win in opportunity["immediate_gangkai"]:
            card = next(c for c in session.contract["decision_cards"] if c["action_id"]==session.handles[opportunity["action_id"]])
            text.append("条件机会：换出"+card["receipt"]["action"]["tiles"][0]+"，若补到"+win["tile"]+"可杠开；"+
                        "、".join(relative(int(s))+f"付{amount}" for s,amount in win["payments"].items())+
                        f"。公开未见上界{win['unseen_upper_bound']}，不是墙内活张或命中概率。")
    for p in opponents:
        if p["seat"] in strategy["focus_seats"]:
            text.append(relative(p["seat"])+"："+render_opponent(p)["hypothesis"]+"，不能当作已知听口。")
    # Always expose all public liabilities; the model may still choose to attack.
    for c in opponent_constraints(session.obs):
        name = relative(c["seat"])
        if c["publicly_cannot_ron"]:
            text.append(name+"已互锁，不能接炮，仍可能自摸。")
        else:
            text.append(name+f"若合法接炮，仅当前公开计分及未知暗杠最低值已含至少{2+c['qualifying_hua_floor']}；"
                        "未公开风刻和牌型另计，不代表已听或一定能胡。")
    text.append("对照方案："+checked_summary(alternative["receipt"]))
    text.append("；".join(TRIGGERS[t] for t in strategy["change_triggers"])+"。")
    note = {"version":VERSION,"opponents":[render_opponent(p) for p in opponents],
            "plan":INTENTS[strategy["intent"]]+"；"+"，".join(PRIORITIES[p] for p in strategy["priorities"]),
            "alternative_action_id":answer["decision_note"]["alternative_action_id"],
            "alternative_reason":"对照而非代码推荐："+checked_summary(alternative["receipt"]),
            "change_if":"；".join(TRIGGERS[t] for t in strategy["change_triggers"])}
    if answer["decision_note"].get("alternative_next_discard") is not None:
        note["alternative_next_discard"] = answer["decision_note"]["alternative_next_discard"]
    return note, "\n\n".join(text)


def render_review(answer, review):
    """The model selects historical comparisons, never writes hindsight facts."""
    if not isinstance(answer,dict) or answer.get("strategy_version") != VERSION or set(answer)!={"strategy_version","review_points"}:
        raise DecisionError("历史复盘需要结构化review_points，不展示旧自由文字")
    points = answer["review_points"]
    if not isinstance(points,list) or not 1<=len(points)<=3:
        raise DecisionError("历史复盘须选择1至3个实际决策点")
    decisions = {d["step"]:d for d in review["decisions"]}
    seen = set(); paragraphs = []
    from .base import action_label
    for point in points:
        keys = {"step","alternative_action_id","alternative_next_discard","intent","focus_seats"}
        if not isinstance(point,dict) or set(point)!=keys or type(point["step"]) is not int or point["step"] not in decisions or point["step"] in seen:
            raise DecisionError("历史复盘引用不存在或重复的决策")
        seen.add(point["step"]); d=decisions[point["step"]]
        if not isinstance(point["intent"],str) or point["intent"] not in INTENTS:
            raise DecisionError("历史复盘意图不合法")
        focus=_seats(point["focus_seats"],{"seat":review["seat"],"players":d["public_then"]},"历史关注对手")
        if point["intent"] in DEFENSIVE_INTENTS and not focus:
            raise DecisionError("历史防守对照必须说明关注哪一家")
        candidate = next((c for c in d["legal_candidates"] if c["action_id"]==point["alternative_action_id"]),None)
        if candidate is None:
            raise DecisionError("历史复盘备选不是当时的合法动作")
        text = f"第{point['step']}手：当时实际"+action_label(d["actual"])+"；模型希望对照"+action_label(candidate)+"。"
        metrics = candidate if candidate["kind"] == "discard" else None
        if candidate["kind"] in ("chi","peng"):
            metrics = next((b for b in candidate.get("after_discards",[]) if b["tile"]==point["alternative_next_discard"]),None)
            if metrics is None:
                raise DecisionError("历史吃碰对照缺少合法后续弃牌")
            text += "随后打"+metrics["tile"]+"。"
        elif point["alternative_next_discard"] is not None:
            raise DecisionError("非吃碰历史备选不能附加弃牌")
        if metrics:
            text += f"该对照分支的结构向听{metrics['shanten']}，公开未见改善张{metrics['unseen_improving']}；留花仍影响合法胡牌。"
        text += "模型在这里更倾向"+INTENTS[point["intent"]]+"。"
        if point["focus_seats"]:
            relative = {1:"下家",2:"对家",3:"上家"}
            text += "特别关注"+"、".join(relative[(s-review["seat"])%4] for s in point["focus_seats"])+"；具体暗牌和听口未知。"
        paragraphs.append(text+"这不是最优结论，也不因实际输赢判错；未见不等于牌墙活张。")
    return {"summary":"本局选取"+str(len(points))+"个当时决策作对照，不用局末暗牌倒推",
            "explanation":"\n\n".join(paragraphs),"action_id":None,"verification_version":VERSION,
            "verification_note":"历史动作与候选由代码核对；模型只选择对照点和策略意图，不证明哪手最优。"}
