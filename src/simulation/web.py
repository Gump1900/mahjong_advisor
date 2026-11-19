"""Local desktop table. Only redacted seat observations cross the HTTP boundary.

Run: python -m src.simulation.web --port 8766
This is independent of the older real-table recording server on port 8765.
"""
import argparse
import copy
import json
import mimetypes
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlsplit
from uuid import uuid4

from .engine import Table
from .observation import observe
from .replay import replay, save
from .coaching import LLMCoach, teaching_report, historical_review
from ..players.base import Choice, DecisionError
from ..players.heuristic import HeuristicPlayer
from ..core.scoring import flower_hua
from ..core.tiles import parse_tile

ASSETS = Path(__file__).with_name("webapp")


class DesktopTable:
    def __init__(self, table=None, human=0, output_dir="runs/mahjong", *, paced=False, bots=None, defer_bots=False, background=False, auto_coach=False, coach_limit=20):
        if type(coach_limit) is not int or not 1 <= coach_limit <= 50:
            raise ValueError("教练每局预算须为1至50次")
        if type(human) is not int or human not in range(4):
            raise ValueError("真人座位须为0至3")
        self.table = table or Table(random.SystemRandom().randrange(2**53))
        self.human = human
        self.output_dir = Path(output_dir)
        self.lock = threading.RLock()
        self.batch = []
        self.saved = None
        self.saved_revision = None
        self.bots = bots if bots is not None else {seat: HeuristicPlayer() for seat in range(4) if seat != human}
        if set(self.bots) != set(range(4)) - {human}:
            raise ValueError("须分别配置三个对手座位")
        self.bot_error = None
        self.paced = paced
        self.frames = []
        self.background = background
        self.thinking = False
        self.thinking_started = None
        self.bot_last_elapsed_ms = None
        self._coach_cache = None
        self._review_cache = None
        self.strategy_job = None
        self.strategy_revision = 0
        self.coach_job = None
        self.coach_calls = 0
        self.coach_limit = coach_limit
        self.coach_auto = bool(auto_coach)
        self.coach_suspended = bool(defer_bots or self.table.stage == "ended")
        self.coach_feed = []
        self.coach_revision = 0
        self._coach_attempted = set()
        primary = next((getattr(b, "primary", b) for b in self.bots.values()
                        if hasattr(getattr(b, "primary", b), "client")), None)
        self.coach = LLMCoach(primary) if primary is not None else None
        if defer_bots and self.table.stage != "ended":
            self.bot_error = "续局已恢复并暂停；点击重试机器人继续（可能产生API费用），或开启新的一局。"
        else:
            self._advance()

    @property
    def version(self):
        return f"{self.table.game_id}:{self.table.revision}"

    def _advance(self):
        self.bot_error = None
        self.batch = []
        if self.background and self.table.stage != "ended":
            # Freeze all observations under the table lock, but NEVER hold it
            # during an API request. Independent seats get independent contexts.
            observations = [(s, observe(self.table, s)) for s in self.table.waiting_seats()]
            version = self.version
            self.thinking = True
            self.thinking_started = time.monotonic()
            def prepare():
                started = time.monotonic()
                try:
                    with ThreadPoolExecutor(max_workers=3) as pool:
                        batch = list(pool.map(self._choose_observation, observations))
                    error = None
                except Exception as exc:
                    batch = []
                    error = str(exc) if isinstance(exc, DecisionError) else f"机器人准备失败（{type(exc).__name__}），已暂停"
                with self.lock:
                    if self.version != version:
                        return  # A completed old request must not touch a new game.
                    self.thinking = False
                    self.bot_last_elapsed_ms = round((time.monotonic()-started)*1000)
                    self.batch, self.bot_error = batch, error
                    if error:
                        self.checkpoint()
                    else:
                        self._maybe_auto_coach()
            threading.Thread(target=prepare, daemon=True).start()
            return
        self.thinking = False
        try:
            self._prepare_choices()
            self._maybe_auto_coach()
        except DecisionError as exc:
            # No choice from a failed response window is applied or leaked.
            self.batch = []
            self.bot_error = str(exc)
            self.checkpoint()

    def _maybe_auto_coach(self):
        """Schedule only on decision transitions, NEVER as a GET side effect."""
        if not self.coach_auto or self.coach_suspended or not self.coach or self.bot_error:
            return
        if self.coach_calls >= self.coach_limit or (self.coach_job and self.coach_job["status"] == "thinking"):
            return
        mode = "review" if self.table.stage == "ended" else "current"
        if mode == "current" and not any(c is None for _, c in self.batch):
            return
        key = (self.version, mode)
        if key in self._coach_attempted:
            return
        self._coach_attempted.add(key)
        self.request_coach(self.version, mode)

    def coach_settings(self, version, enabled, limit=None):
        with self.lock:
            self._require_version(version)
            if type(enabled) is not bool:
                raise ValueError("常驻教练开关须为布尔值")
            if limit is not None and (type(limit) is not int or not 1 <= limit <= 50):
                raise ValueError("教练每局预算须为1至50次")
            if self.coach is None and enabled:
                raise ValueError("当前尚未配置LLM教练")
            self.coach_auto = enabled
            self.coach_suspended = False
            self.coach_revision += 1
            if limit is not None:
                self.coach_limit = limit
            self._maybe_auto_coach()
            return self.view()

    def _choose_observation(self, item):
        seat, obs = item
        actions = obs["legal_actions"]
        if not actions:
            raise DecisionError("裁判没有合法动作，请保存牌谱排查")
        if len(actions) == 1 and actions[0]["kind"] == "pass":
            choice = Choice(actions[0]["id"], "forced", "唯一合法动作")
        elif seat == self.human:
            choice = None
        else:
            bot = self.bots[seat]
            choice = bot.choose(obs)
        if choice and choice.action_id not in {a["id"] for a in actions}:
            raise DecisionError("机器人返回非法动作，已暂停")
        return seat, choice

    def _prepare_choices(self):
        # Freeze the ENTIRE window before collecting choices. Bot choices stay
        # private until the human also responds; response timing conveys nothing.
        while self.table.stage != "ended":
            if len(self.table.decisions) >= 2000:
                raise DecisionError("动作上限，牌局已暂停，请保存")
            observations = [(s, observe(self.table, s)) for s in self.table.waiting_seats()]
            batch = [self._choose_observation(item) for item in observations]
            waiting_human = any(choice is None for _, choice in batch)
            self.batch = batch
            if waiting_human or self.paced:
                return
            self._commit(batch)
        self.batch = []
        self.checkpoint()

    def _commit(self, batch):
        for seat, choice in batch:
            before = self.view() if self.paced else None
            action = next(a for a in self.table.legal_actions(seat) if a.id == choice.action_id)
            bot = self.bots.get(seat)
            selector = getattr(getattr(bot, "primary", bot), "select_flowers", None)
            flowers = selector(observe(self.table, seat)) if action.kind == "flower_kong" and callable(selector) else []
            if len(flowers) > 1:
                drawn = self.table.exchange_flowers(seat, flowers, controller=choice.controller+":batch")
                if self.paced:
                    self.frames.append(flower_batch_frame(self.view(), seat, flowers, drawn))
                continue
            self.table.apply(seat, choice.action_id, controller=choice.controller, reason=choice.reason)
            if self.paced:
                self.frames.extend(presentation_frames(before, self.view()))

    def view(self):
        with self.lock:
            data = observe(self.table, self.human)
            data["version"] = self.version
            data["saved_file"] = self.saved.name if self.saved else None
            llm = any(type(bot).__name__ in ("LLMPlayer", "FallbackPlayer") for bot in self.bots.values())
            providers = sorted({getattr(getattr(bot, "primary", bot), "provider", "LLM") for bot in self.bots.values()})
            data["bot_description"] = ((" / ".join(providers)+" 策略机器人 · 代码校验 / 非精确胜率搜索") if llm else "基础牌效机器人 · 非大师 / 非完整收益搜索")
            data["bot_error"] = self.bot_error
            data["bot_thinking"] = self.thinking
            data["bot_elapsed_ms"] = round((time.monotonic()-self.thinking_started)*1000) if self.thinking and self.thinking_started else self.bot_last_elapsed_ms
            data["credential_sources"] = sorted({
                getattr(getattr(bot, "primary", bot), "key_source", "无需密钥") for bot in self.bots.values()})
            data["awaiting_human"] = any(c is None for _, c in self.batch) and self.table.stage != "ended"
            data["can_advance"] = bool(self.batch) and not data["awaiting_human"] and self.table.stage != "ended"
            data["coach_available"] = self.coach is not None
            data["coach_revision"] = self.coach_revision
            data["coach_auto"] = self.coach_auto and self.coach is not None
            data["coach_suspended"] = self.coach_suspended
            data["coach_limit"] = self.coach_limit
            data["coach_feed"] = copy.deepcopy(self.coach_feed[-3:])
            data["coach_calls_remaining"] = max(0, self.coach_limit-self.coach_calls)
            data["coach_job"] = copy.deepcopy(self.coach_job) if self.coach_job and self.coach_job["version"] == self.version else None
            data["strategy_revision"] = self.strategy_revision
            data["strategy_job"] = copy.deepcopy(self.strategy_job) if self.strategy_job and self.strategy_job["version"] == self.version else None
            if data["awaiting_human"]:
                if not self._coach_cache or self._coach_cache[0] != self.version:
                    self._coach_cache = (self.version, teaching_report(data))
                data["coaching"] = copy.deepcopy(self._coach_cache[1])
            if self.table.stage == "ended":
                if not self._review_cache or self._review_cache[0] != self.version:
                    self._review_cache = (self.version, historical_review(self.table, self.human))
                data["review"] = copy.deepcopy(self._review_cache[1])
            for player in data["players"]:
                flowers = [parse_tile(t) for t in player["flowers"]]
                player["public_flower_hua"] = flower_hua(
                    konged_flowers=flowers, flower_kong_groups=[[t] for t in flowers])
            if self.table.stage == "ended":
                # Explicitly reveal only AFTER settlement, never mid-game.
                data["revealed_hands"] = [[str(t) for t in s.hand] for s in self.table.seats]
                for p, state in zip(data["players"], self.table.seats):
                    for shown, meld in zip(p["melds"], state.melds):
                        shown.update(tiles=[str(t) for t in meld.tiles], hidden=False)
            return data

    def request_strategy(self, version):
        """Free local comparison; compute outside the lock, never as GET effect."""
        with self.lock:
            self._require_version(version)
            if not any(c is None for _,c in self.batch) or self.table.stage == "ended":
                raise ValueError("请等到自己的决策时机")
            if self.strategy_job and self.strategy_job["version"] == version and self.strategy_job["status"] in ("thinking","ready"):
                return self.view()
            obs = observe(self.table,self.human)
            self.strategy_revision += 1
            job = {"version":version,"status":"thinking"}
            self.strategy_job = job
        def compute():
            from ..players.strategy import strategy_bundle
            try:
                result,error = strategy_bundle(obs,trials=16,horizon=3,time_budget=1),None
            except Exception as exc:
                result,error = None,f"本地方案计算未完成（{type(exc).__name__}），原牌局未改变"
            with self.lock:
                if self.version != version or self.strategy_job is not job:
                    return
                job.update(status="error" if error else "ready",result=result,error=error)
                self.strategy_revision += 1
        threading.Thread(target=compute,daemon=True).start()
        return self.view()

    def request_coach(self, version, mode="current"):
        with self.lock:
            self._require_version(version)
            if mode not in ("current", "review"):
                raise ValueError("未知讲解模式")
            if self.coach is None:
                raise ValueError("当前未配置LLM；代码建议与复盘仍可使用")
            if self.coach_job and self.coach_job["status"] == "thinking":
                raise ValueError("已有教练请求进行中，请等待，不重复计费")
            if self.coach_job and self.coach_job["version"] == version and self.coach_job["mode"] == mode and self.coach_job["status"] == "ready":
                return self.view()
            view = self.view()
            if mode == "review":
                if self.table.stage != "ended":
                    raise ValueError("只有局末才能请求整局复盘")
                review = view["review"]
                key_steps = [d for d in review["decisions"] if d["different"] and d["actual"]["kind"] != "flower_kong"]
                protected, seen = [], set()
                for decision in review["decisions"]:
                    if decision["actual"]["kind"] != "discard":
                        continue
                    facts = decision.get("strategy_facts", {})
                    tags = [("three_flowers", f["tile"]) for f in facts.get("three_identical_flower_options", [])]
                    for shape in facts.get("local_shape_checks", []):
                        if any(option["discard"] in decision["actual"]["tiles"] for option in shape["options_preserving_all_local_waits"]):
                            tags.append(("shape", tuple(shape["tiles"])))
                    if any(tag not in seen for tag in tags):
                        seen.update(tags)
                        protected.append(decision)
                selected = protected[:3]
                for decision in reversed(key_steps or review["decisions"]):
                    if len(selected) == 8:
                        break
                    if all(d["step"] != decision["step"] for d in selected):
                        selected.append(decision)
                payload = {"review": {**review, "decisions": sorted(selected, key=lambda d: d["step"]),
                                       "selection_note": "最多八步，优先保留早期留三同花与重叠搭子的决策，再补候选差异；不能只看最后几手。完整代码复盘保留在页面。"}}
            else:
                if not view["awaiting_human"]:
                    raise ValueError("请等到自己的决策时机再请求建议")
                payload = {"observation": observe(self.table, self.human), "code_report": view["coaching"]}
            payload["coaching_memory"] = [{"version": entry["version"], "summary": entry["result"]["summary"]}
                                          for entry in self.coach_feed[-3:]]
            if self.coach_calls >= self.coach_limit:
                raise ValueError(f"本局教练调用已达{self.coach_limit}次，代码建议不受影响")
            from .coaching import LLMCoach
            if isinstance(self.coach, LLMCoach):
                def permit():
                    with self.lock:
                        if self.version != version or self.coach_calls >= self.coach_limit:
                            return False
                        self.coach_calls += 1
                        return True
                payload["_request_permit"] = permit
            else:
                self.coach_calls += 1
            self.coach_revision += 1
            self.coach_job = {"version": version, "mode": mode, "status": "thinking"}
            job = self.coach_job
            def explain():
                try:
                    output, error = self.coach.explain(payload), None
                except Exception as exc:
                    output = None
                    error = str(exc) if isinstance(exc, DecisionError) else "教练请求未完成，代码分析仍可用"
                with self.lock:
                    self.coach_revision += 1
                    same_game = self.version.split(":")[0] == version.split(":")[0]
                    if output and same_game:
                        self.coach_feed.append({"version": version, "mode": mode, "result": output})
                        self.coach_feed = self.coach_feed[-5:]
                    if self.version != version:
                        job["status"] = "stale"
                        self._maybe_auto_coach()
                        return
                    if self.coach_job is not job:
                        return
                    job.update(status="error" if error else "ready", result=output, error=error)
            threading.Thread(target=explain, daemon=True).start()
            return self.view()

    def response(self):
        data = self.view()
        if self.paced:
            data["frames"] = self.frames
        self.frames = []
        return data

    def step(self, version):
        with self.lock:
            self._require_version(version)
            if not self.paced or not self.view()["can_advance"]:
                raise ValueError("当前须等待真人选择，不能跳过")
            self.frames = []
            self._commit(self.batch)
            self._advance()
            return self.response()

    def retry_bots(self, version):
        with self.lock:
            self._require_version(version)
            if not self.bot_error:
                raise ValueError("当前没有待重试的机器人错误")
            self.coach_suspended = False
            self._advance()
            return self.response()

    def _require_version(self, version):
        if version != self.version:
            raise ValueError("页面局面已过期，请刷新后操作；没有执行旧动作")

    def action(self, version, action_id):
        with self.lock:
            self._require_version(version)
            actions = observe(self.table, self.human)["legal_actions"]
            if action_id not in {a["id"] for a in actions}:
                raise ValueError("不是当前合法动作")
            if not any(s == self.human and c is None for s, c in self.batch):
                raise ValueError("当前不等待你的选择")
            batch = [(s, Choice(action_id, "human:web") if c is None else c) for s, c in self.batch]
            self.frames = []
            self._commit(batch)
            self._advance()
            return self.response()

    def checkpoint(self):
        with self.lock:
            if self.saved_revision != self.version:
                self.saved = save(self.table, self.output_dir / f"{self.table.game_id}-{uuid4().hex[:8]}.json")
                self.saved_revision = self.version
            return self.saved

    def exchange_flowers(self, version, tiles):
        """One explicit selection, replayed as ordinary single-flower actions.

        Validate the entire transaction on a private clone before committing.
        Replacements never extend the selection, including newly drawn flowers.
        """
        with self.lock:
            self._require_version(version)
            view = self.view()
            if not view["awaiting_human"] or self.table.stage != "turn" or self.table.actor != self.human:
                raise ValueError("当前不是自己的合法换花时机")
            drawn = self.table.exchange_flowers(self.human, tiles, controller="human:web:batch")
            self.frames = []
            self._advance()
            result = self.response()
            result["batch_result"] = {"exchanged": list(tiles), "drawn": drawn}
            if self.paced:
                result["frames"] = [flower_batch_frame(result, self.human, tiles, drawn)]
            return result

    def new_game(self, version, seed=None, dealer=0):
        with self.lock:
            self._require_version(version)
            if seed is not None and (type(seed) is not int or not 0 <= seed < 2**53):
                raise ValueError("种子须为0至9007199254740991的整数，或留空随机")
            if type(dealer) is not int or dealer not in range(4):
                raise ValueError("庄家座位须为0至3")
            self.checkpoint()  # Preserve an unfinished game before replacing it.
            self.table = Table(seed if seed is not None else random.SystemRandom().randrange(2**53), dealer)
            self.saved = self.saved_revision = None
            self.frames = []
            self._coach_cache = self._review_cache = None
            self.strategy_job = None
            self.strategy_revision += 1
            self.coach_calls = 0
            self.coach_revision += 1
            self.coach_feed = []
            self._coach_attempted.clear()
            self.coach_suspended = False
            # Do not launch overlapping paid coach calls after changing games.
            # An old in-flight job is discarded when its version no longer matches.
            self._advance()
            return self.response()


