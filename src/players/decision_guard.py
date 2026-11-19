"""Checkable decision receipts, not a proof of strategic optimality.

Receipts are recomputed from the allow-listed observation. Free prose gets a
limited contradiction screen, NOT a general semantic verifier. Never silently
replace a model action with a heuristic action or a tile mentioned in prose.
"""
from collections import Counter
import re

from ..core.hand_analyzer import get_waiting_tiles
from ..core.scoring import known_hua, score_hand
from ..core.tiles import Meld, parse_tile, tile_sort_key
from .analysis import analyze_actions
from .base import DecisionError, action_label
from .strategy_facts import pair_completions
from .tactical_facts import wait_shapes


CONTRACT = """
必须遵守decision_contract_v1。返回JSON中的action_id须合法，另有：
action: {"kind":"所选动作kind","tiles":["所选动作牌名"]}，须与action_id完全一致。
fact_check: 逐字段原样填写所选decision_cards条目的receipt（不是baseline或其他候选）。
吃/碰时另填next_discard，必须来自该卡after_discards，fact_check取该弃牌分支的receipt。
若该分支的requires_tradeoff为true，另填tradeoff:
{"category":"defense/hand_value/shape_improvement/flower_timing之一",
 "evidence_ids":["public_evidence中实际有关的id"],"reason":"说明为什么值得牺牲向听或进张"}。
防守取舍至少引用一条对手公开证据。引用存在不代表策略正确，不得伪造胜率。
reason只解释本动作的取舍。不得说选择另一张，不得把其他候选或摸前的进张当本动作结果。
不同向听的进张不能直接比大小。留花时结构向听不是合法听牌，未清花不能胡。
手牌结构、已换花分与接炮条件以receipt为准；不要把花换出说成失去花分。
未见张不等于墙内活张，自己河里打过不等于安全。未知暗杠可以提出假设，但不得把猜测的牌名当作已知事实。
不要在正文重新编造具体分数、向听、待牌或副本数，必要事实由代码单独展示。
"""


def _melds(obs):
    return [Meld(m["type"], [parse_tile(t) for t in m["tiles"]])
            for m in obs["players"][obs["seat"]]["melds"]]


def _qualification(hand, melds, flowers):
    known = known_hua(melds=melds, konged_flowers=flowers, flower_kong_groups=[[t] for t in flowers])
    # known_hua intentionally omits concealed wind triplets for opponents.
    # Here these are OWN explicitly observed tiles, so they can be counted.
    winds = sum(hand.count(parse_tile(name)) == 3 for name in ("南风", "西风", "北风"))
    return {**known, "concealed_wind_triplets": winds, "total": known["total"]+winds}


def _after(hand, melds, flowers, obs, shanten, unseen, *, claim=False):
    base = 13-3*len(melds)
    occupied = sum(t.is_flower for t in hand)
    own = Counter(hand)
    own.update(t for m in melds for t in m.tiles)
    waits = []
    if len(hand) == base and not occupied:
        waits = [t for t in sorted(get_waiting_tiles(hand, len(melds)), key=tile_sort_key) if own[t] < 4]
    ron = []
    if not obs["self"].get("locked_with") and (claim or not obs["self"].get("ron_blocked")):
        for tile in waits:
            try:
                score_hand(hand+[tile], my_melds=melds, konged_flowers=flowers,
                           flower_kong_groups=[[t] for t in flowers], win_method="dianpao")
                ron.append(str(tile))
            except ValueError:
                pass
    return {"structural_shanten": shanten, "unseen_improving": unseen,
            "held_flower_count": occupied, "ready": bool(waits),
            "waiting_tiles": [str(t) for t in waits], "eligible_ron_tiles": ron,
            "wait_shapes": [w for w in wait_shapes(hand, len(melds)) if w["tile"] in {str(t) for t in waits}],
            "locked_with":list(obs["self"].get("locked_with",[])),
            "conditional_zimo_payer_multipliers": {
                str(p["seat"]): 3 if p["seat"] in obs["self"].get("locked_with", []) else 1
                for p in obs["players"] if p["seat"] != obs["seat"]},
            "qualifying_hua": _qualification(hand, melds, flowers)["total"]}


