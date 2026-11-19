"""EV 军师教练：以 LLMCoach 同款 explain() 契约注入桌面牌桌的常驻军师插槽。

数学核心实时计算，LLM 零参与；输出字段适配牌桌页 table.js 的渲染
（verification_version 必须为 "strategy-v2"，否则页面按旧版隐藏）。
"""
from .ev import opponent_panel, rank_candidates
from .receipts import save_receipt
from .reading import river_facts
from .dynamic_reading import read_table, MODEL as READING_MODEL
from .call_decision import evaluate_calls, call_rank
from .ev_bot import build_state_from_observation, self_kong_advice

VERSION = "strategy-v2"


def _fmt_pct(value: float) -> str:
    return f"{value * 100:.0f}%"


class EVCoach:
    """免费、确定性（同 seed）、每次决策自动刷新的常驻军师。"""

    def explain(self, payload: dict) -> dict:
        if payload.get("observation") is not None:
            observation = payload["observation"]
            result = self._live(observation)
            brief = result.setdefault("brief", {
                "action": result["summary"].split("（")[0].split("｜")[0],
                "reason": "",
            })
            opponents = []
            read_state = build_state_from_observation(observation)
            ordered_reads = read_table(read_state)
            seat = observation["seat"]
            for offset, name in ((1, "下家"), (2, "对家"), (3, "上家")):
                player = next((p for p in observation.get("players", [])
                               if p["seat"] == (seat + offset) % 4), {})
                counts = {suit: sum(suit in tile for tile in player.get("river", []))
                          for suit in ("万", "饼", "条")}
                suit = max(counts, key=counts.get)
                text = "无法推断"
                if len(player.get("melds", [])) >= 3:
                    text = "已副露三组，留意成牌" if len(player["melds"]) == 3 else "已副露四组，留意单吊"
                elif counts[suit] >= 3:
                    text = f"已弃{suit}{counts[suit]}张，可能少留{suit}"
                key = {1:"right", 2:"opposite", 3:"left"}[offset]
                if observation.get("events"):
                    text = ordered_reads[key].summary
                    if len(player.get("melds", [])) >= 3:
                        text = "已副露三组，留意成牌" if len(player["melds"]) == 3 else "已副露四组，留意单吊"
                opponents.append({"seat": name, "text": text})
            brief["opponents"] = opponents
            result["reading"] = {"model": READING_MODEL,
                                 "events_used": len(read_state.public_events),
                                 "opponents": {seat: {"summary": read.summary, "phase": read.phase,
                                                      "evidence": list(read.evidence)}
                                               for seat, read in ordered_reads.items()}}
            return result
        return self._review(payload)

    def _call_advice(self, observation: dict) -> dict:
        """响应窗口：吃/碰/明杠 vs 过 的建议（判据与 bot 同源 analyze_actions）。"""
        note_footer = ("判据=结构收益（向听/进张对比），与机器人同源；"
                       "接牌后的弃牌复用动态读牌；补牌收益与整局搜索尚未纳入。")
        analysis = evaluate_calls(observation, samples=16, seed=0)
        baseline = analysis["baseline"]
        base_rank = (baseline["shanten"], -baseline["unseen_improving"])
        lines = [f"当前：{baseline['shanten']}向听，进张活张{baseline['unseen_improving']}"]
        best = None
        for cand in analysis["candidates"]:
            if cand["kind"] not in ("chi", "peng", "ming_gang"):
                continue
            rank = (cand["shanten"], -cand["unseen_improving"])
            gain = rank < base_rank
            lock = bool(cand.get("creates_lock"))
            tag = "✓收益" if gain else "✗不划算"
            lines.append(
                f"{cand['kind']}：{baseline['shanten']}→{cand['shanten']}向听，"
                f"活张{baseline['unseen_improving']}→{cand['unseen_improving']}"
                + (f"，最优弃张{cand['best_discard']}" if cand.get("best_discard") else "")
                + (f"｜⚠第三口互锁（只能自摸/杠开，赔付×3）" if lock else ""))
            if gain and not (cand.get("discards_claimed_kind") and cand["shanten"] >= baseline["shanten"]) \
                    and not (lock and cand["shanten"] >= baseline["shanten"]):
                key = call_rank(cand)
                if best is None or key < best[0]:
                    best = (key, cand)
        if best is None:
            summary = f"建议：过（没有严格收益的叫牌，{baseline['shanten']}向听保持摸牌灵活性）"
        else:
            cand = best[1]
            zh = {"chi": "吃", "peng": "碰", "ming_gang": "明杠"}[cand["kind"]]
            summary = (f"建议：{zh}（{baseline['shanten']}→{cand['shanten']}向听，"
                       f"活张{baseline['unseen_improving']}→{cand['unseen_improving']}"
                       + ("；注意这是第三口，将互锁" if cand.get("creates_lock") else "") + "）")
        return {"verification_version": VERSION, "summary": summary,
                "explanation": "\n".join(lines),
                "verification_note": note_footer}

    def _live(self, observation: dict) -> dict:
        note_footer = ("由数学核心实时计算（闭式公式+先验采样N=64），LLM 不参与决策；"
                       "概率为公开信息加权采样，未经实战校准；吃牌机会只用于相近牌效候选决胜。")
        actions = observation.get("legal_actions") or []
        if any(a["kind"] == "win" for a in actions):
            return {"verification_version": VERSION, "summary": "建议胡牌：当前可自摸/杠开",
                    "explanation": "已有合法胡牌，不再建议弃牌或继续开杠。", "verification_note": note_footer}
        if any(a["kind"] == "ron" for a in actions) and not observation["self"].get("ron_blocked"):
            return {"verification_version": VERSION, "summary": "建议胡牌：当前可接炮",
                    "explanation": "接炮资格由裁判校验，不用弃牌分析覆盖现成胡牌。", "verification_note": note_footer}
        kong = self_kong_advice(observation)
        if kong:
            action, reason = kong
            name = "加杠" if action["kind"] == "add_gang" else "暗杠"
            return {"verification_version": VERSION, "summary": f"建议{name}{action['tiles'][0]}",
                    "explanation": reason, "verification_note": note_footer}
        if (observation.get("stage") == "responses"
                and any(a["kind"] in ("chi", "peng", "ming_gang") for a in actions)
                and not any(a["kind"] == "discard" for a in actions)):
            return self._call_advice(observation)
        if observation["self"].get("held_flower_count", 0):
            return {
                "verification_version": VERSION,
                "summary": "先换花：花占位状态，换完再算 EV",
                "explanation": ("手牌含未换花（占位）。每换一张立即补牌并把花分落袋；"
                                "听牌后留花搏杠开是进阶打法。\n"
                                "EV 层暂只支持换花后的手牌（占位语义属 P2 重做）。"),
                "verification_note": note_footer,
            }
        try:
            state = build_state_from_observation(observation)
            ranked = rank_candidates(state, samples=64, seed=0)
            panel = opponent_panel(state, samples=64, seed=0)
        except ValueError as exc:
            return {
                "verification_version": VERSION,
                "summary": f"EV 暂不可用：{exc}",
                "explanation": "该局面 EV 层暂不支持，可参考牌桌页的代码牌效备选。",
                "verification_note": note_footer,
            }
        top = ranked[0]
        top_is_1ply = any("1-ply" in l for l in top.labels)
        # 近似平局：同向听·同EV·后劲差<2 → 先打哪张都行（小数点决胜不是理由）
        peers = [c for c in ranked[1:5]
                 if c.stand_shanten == top.stand_shanten
                 and any("1-ply" in l for l in c.labels) == top_is_1ply
                 and not any("咨询" in l for l in c.labels)
                 and abs(c.p_next_progress - top.p_next_progress) < 0.1
                 and abs(c.p_call_progress - top.p_call_progress) < 0.1
                 and abs(c.p_feed_chi - top.p_feed_chi) < 0.1
                 and abs(c.ev - top.ev) < 0.05
                 and abs(c.exp_neff_1ply - top.exp_neff_1ply) < 2.0]
        lines = ["本巡建议："]
        for cand in ranked[:3]:
            consult = any("咨询" in label for label in cand.labels)
            if consult:
                structure = f"下摸能进步的概率{_fmt_pct(cand.exp_neff_1ply)}"
            elif any("1-ply" in label for label in cand.labels):
                structure = f"打后还差{cand.stand_shanten}步听牌·后劲{cand.exp_neff_1ply:.1f}"
                if any("孤字" in label for label in cand.labels):
                    structure += "（教学：孤字先走）"
            elif cand.stand_shanten > top.stand_shanten:
                # 退向听候选的静态进张是跨向听虚数，不可与上一行同台比较
                structure = f"打后退到{cand.stand_shanten}步听牌（更慢，不推荐）"
            else:
                structure = f"打后还差{cand.stand_shanten}步听牌·能接{cand.exp_neff_1ply:.0f}张"
            lines.append(
                f"打{cand.tile}：下摸胡率{_fmt_pct(cand.p_win_next)}"
                f"（胡了约{cand.v_win:.0f}分）－ 点炮风险{_fmt_pct(cand.p_point)}"
                f"（点了赔{cand.v_deal:.0f}分）｜{structure}｜下家可吃机会{_fmt_pct(cand.p_feed_chi)}（估计）")
        lines.append("")
        lines.append("三家推测：对手已听牌的可能是采样估计，不保证随弃牌增多越来越准。")
        facts = river_facts(state)
        ordered_reads = read_table(state)
        for seat_key, zh in (("left", "上家"), ("opposite", "对家"), ("right", "下家")):
            if state.public_events:
                lines.append(f"  {zh}【动态读牌】：{ordered_reads[seat_key].summary}")
                for item in ordered_reads[seat_key].evidence:
                    lines.append(f"    依据：{item}")
            river = state.discards.get(seat_key, [])
            melds = state.melds.get(seat_key, [])
            recent = "、".join(str(t) for t in river[-6:]) or "尚无弃牌"
            groups = "；".join(f"{m.type} {'/'.join(str(t) for t in m.tiles)}" for m in melds) or "尚未副露"
            lines.append(f"  {zh}【事实】：已弃{len(river)}张，最近{recent}；{groups}。")
            dumped = [(suit, count) for suit, count in facts.get(seat_key, {}).items()
                      if suit in ("万", "饼", "条") and count >= 3]
            hint = "；".join(f"弃{suit}{count}张，可能较少保留该门，但后续摸牌会改变需求" for suit, count in dumped)
            lines.append(f"  {zh}【推测】：" + (hint or "弃牌证据不足，无法可靠判断具体需求")
                         + f"；听牌采样估计{_fmt_pct(panel[seat_key]['tenpai_prior'])}，采样为零也不代表安全。")
            if len(melds) >= 3:
                lines.append(f"  {zh}【应对】：已副露{len(melds)}组，暗手较短；需同时防点炮和继续送碰杠，不能据此断言已听牌。")
        lines.append(f"控下家：打{top.tile}的下家可吃机会估计{_fmt_pct(top.p_feed_chi)}，"
                     f"下家吃碰后能降向听的样本占比{_fmt_pct(top.p_next_progress)}。"
                     "相近牌效时优先少喂吃；可吃不代表一定吃、吃后一定进步。自己能快听、快胡时仍需权衡。")
        lines.append("——名词：还差N步听牌=向听｜能接N张=进张活张｜"
                     "后劲=同分候选比下一摸潜力｜听牌可能=按公开信息的估计")
        labels = "；".join(top.labels[:3])
        try:
            oid = observation.get("observation_id", "table:rev0:0")
            game_id, stage = oid.split(":")[0], oid.split(":")[1]
            revision = "".join(ch for ch in stage if ch.isdigit()) or 0
            save_receipt(game_id, int(revision), ranked)
        except (OSError, ValueError, IndexError):
            pass   # 落盘失败不影响建议
        return {
            "verification_version": VERSION,
            "summary": (f"建议打{top.tile}"
                        + ((f"｜下摸胡率{_fmt_pct(top.p_win_next)}（胡了约{top.v_win:.0f}分）"
                           + (f"｜点炮风险{_fmt_pct(top.p_point)}（点了赔{top.v_deal:.0f}分）"
                              if top.p_point else ""))
                           if (top.p_win_next or top.p_point)
                           else "（攻防暂无信号，按保搭子排序）")
                        + ((f"｜与{'/'.join(str(c.tile) for c in peers)}"
                            "基本等价，先打哪张都行") if peers else "")),
            "brief": {"action": f"建议打{top.tile}",
                      "reason": "同等牌效时，少给对手送吃碰。" if "决胜:少送吃碰" in top.labels else
                                "保持听牌。" if top.stand_shanten == 0 else
                                "孤字先走，保留搭子。" if any("孤字" in label for label in top.labels) else
                                "优先保留成牌速度。",
                      "alternative": ("也可打" + "、".join(str(c.tile) for c in peers[:2])) if peers else ""},
            "explanation": "\n".join(lines) + f"\n\n数字来源：{labels}",
            "verification_note": note_footer,
        }

    def _review(self, payload: dict) -> dict:
        decisions = (payload.get("review") or {}).get("decisions") or []
        return {
            "verification_version": VERSION,
            "summary": f"局末复盘：本局 {len(decisions)} 个决策已存档，可逐步回看",
            "explanation": ("复盘怎么看：\n"
                            "1) 每一步的「当时建议＋三家推测」都已随收据存档——回放时能看到"
                            "当时你知道什么、军师怎么判断；\n"
                            "2) 摊牌之后可以对照：当时的推测和实际手牌差在哪；\n"
                            "3) 对照公开线索与实际手牌，持续检验推测；信息增多不保证估计一定更准。"),
            "verification_note": "数学核心实时计算，LLM 不参与决策。",
        }
