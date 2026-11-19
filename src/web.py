"""Stdlib-only local web UI for the mahjong advisor."""

import copy
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core.hand_analyzer import can_chi, can_peng
from .core.probability import count_remaining_tiles
from .core.scoring import known_hua, score_hand
from .core.round_rules import can_win_on_discard, settle_round
from .core.tiles import GameState
from .decision.service import analyze
from .decision.ev import opponent_panel, rank_candidates
from .decision.receipts import DEFAULT_ROOT as RECEIPT_ROOT, _candidate_to_dict, load_receipts, save_receipt
from .decision.risk import evaluate_immediate_risk
from .llm.advisor import build_prompt, get_advice
from .session import PHASE_DRAWN, PHASE_NEED_DRAW, GameSession, new_session

_INDEX = Path(__file__).parent / "webapp" / "index.html"
_GAME = {"session": None}
_LOCK = threading.RLock()
_DECISION_SLOT = threading.BoundedSemaphore(1)
_DECISION_CACHE = {}  # One result only; never cache across game/revision.


def _tiles(tiles):
    return [str(tile) for tile in tiles]


def _melds(melds):
    return [{"type": meld.type, "tiles": _tiles(meld.tiles)} for meld in melds]


def state_json(state: GameState) -> dict:
    return {
        "hand": _tiles(state.my_hand),
        "my_melds": _melds(state.my_melds),
        "my_discards": _tiles(state.my_discards),
        "flowers": _tiles(state.flowers_in_hand),
        "konged_flowers": _tiles(state.konged_flowers),
        "flower_kong_groups": [_tiles(group) for group in state.flower_kong_groups],
        "players": {
            key: {"discards": _tiles(state.discards[key]), "melds": _melds(state.melds[key]),
                  "flowers": _tiles(state.opponent_flowers[key]),
                  "konged_flowers": _tiles(state.opponent_konged_flowers[key]),
                  "flower_kong_groups": [_tiles(group) for group in state.opponent_flower_kong_groups[key]],
                  "known_hua": known_hua(state.melds[key], state.opponent_flowers[key],
                                          state.opponent_konged_flowers[key],
                                          state.opponent_flower_kong_groups[key]),
                  "flowers_complete": state.opponent_flowers_complete[key]}
            for key in ("left", "opposite", "right")
        },
    }


def analysis_json(state: GameState) -> dict:
    bundle = analyze(state)
    return {
        "shanten": bundle.shanten,
        "is_tenpai": bundle.is_tenpai,
        "waiting": _tiles(bundle.waiting),
        "ukeire": _tiles(bundle.ukeire),
        "remaining_total": bundle.remaining_total,
        "candidates": [
            {
                "tile": str(tile), "shanten_after": after,
                "speed_types": bundle.discard_speed[tile]["types"],
                "speed_tiles": bundle.discard_speed[tile]["tiles"],
                "risk": bundle.risks[tile],
                "chi": bundle.risk_estimates[tile]["chi"],
                "peng": bundle.risk_estimates[tile]["peng"],
                "ron": bundle.risk_estimates[tile]["ron"],
                "remaining": bundle.remaining.get(tile, 0),
            }
            for tile, after in bundle.discards_ranked[:8]
        ],
        "kong_opportunities": [
            {"kind": item["kind"], "tile": str(item["tile"]),
             "hua": item["hua"], "note": item["note"], "count": item.get("count", 1),
             **{key: item[key] for key in ("hua_basis", "delta_hua", "flower_hua_before", "flower_hua_after")
                if key in item}}
            for item in bundle.kong_opportunities
        ],
    }


def flow_json(session: GameSession) -> dict:
    pending = None
    if session.pending:
        pending = {**session.pending, "tile": str(session.pending["tile"])}
    win = None
    if session.win:
        win = {**session.win, "tile": str(session.win["tile"])}
    remaining = count_remaining_tiles(session.state)
    return {
        "game_id": session.game_id,
        "revision": session.revision,
        "phase": session.phase,
        "drawn_tile": str(session.drawn_tile) if session.drawn_tile else None,
        "pending": pending,
        "win": win,
        "winners": [{**winner, "tile": str(winner["tile"])} for winner in session.winners],
        "replacement_draw_pending": session.replacement_draw_pending,
        "last_draw_was_replacement": session.last_draw_was_replacement,
        "remaining_by_tile": {str(tile): count for tile, count in remaining.items()},
    }


def op_new(hand_line: str, flowers_line: str) -> dict:
    try:
        session = new_session(hand_line, flowers_line)
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    with _LOCK:
        _GAME["session"] = session
    return {"ok": True}