def decision_contract(obs, analysis=None):
    analysis = analysis or analyze_actions(obs)
    hand = [parse_tile(t) for t in obs["self"]["hand"]]
    melds = _melds(obs)
    flowers = [parse_tile(t) for t in obs["players"][obs["seat"]]["flowers"]]
    by_id = {f["action_id"]: f for f in analysis["candidates"]}
    own = {"hand_counts": dict(sorted(Counter(obs["self"]["hand"]).items())),
           "qualifying_hua": _qualification(hand, melds, flowers),
           "held_flowers_are_not_structure": True,
           "ron_blocked": bool(obs["self"].get("ron_blocked")),
           "locked_with": list(obs["self"].get("locked_with", []))}
    counts = Counter(hand)
    own["local_shapes"] = {"pairs": [str(t) for t in sorted(counts, key=tile_sort_key) if not t.is_flower and counts[t] >= 2],
        "triplets": [str(t) for t in sorted(counts, key=tile_sort_key) if not t.is_flower and counts[t] >= 3],
        "taatsu": [], "scope": "局部形状可能共享同一张牌，不能视为可同时成立的整手分解"}
    for suit in ("万", "饼", "条"):
        values = sorted(int(t.value) for t in counts if t.suit == suit)
        for i,a in enumerate(values):
            for b in values[i+1:]:
                waits = pair_completions((a,b))
                if waits:
                    own["local_shapes"]["taatsu"].append({"tiles": [f"{a}{suit}", f"{b}{suit}"],
                        "completions": [f"{v}{suit}" for v in sorted(waits)]})
    evidence = {"self.hand": {"seat": obs["seat"], "counts": own["hand_counts"]}}
    for p in obs["players"]:
        prefix = f"seat.{p['seat']}"
        for field in ("river", "melds", "flowers", "known_qualifying_hua", "locked_with"):
            if p.get(field):
                evidence[prefix+"."+field] = {"seat": p["seat"], "value": p[field]}
    cards = []
    for action in obs["legal_actions"]:
        fact = by_id[action["id"]]
        echo = {"kind": action["kind"], "tiles": list(action["tiles"])}
        receipt = {"action": echo, "own_hand_counts": own["hand_counts"],
                   "own_meld_tiles": [[str(t) for t in m.tiles] for m in melds],
                   "current_qualifying_hua": own["qualifying_hua"]["total"], "after": None}
        if action["kind"] in ("chi", "peng", "ming_gang"):
            source = obs["pending"]["source"]
            receipt.update(source=source, source_relative={1: "下家", 2: "对家", 3: "上家"}[(source-obs["seat"]) % 4],
                           call_count_after=fact["call_count_after"], creates_lock=fact["creates_lock"])
        card = {"action_id": action["id"], "label": action_label(action), "receipt": receipt,
                "requires_tradeoff": False}
        if action["kind"] == "discard":
            after = hand.copy()
            after.remove(parse_tile(action["tiles"][0]))
            receipt["after"] = _after(after, melds, flowers, obs, fact["shanten"], fact["unseen_improving"])
        elif action["kind"] in ("chi", "peng"):
            tile = parse_tile(obs["pending"]["tile"])
            group = [parse_tile(t) for t in action["tiles"]] if action["kind"] == "chi" else [tile]*3
            needed = group.copy()
            needed.remove(tile)
            after = hand.copy()
            for t in needed:
                after.remove(t)
            new_melds = melds+[Meld(action["kind"], group)]
            # The projected third mouth takes effect BEFORE evaluating ron
            # eligibility, not only after the real engine commits the claim.
            claim_obs=obs
            if fact["creates_lock"]:
                claim_obs={**obs,"self":{**obs["self"],"locked_with":sorted(set(
                    obs["self"].get("locked_with",[]))|{obs["pending"]["source"]})}}
            branches = []
            for f in fact["after_discards"]:
                rest = after.copy()
                rest.remove(parse_tile(f["tile"]))
                branch_receipt = {**receipt, "next_discard": f["tile"],
                    "after": _after(rest, new_melds, flowers, claim_obs, f["shanten"], f["unseen_improving"], claim=True)}
                branches.append({"tile": f["tile"], "receipt": branch_receipt,
                                 "requires_tradeoff": False})
            card["after_discards"] = branches
            # Do not expose an unfilled top-level receipt as another apparently
            # selectable answer. Only a concrete discard branch is checkable.
            card["action"] = echo
            del card["receipt"]
        elif action["kind"] == "pass":
            from ..simulation.state import RULES_VERSION
            receipt["passing_ron_blocks_all_ron"] = any(a["kind"] == "ron" for a in obs["legal_actions"])
            receipt["passing_peng_blocks_tile"] = obs["pending"]["tile"] if (
                obs["rules_version"] == RULES_VERSION and any(a["kind"] == "peng" for a in obs["legal_actions"])) else None
        cards.append(card)
    # Require explicit rationale for structural regression / fewer outs at the
    # same shanten. This is NOT a ban: defense/value/improvement may justify it.
    discards = [c for c in cards if c.get("receipt", {}).get("after") is not None]
    branches = [b for c in cards for b in c.get("after_discards", [])]
    for group in (discards, branches):
        if not group:
            continue
        best = min((c["receipt"]["after"] for c in group),
                   key=lambda f: (f["structural_shanten"], -f["unseen_improving"]))
        for card in group:
            after = card["receipt"]["after"]
            card["requires_tradeoff"] = (after["structural_shanten"], -after["unseen_improving"]) > (
                best["structural_shanten"], -best["unseen_improving"])
    return {"version": "decision_contract_v1", "self_facts": own, "decision_cards": cards,
            "public_evidence": evidence,
            "scope": "receipt精确校核；策略理由仅有限矛盾筛查，不证明最优、不保证所有自然语言事实正确"}


