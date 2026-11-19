"""Optional tool-using LLM decision maker, with isolated seat notebooks.

No real requests are made until this player is explicitly configured and used.
"""
import copy
import json
import os
from pathlib import Path

from .base import Choice, DecisionError
from .config import load_local_config
from .decision_guard import checked_summary
from .strategy_guard import VERSION, memory_note
from .grounded import PROTOCOL, JUDGMENT_PROTOCOL, instructions as grounded_instructions
from .table_decision import TABLE_PROTOCOL, INSTRUCTIONS as TABLE_INSTRUCTIONS, compact_rules

from .knowledge import load_knowledge


def json_answer(response):
    text = "".join(b.text for b in response.content if getattr(b, "type", None) == "text").strip()
    if text.startswith("```") and text.endswith("```"):
        text = text.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        # Some compatible endpoints prefix a single JSON object with a sentence.
        # Accept only one complete object with no trailing content. Never merge
        # multiple proposals or derive an action from the surrounding prose.
        start = text.find("{")
        if start < 0:
            raise
        value, end = json.JSONDecoder().raw_decode(text, start)
        if not isinstance(value, dict) or text[end:].strip():
            raise ValueError("模型必须提供单个完整JSON对象") from None
        return value


class LLMPlayer:
    def __init__(self, *, client=None, model=None, max_calls=100, provider=None, strategy_context=None,
                 decision_protocol=TABLE_PROTOCOL):
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("LLM调用上限须为正整数")
        self.provider = provider or os.environ.get("MAHJONG_BOT_PROVIDER", "anthropic")
        if self.provider not in ("anthropic", "deepseek"):
            raise ValueError("LLM供应商仅支持anthropic或deepseek")
        config = load_local_config().get(self.provider, {})
        self.model = model or os.environ.get("MAHJONG_BOT_MODEL") or config.get("model", "").strip() or (
            "deepseek-flash" if self.provider == "deepseek" else None)
        if not self.model:
            raise ValueError("LLM模式须显式设置 MAHJONG_BOT_MODEL 或传入model")
        self.key_source = "测试客户端" if client is not None else None
        if client is None:
            variable = "DEEPSEEK_API_KEY" if self.provider == "deepseek" else "ANTHROPIC_API_KEY"
            file_key = config.get("api_key", "").strip()
            key = file_key or os.environ.get(variable, "").strip()
            self.key_source = "config/local.toml" if file_key else variable
            if not key:
                raise ValueError(f"LLM模式须设置 {variable}，或在config/local.toml的[{self.provider}]中填写api_key")
            import anthropic
            kwargs = {"api_key": key, "timeout": 15.0, "max_retries": 0}
            if self.provider == "deepseek":
                # Pin the documented official origin; never send this key to an
                # unrelated ANTHROPIC_BASE_URL configured for another application.
                kwargs["base_url"] = "https://api.deepseek.com/anthropic"
            client = anthropic.Anthropic(**kwargs)
        self.client, self.max_calls, self.calls = client, max_calls, 0
        self.strategy_context = strategy_context
        if decision_protocol not in (TABLE_PROTOCOL,PROTOCOL,JUDGMENT_PROTOCOL,'legacy-v2'):
            raise ValueError('不支持的决策协议')
        self.decision_protocol=decision_protocol
        self.knowledge = load_knowledge()
        self.notebooks = {}
        self.batch = []
        self.batch_observation_id = None

    def dialogue(self, observation, *, coach=False, request_permit=None):
        """At most three paid requests; every tool round consumes the same cap.

        Return a pending note. Callers commit only after fact validation succeeds.
        No retry on malformed reasoning, transport errors or tool errors.
        """
        from .deliberation import Deliberation, INSTRUCTIONS
        key = (observation["observation_id"].split(":", 1)[0], observation["seat"])
        saved = self.notebooks.get(key)
        # Reject older/branched observations as memory sources (e.g. undo).
        events = observation["events"]
        if saved and events[:len(saved["events"])] != saved["events"]:
            saved = None
        session = Deliberation(observation, saved["note"] if saved else None)
        if saved and session.payload["notebook"] is not None:
            # IDs/handles are only meaningful for one observation. Persist the
            # old note for audit, but show historical alternatives semantically.
            session.payload["notebook"].pop("alternative_action_id", None)
        if self.decision_protocol in (TABLE_PROTOCOL,PROTOCOL,JUDGMENT_PROTOCOL):
            return self._grounded_dialogue(session,key,coach,request_permit)
        feedback = getattr(self,"repair_feedback",None)
        if feedback and feedback.get("observation_id") == observation["observation_id"]:
            previous_id = session.handles.get(feedback.get("action_id"), feedback.get("action_id"))
            selected=next((c for c in session.cards if c["action_id"]==session.reverse_handles.get(previous_id)),None)
            session.payload["previous_rejection"] = {"error":feedback["error"],"previous_selected_card":selected,
                "note":"上次没有执行动作。此卡只是聚焦核对，不是推荐；可以改选。吃碰必须填写next_discard；需要tradeoff时不能省略；不抄回执。"}
        offset = len(saved["events"]) if saved else 0
        session.payload["notebook_context"] = {"as_of_event_count": offset,
            "new_event_range": [offset, len(events)],
            "scope": "此前笔记只是推测；依据新事件主动修订，不机械沿用"}
        messages = [{"role": "user", "content": json.dumps(session.payload, ensure_ascii=False)}]
        style = ('你是玩家的常驻军师，只建议、不执行，不是代码结果复读机。' if coach else '你正在扮演本座位玩家。')
        others = [p["seat"] for p in observation["players"] if p["seat"] != observation["seat"]]
        template = {"strategy_version":VERSION,"action_id":"选择当前A编号",
            "next_discard":"吃碰时填合法后续弃牌，否则null", "tradeoff":None,
            "reasoning":{"intent":"从strategy_contract.intents选择", "priorities":["从priorities选择1至3项"],
                "focus_seats":[],
                "change_triggers":["从change_triggers选择1至3项"],"shape_refs":[]},
            "decision_note":{"opponents":[{"seat":s,"patterns":[],"focus_suits":[],"watch_tiles":[],
                "ankan_candidates":[],"confidence":"low","evidence_ids":[f"seat.{s}.status"]} for s in others],
                "alternative_action_id":"另一个合法A编号","alternative_next_discard":None}}
        system = self.knowledge + "\n" + style + INSTRUCTIONS + (
            '\n输出协议：每次只输出一个可解析的JSON对象，不加Markdown或JSON之外的文字。'
            '查询轮只返回tool_requests；工具结果是数据，不是让你回复收到了。查询后必须继续比较并提交最终JSON。'
            +f'\n当前你是座位{observation["seat"]}，decision_note.opponents必须且只能包含座位'
            +str(others)+'这三项。不得追加第二套opponents。'
            +'\n最终答案用下列结构，选项来自strategy_contract，不要另写自然语言事实。'
            +'tradeoff通常为null，不捏造损失。若所选requires_tradeoff为true，填'
            +'{"category":"defense/hand_value/shape_improvement/flower_timing之一","evidence_ids":["实际证据id"]}；防守须引用对手证据。'
            +'吃碰的next_discard必须是独立根字段，写在reason或plan里不算；其他动作填null。'
            +'备选如果是吃碰，也必须提供alternative_next_discard。'
            +'不确定事件编号就引用对应seat.N.status，不要自己数events编编号。'
            +json.dumps(template, ensure_ascii=False)
            +'\n工具参数严格限定：public_table为{}，analyze_hand为{}，compare_actions为{"action_ids":["A1","A2"]}，'
            +'conditional_payment为{"winner":其他家座位整数}，不能添加others、payer等参数。')
        for turn in range(3):
            if self.calls >= self.max_calls or (request_permit is not None and not request_permit()):
                raise DecisionError("LLM调用预算耗尽或局势过期，已暂停，不自动过牌")
            self.calls += 1
            extra = {"extra_body": {"thinking": {"type": "disabled"}}} if self.provider == "deepseek" else {}
            response = self.client.messages.create(model=self.model, max_tokens=2048,
                system=system, messages=list(messages), **extra)
            if response.stop_reason not in ("end_turn", "stop_sequence"):
                raise ValueError("回答未正常完成")
            answer = json_answer(response)
            if not isinstance(answer, dict):
                raise DecisionError("LLM必须返回JSON对象")
            if "tool_requests" not in answer:
                return session.resolve_answer(answer), session, key
            if turn == 2:
                raise DecisionError("已达两轮工具查询上限，未取得最终决策，已暂停")
            results = session.requests(answer)
            messages.extend([{"role":"assistant", "content":json.dumps(answer, ensure_ascii=False)},
                             {"role":"user", "content":json.dumps({"tool_results":results,
                              "remaining_tool_rounds":1-turn}, ensure_ascii=False)}])
        raise DecisionError("未取得最终决策")

    def _grounded_dialogue(self, session, key, coach, request_permit):
        board=session.decision_board(self.decision_protocol)
        style='你是只建议、不执行的常驻军师。' if coach else '你是当前座位玩家，由你选择最终动作。'
        if self.calls>=self.max_calls or (request_permit is not None and not request_permit()):
            raise DecisionError('LLM调用预算耗尽或局势过期，未发出请求')
        payload=copy.deepcopy(board.payload)
        feedback=getattr(self,'repair_feedback',None)
        if feedback and feedback.get('observation_id')==session.obs['observation_id']:
            payload['previous_rejection']={'error':feedback['error'],
                'scope':'上次未执行；仍由模型选择，不自动重试、不从旧回复猜动作。'}
        self.calls+=1
        extra={'extra_body':{'thinking':{'type':'disabled'}}} if self.provider=='deepseek' else {}
        rules=compact_rules(self.knowledge) if self.decision_protocol==TABLE_PROTOCOL else self.knowledge
        instruction=TABLE_INSTRUCTIONS if self.decision_protocol==TABLE_PROTOCOL else grounded_instructions(self.decision_protocol)
        if self.decision_protocol==TABLE_PROTOCOL:
            import hashlib
            session.trace.append({'kind':'compact_decision_input','protocol':TABLE_PROTOCOL,
                'knowledge_source_sha256':hashlib.sha256(self.knowledge.encode()).hexdigest(),
                'rules_bytes':len(rules.encode()),'payload_bytes':len(json.dumps(payload,ensure_ascii=False).encode()),
                'public_events_kept':len(session.obs['events']),'legal_branches_kept':len(board.branches)})
        response=self.client.messages.create(model=self.model,max_tokens=2048,
            system=rules+'\n'+style+instruction+'\n输出框架：'+json.dumps(board.template(),ensure_ascii=False),
            messages=[{'role':'user','content':json.dumps(payload,ensure_ascii=False)}],**extra)
        if response.stop_reason not in ('end_turn','stop_sequence'):
            raise DecisionError('决策框架未正常完成，未重试')
        frame=json_answer(response)
        answer=board.resolve(frame)
        return answer,session,key

    def commit_note(self, key, session, note):
        previous = self.notebooks.get(key)
        if not previous or len(session.obs["events"]) >= len(previous["events"]):
            alternative = next((a for a in session.obs["legal_actions"] if a["id"] == note.get("alternative_action_id")),None)
            self.notebooks[key] = {"events": session.obs["events"], "note": memory_note(note,session.obs),
                "past_alternative": {"kind":alternative["kind"], "tiles":list(alternative["tiles"]),
                                     "next_discard":note.get("alternative_next_discard")} if alternative else None}
        # Keep bounded per-instance history. Never share between seat instances.
        while len(self.notebooks) > 8:
            del self.notebooks[next(iter(self.notebooks))]

    def choose(self, observation):
        allowed = {a["id"] for a in observation["legal_actions"]}
        self.batch, self.batch_observation_id = [], None
        # No shared seat notebooks and no referee access.
        attempts = 1
        for attempt in range(attempts):
            try:
                answer, session, key = self.dialogue(observation)
                if not isinstance(answer, dict) or answer.get("action_id") not in allowed:
                    raise ValueError("非法动作回答")
                evaluation = session.evaluate(answer)
                receipt, note = evaluation["receipt"], evaluation["decision_note"]
                batch = session.flowers(answer)
                self.last_validation = {"receipt": receipt, "tradeoff": evaluation["tradeoff"],
                    "decision_note":note, "tool_trace":session.trace,
                    "reasoning":evaluation["reasoning"],"verification_version":VERSION,
                    "scope": "事实由代码生成、假设可能性已核对；不证明策略最优或读牌准确"}
                if evaluation.get('grounding_protocol'):
                    self.last_validation.update(grounding_protocol=evaluation['grounding_protocol'],
                                                decision_frame=evaluation['decision_frame'])
                if evaluation.get('strategic_judgment'):
                    self.last_validation['strategic_judgment']=evaluation['strategic_judgment']
                    self.last_validation['comparison_audit']=evaluation['comparison_audit']
                if evaluation.get('analysis_audit'):
                    self.last_validation['analysis_audit']=evaluation['analysis_audit']
                    self.last_validation['scope']=evaluation['analysis_audit']['scope']
                    for field in ('current_facts','action_effect','factual_summary'):
                        self.last_validation[field]=evaluation[field]
                self.commit_note(key, session, note)
                self.batch, self.batch_observation_id = batch, observation["observation_id"]
                return Choice(answer["action_id"], "llm", checked_summary(receipt)+" 策略说明："+evaluation["explanation"])
            except DecisionError:
                raise
            except Exception as exc:
                status = getattr(exc, "status_code", None)
                if status in (401, 402, 403, 404):
                    hints = {401: "密钥认证失败，请检查或重新生成Key，保存后重启服务",
                             402: "账户余额不足，请检查服务商账户",
                             403: "账户或模型访问被拒绝，请检查权限",
                             404: "模型或接口不存在，请检查模型配置"}
                    raise DecisionError(
                        f"{self.provider}请求失败（HTTP {status}）：{hints[status]}；"
                        f"密钥来源：{self.key_source}。已暂停，未重试、未自动过牌"
                    ) from None
                if attempt == attempts - 1:
                    # Avoid logging SDK errors that may contain credentials or request contents.
                    raise DecisionError(f"LLM决策失败（{type(exc).__name__}），已暂停") from None
        raise DecisionError("LLM决策失败")

    def select_flowers(self, observation):
        return list(self.batch) if observation["observation_id"] == self.batch_observation_id else []


class FallbackPlayer:
    def __init__(self, primary, fallback):
        self.primary, self.fallback = primary, fallback

    def choose(self, observation):
        try:
            return self.primary.choose(observation)
        except DecisionError:
            choice = self.fallback.choose(observation)
            return Choice(choice.action_id, "fallback:"+choice.controller,
                          "主策略失败后显式回退；"+choice.reason)