def op_event(line: str, expected_pending_id=None) -> dict:
    with _LOCK:
        session = _GAME["session"]
        if session is None:
            return {"ok": False, "error": "还没有开始对局"}
        return session.apply(line, expected_pending_id=expected_pending_id)


def op_legal() -> dict:
    with _LOCK:
        session = _GAME["session"]
        if session is None:
            return {"ok": False, "error": "还没有开始对局"}
        pending = session.pending
        empty = {"ok": True, "pending": None, "peng": False, "chi": [], "ron": False}
        if (pending is None or pending["player"] == "me"
                or session.phase != PHASE_NEED_DRAW
                or len(session.state.my_hand) != session.base()):
            return empty
        tile = pending["tile"]
        encoded_pending = {**pending, "tile": str(tile)}
        chi = can_chi(session.state.my_hand, tile) if pending["player"] == "left" else []
        return {
            "ok": True,
            "pending": encoded_pending,
            "peng": can_peng(session.state.my_hand, tile),
            "gang": not tile.is_flower and session.state.my_hand.count(tile) == 3,
            "chi": [_tiles(pair) for pair in chi],
            "ron": can_win_on_discard(session.state.my_hand, tile, session.state.my_melds,
                                       session.state.flowers_in_hand, session.state.konged_flowers,
                                       session.state.flower_kong_groups),
        }


def op_claims(lines: list[str], expected_pending_id) -> dict:
    with _LOCK:
        session = _GAME["session"]
        if session is None:
            return {"ok": False, "error": "还没有开始对局"}
        if (not isinstance(lines, list) or not all(isinstance(line, str) for line in lines)
                or not isinstance(expected_pending_id, int) or isinstance(expected_pending_id, bool)):
            return {"ok": False, "error": "请提供响应命令列表及待响应弃牌ID"}
        return session.apply_claims(lines, expected_pending_id=expected_pending_id)


def op_score() -> dict:
    with _LOCK:
        session = _GAME["session"]
        if session is not None and session.phase == PHASE_DRAWN:
            return {"ok": True, "hua": 0, "flowers": 0,
                    "breakdown": ["黄庄：全部零结算，杠分不支付"],
                    "settlement": settle_round("draw", {}).net}
        if session is None or session.win is None:
            return {"ok": False, "error": "只有确认胡牌后才能算花"}
        hand = list(session.state.my_hand)
        if session.win["method"] == "dianpao":
            hand.append(session.win["tile"])
        result = score_hand(
            hand, session.state.my_melds, session.state.flowers_in_hand,
            session.state.konged_flowers, session.win["method"],
            flower_kong_groups=session.state.flower_kong_groups,
        )
        missing = [winner["player"] for winner in session.winners if winner["player"] != "me"]
        return {"ok": True, "hua": result.hua, "flowers": result.flowers,
                "breakdown": result.breakdown,
                "qualifying_hua": result.qualifying_hua, "pattern_hua": result.pattern_hua,
                "settlement": None if missing else settle_round(
                    session.win["method"], {"me": result.hua}, session.win["source"]).net,
                "settlement_complete": not missing, "settlement_missing_players": missing}


def op_ev_advice(samples=128, seed=0, *, game_id=None, revision=None,
                 save=True) -> dict:
    """EV 军师：候选 EV 排序 + 对手先验面板 + receipt 落盘（可回查）。"""
    if (isinstance(samples, bool) or not isinstance(samples, int)
            or not 1 <= samples <= 2048 or isinstance(seed, bool)
            or not isinstance(seed, int)):
        return {"ok": False, "error": "抽样次数须为1到2048的整数，种子须为整数"}
    with _LOCK:
        session = _GAME["session"]
        if session is None:
            return {"ok": False, "error": "还没有开始对局"}
        if ((game_id is not None and game_id != session.game_id)
                or (revision is not None and revision != session.revision)):
            return {"ok": False, "stale": True, "error": "局面已更新，请重新分析"}
        state = copy.deepcopy(session.state)
        gid, rev = session.game_id, session.revision
    if not _DECISION_SLOT.acquire(blocking=False):
        return {"ok": False, "error": "正在计算其他分析，请稍后重试"}
    try:
        ranked = rank_candidates(state, samples=samples, seed=seed)
        panel = opponent_panel(state, samples=samples, seed=seed)
        with _LOCK:   # 计算期间局面前进 => stale（与 /api/decision 同构）
            live = _GAME["session"]
            if live is None or (live.game_id, live.revision) != (gid, rev):
                return {"ok": False, "stale": True, "error": "计算期间局面已更新，请重新分析"}
        receipt_path = None
        if save:
            receipt_path = f"{RECEIPT_ROOT}/{gid}.jsonl"
            if not any(r["revision"] == rev for r in load_receipts(gid)):
                receipt_path = save_receipt(gid, rev, ranked)
        return {
            "ok": True, "game_id": gid, "revision": rev,
            "candidates": [_candidate_to_dict(c) for c in ranked],
            "opponents": panel,
            "receipt_path": receipt_path,
        }
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        _DECISION_SLOT.release()