def _normalized(text):
    return text.replace("筒", "饼").replace("餅", "饼").replace("條", "条")


TILE = r"(?:[1-9][万饼条]|[南西北东]风|中|发|白|春|夏|秋|冬|梅|兰|竹|菊)"


def check_prose(text, action, receipt):
    text = _normalized(text)
    if len(text) > 1000:
        raise DecisionError("决策解释过长，未执行")
    # Explicit final/recommended commands, not discussion of alternatives.
    commands = re.findall(r"(?:选择|决定|建议|最终)(?:先|直接)?(?:打|切|弃|丢)(?:出|掉|一张)?("+TILE+r")", text)
    if action["kind"] == "discard" and any(t != action["tiles"][0] for t in commands):
        raise DecisionError("决策解释与实际弃牌冲突，未执行")
    first = re.match(r"(?:先)?(?:打|切|弃)(?:出|掉|一张)?("+TILE+r")", text)
    if first and (action["kind"] != "discard" or first[1] != action["tiles"][0]):
        raise DecisionError("决策解释开头与实际动作冲突，未执行")
    if "source_relative" in receipt:
        sources = re.findall(r"(?:吃碰|吃|碰|明杠)(?:为|来自|取自)(上家|对家|下家)", text)
        if any(source != receipt["source_relative"] for source in sources):
            raise DecisionError("决策解释的取牌来源不符，未执行")
    after = receipt.get("after")
    if after and not after["ready"] and re.search(r"(?:仍|继续|依旧)(?:然|可|能|保持|维持|是)*听牌|(?:仍保持|仍维持|保持|维持)[0零]向听", text):
        raise DecisionError("决策解释错误宣称保持听牌，未执行")
    first_sentence = re.split(r"[。；;\n]", text)[0]
    if after:
        numbers = re.findall(r"(?:保留|只剩|剩下)(\d+)(?:张|种|个)(?:公开未见|有效|改善)?进张", first_sentence)
        numbers += re.findall(r"(?:未见进张|改善张|进张数)(?:约|为|共|剩)?(\d+)", first_sentence)
        if any(int(n) != after["unseen_improving"] for n in numbers):
            raise DecisionError("决策解释的本次进张数量不符，未执行")
    if receipt["current_qualifying_hua"] > 0 and re.search(r"(?:自己|自身|我|唯一)(?:当前|目前|现在)?(?:无|没有|缺)(?:资格花|花分)", text):
        raise DecisionError("决策解释遗漏已有资格花，未执行")
    if action["kind"] == "flower_kong" and re.search(r"换(?:出|掉).{0,12}(?:失去|损失|丢失)(?:花分|资格花)", text):
        raise DecisionError("单张花换出不会丢失花分，未执行")
    # Named own pairs/triplets; quoted opponents and hypothetical future shapes
    # are deliberately not parsed as current own hand assertions.
    for match in re.finditer(r"("+TILE+r")(?:是|为|的)?(对子|暗刻|刻子)", text):
        tile, label = match.groups()
        count = receipt["own_hand_counts"].get(tile, 0)
        if label == "刻子":
            count += sum(group.count(tile) for group in receipt["own_meld_tiles"])
        potential = text[match.end():].startswith(("潜力", "候选", "可能", "机会", "的可能", "的潜力", "雏形"))
        triplet_wait = label == "刻子" and text[match.end():].startswith("待牌")
        # A triplet wait is a pair awaiting its third tile, not an existing set.
        # Keep rejecting one-copy claims and unqualified "已有刻子" assertions.
        required = 2 if triplet_wait else 1 if potential else 2 if label == "对子" else 3
        if count < required and not re.search(r"(?:对手|上家|下家|对家|如果|摸到|假如)", text):
            raise DecisionError("决策解释的手牌副本数不符，未执行")