def flower_batch_frame(view, seat, tiles, drawn):
    frame = copy.deepcopy(view)
    frame.pop("frames", None)
    event = {"kind":"flower_batch", "seat":seat, "tiles":list(tiles), "drawn_count":len(drawn)}
    if seat == view["seat"]:
        event["drawn_tiles"] = list(drawn)
    frame["presentation"] = event
    frame["legal_actions"] = []
    frame["can_advance"] = frame["awaiting_human"] = False
    return frame


def presentation_frames(before, after):
    """Redacted presentation states within ONE atomic rules action.

    A kong/call and its replacement are atomic in Table. Reconstruct only the
    public pre-replacement display, never sample or reveal hidden hand contents.
    These display states cannot be submitted to the referee as game states.
    """
    events = after["events"][len(before["events"]):]
    if not events:
        return []
    frames = []
    first = events[0]
    kind = first["kind"]
    if kind in ("flower_kong", "an_gang", "add_gang", "chi", "peng", "ming_gang"):
        frame = copy.deepcopy(before)
        seat = first["seat"]
        player = frame["players"][seat]
        own = seat == frame["seat"]
        tile = first.get("tile")
        frame["actor"], frame["stage"], frame["pending"] = seat, "turn", None
        frame["self"]["drawn_tile"] = None
        frame["self"]["draw_source"] = "claim" if own else None
        needed = []
        if kind == "flower_kong":
            needed = [tile]
            player["flowers"].append(tile)
        elif kind == "an_gang":
            needed = [tile] * 4
            player["melds"].append({"type": kind, "size": 4,
                                    "tiles": [tile]*4 if own else None, "hidden": not own})
        elif kind == "add_gang":
            needed = [tile]
            meld = next(m for m in player["melds"] if m["type"] == "peng" and m["tiles"][0] == tile)
            meld.update(type="ming_gang", size=4, tiles=[tile]*4)
        else:
            source = first["source"]
            claimed = before["pending"]["tile"]
            frame["players"][source]["river"].pop()
            needed = list(first["tiles"])
            needed.remove(claimed)
            player["melds"].append({"type": kind, "size": len(first["tiles"]),
                                    "tiles": first["tiles"], "hidden": False})
        player["hand_count"] -= len(needed)
        if own:
            for t in needed:
                frame["self"]["hand"].remove(t)
            frame["self"]["held_flower_count"] = sum(parse_tile(t).is_flower for t in frame["self"]["hand"])
        flowers = [parse_tile(t) for t in player["flowers"]]
        player["public_flower_hua"] = flower_hua(konged_flowers=flowers, flower_kong_groups=[[t] for t in flowers])
        frame["events"].append(first)
        frame["presentation"] = first
        frames.append(frame)
    if events[-1]["kind"] == "end" and after["result"]["winners"]:
        announce = copy.deepcopy(frames[-1] if frames else before)
        announce["presentation"] = {"kind": "win", "seat": after["result"]["winners"][0],
                                    "tile": after["result"]["tile"], "winners": after["result"]["winners"]}
        frames.append(announce)
    final = copy.deepcopy(after)
    final["presentation"] = events[-1]
    # A non-kong call has no replacement; avoid rendering the same call twice.
    if kind in ("chi", "peng") and len(events) == 1:
        frames = []
    frames.append(final)
    for frame in frames:
        frame["legal_actions"] = []
        frame["can_advance"] = frame["awaiting_human"] = False
    return frames