def op_advice() -> dict:
    with _LOCK:
        session = _GAME["session"]
        if session is None:
            return {"ok": False, "error": "还没有开始对局"}
        state = copy.deepcopy(session.state)
        bundle = analyze(state)
    try:
        return {"ok": True, "advice": get_advice(state, bundle)}
    except Exception as exc:  # noqa: BLE001 - intentional offline fallback
        return {"ok": False, "error": str(exc), "prompt": build_prompt(state, bundle)}


def op_decision(samples=256, seed=0, *, game_id=None, revision=None) -> dict:
    """Bounded on-demand analysis, without holding the recording lock."""
    if (isinstance(samples, bool) or not isinstance(samples, int)
            or not 1 <= samples <= 2048 or isinstance(seed, bool) or not isinstance(seed, int)):
        return {"ok": False, "error": "抽样次数须为1到2048的整数，种子须为整数"}
    with _LOCK:
        session = _GAME["session"]
        if session is None:
            return {"ok": False, "error": "还没有开始对局"}
        if ((game_id is not None and game_id != session.game_id)
                or (revision is not None and revision != session.revision)):
            return {"ok": False, "stale": True, "error": "局面已更新，请重新分析"}
        context = session.decision_context()
        key = (context.game_id, context.revision, samples, seed)
        if _DECISION_CACHE.get("key") == key:
            return {"ok": True, "decision": _DECISION_CACHE["result"], "cached": True}
    if not _DECISION_SLOT.acquire(blocking=False):
        return {"ok": False, "error": "正在计算其他分析，请稍后重试"}
    try:
        result = evaluate_immediate_risk(context, samples=samples, seed=seed)
        with _LOCK:
            live = _GAME["session"]
            if live is None or (live.game_id, live.revision) != (context.game_id, context.revision):
                return {"ok": False, "stale": True, "error": "计算期间局面已更新，请重新分析"}
            _DECISION_CACHE.clear()
            _DECISION_CACHE.update(key=key, result=result)
        return {"ok": True, "decision": result, "cached": False}
    except ValueError as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        _DECISION_SLOT.release()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload, ensure_ascii=False).encode(),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path.startswith("/api/state"):
            with _LOCK:
                session = _GAME["session"]
                if session is None:
                    payload = {"ok": False, "error": "还没有开始对局"}
                    state = None
                else:
                    state = copy.deepcopy(session.state)
                    payload = {"ok": True, "state": state_json(state),
                               "flow": flow_json(session)}
            if state is not None:
                payload["analysis"] = analysis_json(state)
            self._json(payload)
            return
        if self.path.startswith("/api/legal"):
            self._json(op_legal())
            return
        self._send(200, _INDEX.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "请求体不是合法 JSON"}, 400)
            return
        if not isinstance(data, dict):
            self._json({"ok": False, "error": "请求体必须是 JSON 对象"}, 400)
            return
        if self.path == "/api/new":
            result = op_new(data.get("hand", ""), data.get("flowers", ""))
        elif self.path == "/api/event":
            result = op_event(data.get("line", ""), data.get("expected_pending_id"))
        elif self.path == "/api/score":
            result = op_score()
        elif self.path == "/api/claims":
            result = op_claims(data.get("lines"), data.get("expected_pending_id"))
        elif self.path == "/api/advice":
            result = op_advice()
        elif self.path == "/api/ev":
            result = op_ev_advice(data.get("samples", 128), data.get("seed", 0),
                                  game_id=data.get("game_id"),
                                  revision=data.get("revision"),
                                  save=data.get("save", True))
        elif self.path == "/api/decision":
            result = op_decision(data.get("samples", 256), data.get("seed", 0),
                                 game_id=data.get("game_id"), revision=data.get("revision"))
        else:
            self._json({"ok": False, "error": f"未知接口 {self.path}"}, 404)
            return
        self._json(result)


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"麻将策略助手 Web 界面：http://{host}:{port}  （Ctrl+C 退出）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