def validate_decision(answer, obs, contract, *, prose_fields=("reason",)):
    if not isinstance(answer, dict):
        raise DecisionError("模型未返回决策对象，未执行")
    card = next((c for c in contract["decision_cards"] if c["action_id"] == answer.get("action_id")), None)
    if card is None:
        raise DecisionError("模型返回非法或过期动作，未执行")
    action = card["action"] if card.get("after_discards") else card["receipt"]["action"]
    echo = answer.get("action")
    if isinstance(echo, str) and isinstance(answer.get("tiles"), list):
        # Lossless wire-format compatibility only. Both fields still have to
        # match the engine action; never infer the action from prose or receipt.
        echo = {"kind": echo, "tiles": answer["tiles"]}
    if echo != action or ("tiles" in answer and answer["tiles"] != action["tiles"]):
        raise DecisionError("动作编号与牌名／动作类型不一致，未执行")
    branch = card
    if card.get("after_discards"):
        branch = next((b for b in card["after_discards"] if b["tile"] == answer.get("next_discard")), None)
        if branch is None:
            raise DecisionError("吃碰未指定合法的后续弃牌计划，未执行")
    # JSON equality would accept True==1; canonical encoding checks types too.
    import json
    encode = lambda value: json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    if encode(answer.get("fact_check")) != encode(branch["receipt"]):
        raise DecisionError("决策回执与代码事实不符，未执行")
    if branch["requires_tradeoff"] or answer.get("tradeoff") is not None:
        tradeoff = answer.get("tradeoff")
        if not isinstance(tradeoff, dict) or tradeoff.get("category") not in (
                "defense", "hand_value", "shape_improvement", "flower_timing"):
            raise DecisionError("牺牲牌效未说明取舍类别，未执行")
        evidence = tradeoff.get("evidence_ids")
        if (not isinstance(evidence, list) or not evidence or any(
                not isinstance(k, str) or k not in contract["public_evidence"] for k in evidence)
                or not isinstance(tradeoff.get("reason"), str) or len(tradeoff["reason"].strip()) < 8):
            raise DecisionError("牺牲牌效缺少可核对的依据，未执行")
        if tradeoff["category"] == "defense" and not any(
                contract["public_evidence"][k]["seat"] != obs["seat"] for k in evidence):
            raise DecisionError("防守取舍未引用对手公开证据，未执行")
        check_prose(tradeoff["reason"], action, branch["receipt"])
    for field in prose_fields:
        if not isinstance(answer.get(field), str):
            raise DecisionError("决策解释格式错误，未执行")
        check_prose(answer[field], action, branch["receipt"])
    return branch["receipt"]


def checked_summary(receipt):
    action = receipt["action"]
    text = action_label(action).strip()+"。"
    if receipt.get("next_discard"):
        text += "随后打"+receipt["next_discard"]+"。"
    if "source_relative" in receipt:
        text += f"取自{receipt['source_relative']}，向其第{receipt['call_count_after']}口。"
    after = receipt.get("after")
    if after:
        if after["ready"]:
            text += "听"+"／".join(after["waiting_tiles"])+"。"
            for w in after.get("wait_shapes",[]):
                text += w["tile"]+"可按"+"／".join(w["forms"])+"成牌。"
            text += "可接炮的待牌："+"／".join(after["eligible_ron_tiles"])+"。" if after["eligible_ron_tiles"] else "当前条件暂不能接炮。"
        else:
            text += f"结构{after['structural_shanten']}向听，尚未合法听牌。"
            if after["held_flower_count"]:
                text += "手里仍有留花，须处理后才能胡牌。"
        text += f"公开未见改善张{after['unseen_improving']}，不等于墙内活张。"
    elif action['kind'] in ('win', 'ron'):
        text += f"当前已可合法胡牌；可核对资格花{receipt['current_qualifying_hua']}，最终收入按本次胡法结算。"
    elif action['kind'] in ('flower_kong', 'an_gang', 'ming_gang', 'add_gang'):
        text += f"当前可核对资格花{receipt['current_qualifying_hua']}；补牌未知，不预报补牌后的听口。"
    else:
        text += f"当前可核对资格花{receipt['current_qualifying_hua']}；本动作不预报下一次摸牌结果。"
    return text