def make_handler(desktop):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        def log_message(self, *args):
            pass

        def _send(self, status, data, content_type="application/json; charset=utf-8"):
            body = json.dumps(data, ensure_ascii=False).encode() if isinstance(data, dict) else data
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self'; style-src 'self'; script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _local(self):
            host = self.headers.get("Host", "")
            return host in {f"127.0.0.1:{self.server.server_port}", f"localhost:{self.server.server_port}"}

        def do_GET(self):
            if not self._local():
                return self._send(403, {"error": "仅允许本机访问"})
            path = unquote(urlsplit(self.path).path)
            if path == "/api/state":
                return self._send(200, desktop.view())
            target = (ASSETS / ("index.html" if path == "/" else path.lstrip("/"))).resolve()
            if not target.is_relative_to(ASSETS.resolve()) or not target.is_file():
                return self._send(404, {"error": "资源不存在"})
            return self._send(200, target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream")

        def do_POST(self):
            origin = self.headers.get("Origin")
            if (not self._local() or (origin and origin != "http://" + self.headers.get("Host", ""))
                    or self.headers.get("Content-Type", "").split(";")[0] != "application/json"):
                return self._send(403, {"error": "拒绝跨站或非JSON操作"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= 10000:
                    raise ValueError("请求大小不合法")
                data = json.loads(self.rfile.read(length))
                if not isinstance(data, dict):
                    raise ValueError("请求须为JSON对象")
                path = urlsplit(self.path).path
                if path == "/api/action":
                    result = desktop.action(data.get("version"), data.get("action_id"))
                elif path == "/api/step":
                    result = desktop.step(data.get("version"))
                elif path == "/api/retry":
                    result = desktop.retry_bots(data.get("version"))
                elif path == "/api/coach":
                    result = desktop.request_coach(data.get("version"), data.get("mode", "current"))
                elif path == "/api/strategy":
                    result = desktop.request_strategy(data.get("version"))
                elif path == "/api/coach/settings":
                    result = desktop.coach_settings(data.get("version"), data.get("enabled"), data.get("limit"))
                elif path == "/api/flowers":
                    result = desktop.exchange_flowers(data.get("version"), data.get("tiles"))
                elif path == "/api/new":
                    result = desktop.new_game(data.get("version"), data.get("seed"), data.get("dealer", 0))
                elif path == "/api/save":
                    with desktop.lock:
                        desktop._require_version(data.get("version"))
                        desktop.checkpoint()
                        result = desktop.view()
                else:
                    return self._send(404, {"error": "接口不存在"})
                self._send(200, result)
            except (ValueError, TypeError, DecisionError) as exc:
                self._send(400, {"error": str(exc)})
    return Handler


class DesktopHTTPServer(ThreadingHTTPServer):
    # A cold table loads many distinct SVGs alongside CSS, audio and /api/state.
    # The default five-connection backlog causes resets and long browser retries.
    request_queue_size = 128
    daemon_threads = True


def main():
    parser = argparse.ArgumentParser(description="电脑网页四人测试桌（与旧录入服务独立）")
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--dealer", type=int, choices=range(4), default=0)
    parser.add_argument("--human-seat", type=int, choices=range(4), default=0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--output-dir", type=Path, default=Path("runs/mahjong"))
    parser.add_argument("--bot", choices=("heuristic", "llm"), default="heuristic")
    parser.add_argument("--llm-provider", choices=("anthropic", "deepseek"), help="LLM供应商，也可设置MAHJONG_BOT_PROVIDER")
    parser.add_argument("--fallback", choices=("pause", "heuristic"), default="pause")
    parser.add_argument("--llm-max-calls", type=int, default=100, help="每个机器人本次服务进程的API调用上限（含重试）")
    parser.add_argument("--coach-max-calls", type=int, default=20, help="教练每局API调用上限（1至50，默认20）")
    parser.add_argument("--coach-manual", action="store_true", help="关闭常驻教练，仅手动请求")
    args = parser.parse_args()
    if args.llm_max_calls < 1:
        parser.error("调用上限必须大于0")
    if not 1 <= args.coach_max_calls <= 50:
        parser.error("教练每局调用上限须为1至50")
    bots = None
    if args.bot == "llm":
        from ..players.llm import LLMPlayer, FallbackPlayer
        try:
            bots = {}
            for seat in range(4):
                if seat == args.human_seat:
                    continue
                bot = LLMPlayer(max_calls=args.llm_max_calls, provider=args.llm_provider)
                bots[seat] = FallbackPlayer(bot, HeuristicPlayer()) if args.fallback == "heuristic" else bot
        except (ValueError, ImportError) as exc:
            parser.error(str(exc))
    table = replay(json.loads(args.resume.read_text())) if args.resume else Table(
        args.seed if args.seed is not None else random.SystemRandom().randrange(2**53), args.dealer)
    desktop = DesktopTable(table, args.human_seat, args.output_dir, paced=True, bots=bots, background=True,
                           auto_coach=not args.coach_manual, coach_limit=args.coach_max_calls,
                           defer_bots=bool(args.resume and args.bot == "llm"))
    server = DesktopHTTPServer(("127.0.0.1", args.port), make_handler(desktop))
    description = "三个LLM机器人，产生API费用" if args.bot == "llm" else "三个基础机器人，无LLM费用"
    print(f"电脑牌桌：http://127.0.0.1:{server.server_port}/ （{description}）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        print(f"私有续局牌谱：{desktop.checkpoint()}", flush=True)
        server.server_close()


if __name__ == "__main__":
    main()
