"""Budgeted, private self-play collection. This is NOT weight training.

Policies receive only observe(); oracle replays/outcomes stay separate. A durable
ledger reserves an entire request BEFORE dispatch, including failed requests whose
usage is unknown. No automatic retries or promotion of generated advice.
"""
import copy
from collections import Counter
from datetime import datetime, timezone, timedelta
from decimal import Decimal
import fcntl
import hashlib
import json
import os
import time
from pathlib import Path

from ..players.base import Choice, DecisionError
from ..players.heuristic import HeuristicPlayer
from ..players.analysis import analyze_actions
from .observation import observe
from .replay import save


def private_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)


class Budget:
    # Official Flash peak tariff checked 2026-10-24. Use peak rates as a
    # conservative estimate, but do not charge cached input at uncached rates.
    INPUT_RATE = Decimal("2")
    CACHE_RATE = Decimal("0.04")
    OUTPUT_RATE = Decimal("8")
    PRICING = "flash-time-and-cache-aware-2026-10-24"
    MAX_INPUT = 131072
    MAX_OUTPUT = 2048

    def __init__(self, path, limit_cny="3", max_calls=240):
        self.path = Path(path)
        self.limit = Decimal(str(limit_cny))
        if not self.limit.is_finite() or not 0 < self.limit <= 30:
            raise ValueError("实验预算必须大于0且不超过30元")
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("调用上限必须是正整数")
        self.max_calls = max_calls
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._update(lambda data: None)

    def _update(self, operation):
        fd = os.open(self.path, os.O_RDWR | os.O_CREAT, 0o600)
        with os.fdopen(fd, "r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            raw = stream.read()
            data = json.loads(raw) if raw else {
                "limit_cny": str(self.limit), "max_calls": self.max_calls,
                "pricing": self.PRICING,
                "requests": []}
            if Decimal(data["limit_cny"]) != self.limit or data["max_calls"] != self.max_calls:
                raise ValueError("同一实验不可重设预算或调用上限")
            result = operation(data)
            stream.seek(0)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())
            return result

    @classmethod
    def cost(cls, inputs, outputs, cached=0, *, off_peak=False):
        amount=(Decimal(inputs)*cls.INPUT_RATE + Decimal(cached)*cls.CACHE_RATE
                + Decimal(outputs)*cls.OUTPUT_RATE)/1000000
        return amount/2 if off_peak else amount

    @staticmethod
    def off_peak_at(timestamp):
        # Official schedule: Beijing weekdays 09-12/14-18 peak, otherwise half.
        # No guessed holiday discounts: treating a weekday holiday as peak is
        # conservative. Missing timestamps retain the full peak estimate.
        if not timestamp:
            return False
        moment=datetime.fromisoformat(timestamp).astimezone(timezone(timedelta(hours=8)))
        return moment.weekday()>=5 or not (9<=moment.hour<12 or 14<=moment.hour<18)

    @classmethod
    def migrate_cache_pricing(cls, path, max_calls):
        """Explicit accounting correction, NOT a new money budget.

        Retain each legacy charge and all unknown reservations. The operator
        records a higher request ceiling to run the user's ten-hand batch.
        """
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("调用上限必须为正整数")
        with Path(path).open("r+",encoding="utf-8") as stream:
            fcntl.flock(stream,fcntl.LOCK_EX)
            data=json.load(stream)
            if max_calls < max(data["max_calls"],len(data["requests"])):
                raise ValueError("迁移不能降低既有请求计数或上限")
            before=sum((Decimal(r["charged_upper_cny"]) for r in data["requests"]),Decimal(0))
            old_pricing,old_calls=data.get("pricing"),data["max_calls"]
            for r in data["requests"]:
                if r["status"] == "usage_recorded":
                    u=r["usage"]
                    r.setdefault("legacy_charged_upper_cny",r["charged_upper_cny"])
                    r["charged_upper_cny"]=str(cls.cost(u["input_tokens"]+u.get("cache_creation_input_tokens",0),
                        u["output_tokens"],u.get("cache_read_input_tokens",0),off_peak=cls.off_peak_at(r.get("time"))))
            data["pricing"]=cls.PRICING
            data["max_calls"]=max_calls
            after=sum((Decimal(r["charged_upper_cny"]) for r in data["requests"]),Decimal(0))
            data.setdefault("accounting_changes",[]).append({"from_pricing":old_pricing,"to_pricing":cls.PRICING,
                "old_max_calls":old_calls,"max_calls":max_calls,"old_upper_cny":str(before),"new_upper_cny":str(after),
                "money_limit_unchanged":data["limit_cny"],"reason":"user requested ten live hands; fix cache pricing, preserve unknown usage",
                "time":datetime.now(timezone.utc).isoformat()})
            stream.seek(0);json.dump(data,stream,ensure_ascii=False,indent=2);stream.truncate();stream.flush();os.fsync(stream.fileno())
            return {"calls":len(data["requests"]),"limit_cny":data["limit_cny"],"upper_cny":str(after),"max_calls":max_calls}

    def reserve(self):
        def operation(data):
            spent = sum((Decimal(r["charged_upper_cny"]) for r in data["requests"]), Decimal(0))
            amount = self.cost(self.MAX_INPUT, self.MAX_OUTPUT)
            if len(data["requests"]) >= self.max_calls or spent+amount > self.limit:
                raise DecisionError("实验共享预算／调用上限触发；保存暂停，不自动回退")
            index = len(data["requests"])
            data["requests"].append({"status": "reserved", "charged_upper_cny": str(amount),
                                     "time": datetime.now(timezone.utc).isoformat()})
            return index
        return self._update(operation)

    def settle(self, index, usage):
        # Unknown/invalid usage retains the full reservation; never guess zero.
        fields = ("input_tokens", "output_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
        counts = {name: getattr(usage, name, 0) for name in fields}
        for name in fields[2:]:
            if counts[name] is None:
                counts[name] = 0
        if any(type(n) is not int or n < 0 for n in counts.values()):
            return
        if not hasattr(usage, "input_tokens") or not hasattr(usage, "output_tokens"):
            return
        def operation(data):
            entry = data["requests"][index]
            if entry["status"] != "reserved":
                raise ValueError("请求不可重复结算")
            entry.update(status="usage_recorded", usage=counts,
                         charged_upper_cny=str(self.cost(counts["input_tokens"]+counts["cache_creation_input_tokens"],
                            counts["output_tokens"],counts["cache_read_input_tokens"],off_peak=self.off_peak_at(entry.get("time")))))
        self._update(operation)

    def record_failure(self, index, exception):
        # Exception text/args/request objects can expose credentials. Record
        # class names and numeric OS codes only; unknown usage stays reserved.
        chain, seen = [], set()
        current = exception
        while current is not None and id(current) not in seen and len(chain) < 8:
            seen.add(id(current))
            item = {"type": type(current).__name__}
            code = getattr(current, "errno", None)
            if type(code) is int:
                item["errno"] = code
            chain.append(item)
            current = current.__cause__ or current.__context__
        self._update(lambda data: data["requests"][index].update(failure_chain=chain))

    def record_metrics(self,index,*,elapsed,prompt_bytes,stop_reason=None):
        self._update(lambda data:data["requests"][index].update(api_elapsed_seconds=round(elapsed,3),
            prompt_bytes=prompt_bytes,stop_reason=stop_reason))

    def summary(self):
        return self._update(lambda data: {
            "limit_cny": str(self.limit), "calls": len(data["requests"]),
            "unknown_usage_requests": sum(r["status"] == "reserved" for r in data["requests"]),
            "known_usage_estimate_cny":str(sum((Decimal(r["charged_upper_cny"]) for r in data["requests"] if r["status"]=="usage_recorded"),Decimal(0))),
            "unknown_reservations_cny":str(sum((Decimal(r["charged_upper_cny"]) for r in data["requests"] if r["status"]=="reserved"),Decimal(0))),
            "charged_upper_cny": str(sum((Decimal(r["charged_upper_cny"]) for r in data["requests"]), Decimal(0)))})

    @classmethod
    def increase_authorized_calls(cls, path, max_calls):
        """Explicit operator action: only raise calls, never reprice old usage."""
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError("调用上限必须为正整数")
        with Path(path).open("r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            data = json.load(stream)
            old = data["max_calls"]
            if max_calls <= max(old,len(data["requests"])):
                raise ValueError("新授权调用上限必须高于原上限及已有计数")
            data.setdefault("budget_changes", []).append({"old_max_calls":old,"max_calls":max_calls,
                "money_limit_unchanged":data["limit_cny"],"authorization":"explicit-user-request",
                "time":datetime.now(timezone.utc).isoformat()})
            data["max_calls"] = max_calls
            stream.seek(0)
            json.dump(data,stream,ensure_ascii=False,indent=2)
            stream.truncate();stream.flush();os.fsync(stream.fileno())

    @classmethod
    def increase_authorized_limit(cls, path, limit_cny):
        """Explicit operator action only; preserve all prior charges/reservations."""
        limit = Decimal(str(limit_cny))
        if not limit.is_finite() or not 0 < limit <= 30:
            raise ValueError("授权上限须大于0且不超过30元")
        with Path(path).open("r+", encoding="utf-8") as stream:
            fcntl.flock(stream, fcntl.LOCK_EX)
            data = json.load(stream)
            old = Decimal(data["limit_cny"])
            if limit <= old:
                raise ValueError("新授权上限必须高于原上限")
            data.setdefault("budget_changes", []).append({"from": str(old), "to": str(limit),
                "authorization": "explicit-user-request", "time": datetime.now(timezone.utc).isoformat()})
            data["limit_cny"] = str(limit)
            stream.seek(0)
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.truncate()
            stream.flush()
            os.fsync(stream.fileno())


class MeteredClient:
    def __init__(self, client, budget, funds_guard=None, *, flower_batches=True):
        self.client, self.budget, self.messages = client, budget, self
        self.funds_guard=funds_guard
        self.flower_batches=flower_batches

    def create(self, **kwargs):
        self.last_answer = None
        self.last_model_output = None
        kwargs = dict(kwargs)
        if self.flower_batches:
            kwargs["system"] = kwargs.get("system", "") + (
            '\n实验接口补充：若选择flower_kong，可额外返回"flower_batch":["春","中"]，'
            '表示一次选择当前手中的多张花（重复同款须逐张列出），先含所选动作对应花牌。'
            '仅选择当前持有且可单换的牌，不包含换来后才看到的新牌；四张单换不是暗杠。'
            '比较整批换花与留花，不要每张花都重复请求。只有持同款三张时，才重点评估等第四张；'
            '单张等到四张不能被当作无成本的保留理由。手牌刻子、对子必须核对实际数量。')
        if kwargs.get("model") != "deepseek-flash" or kwargs.get("max_tokens", 0) > Budget.MAX_OUTPUT:
            raise DecisionError("预算价格仅适用于deepseek-flash及限定输出长度")
        # Conservative byte bound leaves 11k tokens for serialization/control
        # overhead. No tools, attachments, or server-side search are permitted.
        if set(kwargs)-{"model", "max_tokens", "system", "messages", "extra_body"}:
            raise DecisionError("实验禁止未计费的工具或附件参数")
        size = len(json.dumps(kwargs, ensure_ascii=False).encode("utf-8"))
        if size > 120000:
            raise DecisionError("上下文超过保守计费边界，暂停而不截断信息")
        if self.funds_guard is not None:
            self.funds_guard()
        index = self.budget.reserve()
        started=time.monotonic()
        try:
            response = self.client.messages.create(**kwargs)
        except Exception as exc:
            self.budget.record_failure(index, exc)
            self.budget.record_metrics(index,elapsed=time.monotonic()-started,prompt_bytes=size)
            raise
        self.budget.record_metrics(index,elapsed=time.monotonic()-started,prompt_bytes=size,
                                   stop_reason=getattr(response,"stop_reason",None))
        self.budget.settle(index, getattr(response, "usage", None))
        # Only returned model text/stop reason, never SDK request/header/error
        # objects. Private diagnostic record for malformed protocol responses.
        self.last_model_output = {"stop_reason": getattr(response,"stop_reason",None),
            "text": "".join(b.text for b in getattr(response,"content",[]) if getattr(b,"type",None)=="text")[:16000]}
        from ..players.llm import json_answer
        self.last_answer = json_answer(response)
        return response


class ExperimentPlayer:
    """Additional batch protocol is local to the lab, not the desktop contract."""
    def __init__(self, player):
        self.player, self.batch = player, []

    def choose(self, obs):
        self.batch = []
        self.last_rejection = None
        try:
            choice = self.player.choose(obs)
        except DecisionError as exc:
            answer = getattr(self.player.client, "last_answer", None)
            self.last_rejection = {"observation": copy.deepcopy(obs), "answer": copy.deepcopy(answer),
                                   "model_output":copy.deepcopy(getattr(self.player.client,"last_model_output",None)),
                                   "error": str(exc), "executed": False}
            raise
        answer = self.player.client.last_answer
        batch = answer.get("flower_batch", [])
        if not isinstance(batch, list) or any(not isinstance(t, str) for t in batch):
            raise DecisionError("实验换花批次格式错误，未执行")
        action = next(a for a in obs["legal_actions"] if a["id"] == choice.action_id)
        if batch:
            legal = {a["tiles"][0] for a in obs["legal_actions"] if a["kind"] == "flower_kong"}
            if (action["kind"] != "flower_kong" or batch[0] != action["tiles"][0]
                    or Counter(batch)-Counter(obs["self"]["hand"])
                    or not set(batch) <= legal or len(batch) > obs["wall_count"]):
                raise DecisionError("实验换花批次非法，整批未执行")
            self.batch = batch
        return choice

    def select_flowers(self, obs):
        return list(self.batch)


def experiment_context(obs):
    from .coaching import opponent_evidence
    return {"opponents": opponent_evidence(obs), "own_hand_counts": dict(Counter(obs["self"]["hand"])),
            "warning": "刻子对子只能依据实际副本数；未见牌不等于在墙；不输出伪造胜率"}


def play_experiment(table, players, dataset_path, *, max_decisions=2000, progress=None):
    """Freeze a whole response window before asking anyone; journal before apply.

    JSONL contains own/private-per-seat facts, not globally public training data.
    No post-game oracle state is ever appended to model inputs.
    """
    if len(players) != 4:
        raise ValueError("必须配置四个玩家")
    fd = os.open(dataset_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        while table.stage != "ended":
            observations = [(seat, observe(table, seat)) for seat in table.waiting_seats()]
            if len(table.decisions)+len(observations) > max_decisions:
                raise DecisionError("到达动作上限")
            choices = []
            for seat, obs in observations:
                actions = obs["legal_actions"]
                if not actions:
                    raise DecisionError("裁判没有合法动作")
                win = next((a for a in actions if a["kind"] in ("win", "ron")), None)
                # LLMs decide every non-forced action, including passing a win.
                if win and not hasattr(getattr(players[seat], "player", players[seat]), "client"):
                    choice = Choice(win["id"], "experiment:take-win", "实验约定：合法胡牌即胡；不是所有策略都必须如此")
                elif len(actions) == 1:
                    choice = Choice(actions[0]["id"], "forced", "唯一合法动作")
                else:
                    choice = players[seat].choose(copy.deepcopy(obs))
                if choice.action_id not in {a["id"] for a in actions}:
                    raise DecisionError("玩家返回非法动作，当前响应窗口不执行")
                row = {"observation": obs, "analysis": analyze_actions(obs),
                       "execution": "proposed; verify commitment in referee replay",
                       "choice": {"action_id": choice.action_id, "controller": choice.controller, "reason": choice.reason}}
                validation = getattr(getattr(players[seat], "player", players[seat]), "last_validation", None)
                if choice.controller == "llm" and validation is not None:
                    row["decision_validation"] = validation
                selector = getattr(players[seat], "select_flowers", None)
                selected = selector(obs) if callable(selector) else []
                row["flower_batch"] = selected
                stream.write(json.dumps(row, ensure_ascii=False)+"\n")
                stream.flush()
                choices.append((seat, choice, selected))
                if progress:
                    progress(table, seat, choice)
            for seat, choice, selected in choices:
                action = next(a for s, obs in observations if s == seat for a in obs["legal_actions"] if a["id"] == choice.action_id)
                if action["kind"] == "flower_kong" and len(selected) > 1:
                    if len(table.decisions)+len(selected) > max_decisions:
                        raise DecisionError("批量换花将超出动作上限，整批未执行")
                    table.exchange_flowers(seat, selected, controller=choice.controller+":batch")
                else:
                    table.apply(seat, choice.action_id, controller=choice.controller, reason=choice.reason)
    return table.result


def summarize_decisions(path):
    """Compare shapes, NOT claim a different action was a strategic mistake."""
    result = {"decisions": 0, "llm_decisions": 0, "baseline_disagreements": 0,
              "shape_regressions": [], "limitation": "牌效分歧不等于错误；没有反事实整局净收益评估"}
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            result["decisions"] += 1
            if row["choice"]["controller"] != "llm":
                continue
            result["llm_decisions"] += 1
            baseline = HeuristicPlayer().choose(row["observation"])
            if baseline.action_id != row["choice"]["action_id"]:
                result["baseline_disagreements"] += 1
            fact = next(a for a in row["analysis"]["candidates"] if a["action_id"] == row["choice"]["action_id"])
            discards = [a for a in row["analysis"]["candidates"] if a["kind"] == "discard"]
            if fact["kind"] == "discard" and discards and fact["shanten"] > min(a["shanten"] for a in discards):
                result["shape_regressions"].append({"observation_id": row["observation"]["observation_id"],
                    "chosen": fact, "reason": row["choice"]["reason"],
                    "note": "向听退步候选，需结合防守／价值核查；不是已确认错误"})
    return result


def run_hand(table, players, directory, *, max_decisions=2000, progress=None):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=False)
    status, error = "completed", None
    try:
        play_experiment(table, players, directory/"decisions.jsonl", max_decisions=max_decisions, progress=progress)
    except (DecisionError, KeyboardInterrupt) as exc:
        status = "interrupted" if isinstance(exc, KeyboardInterrupt) else "paused"
        error = str(exc) if isinstance(exc, DecisionError) else "KeyboardInterrupt"
        # Sanitized errors only: SDK exception strings can contain credentials.
    except Exception as exc:
        status, error = "error", type(exc).__name__
        raise
    finally:
        save(table, directory/"referee-private.json")
        for seat, player in enumerate(players):
            rejection = getattr(player, "last_rejection", None)
            if rejection is not None:
                private_json(directory/f"rejected-seat-{seat}.json", rejection)
        report = {"status": status, "error": error, "stage": table.stage,
                  "rules_version": table.rules_version, "result": table.result,
                  "weights_updated": False, "knowledge_promoted": False,
                  "audit": summarize_decisions(directory/"decisions.jsonl")}
        private_json(directory/"report.json", report)
        if table.stage == "ended":
            export_oracle_labels(table, directory/"decisions.jsonl", directory/"labels-offline-only.jsonl")
    return report


def export_oracle_labels(table, decisions_path, labels_path):
    """Generate supervised opponent targets AFTER game end, never in prompts.

    Reconstruct the actual hidden state at each decision, not merely final hands.
    Labels describe structure/eligibility, not a promise a tile is alive in wall.
    The entire same-wall family shares a split, preventing rotation leakage.
    """
    if table.stage != "ended":
        raise ValueError("牌局未结束，不得生成全知标签")
    from ..core.hand_analyzer import get_waiting_tiles
    from .engine import Table
    wanted = {}
    with Path(decisions_path).open(encoding="utf-8") as stream:
        for line in stream:
            row = json.loads(line)
            wanted[row["observation"]["observation_id"]] = row
    family = hashlib.sha256(json.dumps([table.rules_version, [str(t) for t in table.initial_wall]]).encode()).hexdigest()
    bucket = int(family[:8], 16) % 10
    split = "test" if bucket == 9 else "validation" if bucket == 8 else "train"
    trial = Table(table.seed, table.dealer, wall=list(table.initial_wall), game_id=table.game_id,
                  rules_version=table.rules_version)
    fd = os.open(labels_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    found = set()
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for decision in table.decisions:
            seat = decision["seat"]
            identity = f"{trial.game_id}:{trial._token()}:{seat}"
            if identity in wanted:
                # Protect labels against mixing unrelated or corrupted journals.
                if observe(trial, seat) != wanted[identity]["observation"]:
                    raise ValueError("标签与决策时观察不一致")
                targets = []
                for opponent, state in enumerate(trial.seats):
                    if opponent == seat:
                        continue
                    base = 13-3*len(state.melds)
                    waits = get_waiting_tiles(state.hand, len(state.melds)) if (
                        len(state.hand) == base and not any(t.is_flower for t in state.hand)) else []
                    counts = Counter(state.hand)
                    counts.update(t for m in state.melds for t in m.tiles)
                    waits = [t for t in waits if counts[t] < 4]
                    targets.append({"seat": opponent, "structural_tenpai": bool(waits),
                        "structural_waits": [str(t) for t in waits],
                        "eligible_ron_tiles": [str(t) for t in waits if trial._score(opponent, "dianpao", t) is not None],
                        "held_flowers": sum(t.is_flower for t in state.hand),
                        "concealed_kongs": [str(m.tiles[0]) for m in state.melds if m.type == "an_gang"]})
                stream.write(json.dumps({"observation_id": identity, "wall_family": family, "split": split,
                    "selected_action_executed": wanted[identity]["choice"]["action_id"] == decision["action"]["id"],
                    "targets": targets, "privacy": "训练标签，仅局末离线使用；不得放入对局／教练请求"}, ensure_ascii=False)+"\n")
                found.add(identity)
            trial.apply(seat, decision["action"]["id"], controller="offline-label")
    if found != set(wanted):
        raise ValueError("存在无法对齐的决策标签")


def consolidate_completed_campaign(directory):
    """Join committed proposals across resumes; discard failed-window proposals."""
    from .replay import replay
    directory = Path(directory)
    replays = sorted(directory.glob("hand-*/referee-private.json"), key=lambda p: p.stat().st_mtime)
    if not replays:
        raise ValueError("没有牌谱")
    table = replay(json.loads(replays[-1].read_text()))
    if table.stage != "ended":
        raise ValueError("牌局尚未结束")
    committed = {d["action"]["id"]: i for i, d in enumerate(table.decisions)}
    rows = {}
    for path in sorted(directory.glob("hand-*/decisions.jsonl"), key=lambda p: p.stat().st_mtime):
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                row = json.loads(line)
                if row["choice"]["action_id"] in committed:
                    rows[row["observation"]["observation_id"]] = row
    dataset = directory/"completed-decisions.jsonl"
    fd = os.open(dataset, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        for row in sorted(rows.values(), key=lambda r: committed[r["choice"]["action_id"]]):
            stream.write(json.dumps(row, ensure_ascii=False)+"\n")
    export_oracle_labels(table, dataset, directory/"completed-labels-offline-only.jsonl")
    audit = summarize_decisions(dataset)
    private_json(directory/"completed-audit.json", audit)
    return audit
