"""Local web UI for the mahjong advisor.

Run with:
    python -m src.web            # http://127.0.0.1:8765
    python -m src.web 9000       # custom port

Stdlib-only backend (no extra dependencies): serves the single-page
frontend in src/webapp/ and a small JSON API that reuses the session
layer (parse_event/apply_event) and the analysis/advice layers.
"""
import copy
import json
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from .core.tiles import GameState, Tile, parse_tile
from .llm.advisor import analyze, build_prompt, get_advice
from .session import apply_event, parse_event

_INDEX = Path(__file__).parent / "webapp" / "index.html"

# single-user local tool: one game + undo history in memory
_GAME = {"state": None, "history": []}


# --- serialization helpers ---------------------------------------------------
def _tiles(tiles):
    return [str(t) for t in tiles]


def _melds(melds):
    return [{"type": m.type, "tiles": _tiles(m.tiles)} for m in melds]


def state_json(state: GameState) -> dict:
    return {
        "hand": _tiles(state.my_hand),
        "my_melds": _melds(state.my_melds),
        "my_discards": _tiles(state.my_discards),
        "flowers": _tiles(state.flowers_in_hand),
        "konged_flowers": _tiles(state.konged_flowers),
        "players": {
            key: {
                "discards": _tiles(state.discards[key]),
                "melds": _melds(state.melds[key]),
            }
            for key in ("left", "right", "opposite")
        },
    }


def analysis_json(state: GameState) -> dict:
    a = analyze(state)
    return {
        "shanten": a.shanten,
        "is_tenpai": a.is_tenpai,
        "waiting": _tiles(a.waiting),
        "ukeire": _tiles(a.ukeire),
        "remaining_total": a.remaining_total,
        "candidates": [
            {
                "tile": str(tile),
                "shanten_after": after,
                "speed_types": a.discard_speed[tile]["types"],
                "speed_tiles": a.discard_speed[tile]["tiles"],
                "risk": a.risks[tile],
                "chi": a.risk_estimates[tile]["chi"],
                "peng": a.risk_estimates[tile]["peng"],
                "ron": a.risk_estimates[tile]["ron"],
                "remaining": a.remaining.get(tile, 0),
            }
            for tile, after in a.discards_ranked[:8]
        ],
        "kong_opportunities": [
            {"kind": op["kind"], "tile": str(op["tile"]),
             "hua": op["hua"], "note": op["note"]}
            for op in a.kong_opportunities
        ],
    }


# --- game operations ---------------------------------------------------------
def op_new(hand_line: str, flowers_line: str) -> dict:
    hand = [parse_tile(t) for t in hand_line.split() if t] if hand_line else []
    flowers = [parse_tile(t) for t in flowers_line.split() if t] if flowers_line else []
    state = GameState(my_hand=hand, flowers_in_hand=flowers)
    _GAME["state"] = state
    _GAME["history"] = [copy.deepcopy(state)]
    return {"ok": True}


def op_event(line: str) -> dict:
    if _GAME["state"] is None:
        return {"ok": False, "error": "还没有开始对局"}
    try:
        event = parse_event(line)
    except ValueError as e:
        return {"ok": False, "error": str(e)}
    if event is None:
        return {"ok": False, "error": "空输入"}

    if event.kind == "undo":
        if len(_GAME["history"]) > 1:
            _GAME["history"].pop()
            _GAME["state"] = copy.deepcopy(_GAME["history"][-1])
            return {"ok": True, "undid": True}
        return {"ok": False, "error": "没有可撤销的事件"}

    if event.kind == "quit":
        return {"ok": False, "error": "网页模式不用 q，直接关页面即可"}

    try:
        apply_event(_GAME["state"], event)
    except ValueError as e:
        return {"ok": False, "error": str(e)}

    _GAME["history"].append(copy.deepcopy(_GAME["state"]))
    return {"ok": True}


def op_advice() -> dict:
    state = _GAME["state"]
    if state is None:
        return {"ok": False, "error": "还没有开始对局"}
    bundle = analyze(state)
    try:
        return {"ok": True, "advice": get_advice(state, bundle)}
    except Exception as e:  # noqa: BLE001 - offline/no-key fallback, same as CLI
        return {"ok": False, "error": str(e), "prompt": build_prompt(state, bundle)}


# --- HTTP --------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):   # keep the console quiet
        pass

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, payload: dict, code: int = 200):
        self._send(code, json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                   "application/json; charset=utf-8")

    def do_GET(self):
        if self.path.startswith("/api/state"):
            if _GAME["state"] is None:
                self._json({"ok": False, "error": "还没有开始对局"})
            else:
                self._json({"ok": True,
                            "state": state_json(_GAME["state"]),
                            "analysis": analysis_json(_GAME["state"])})
            return
        self._send(200, _INDEX.read_bytes(), "text/html; charset=utf-8")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        try:
            data = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            self._json({"ok": False, "error": "请求体不是合法 JSON"}, 400)
            return

        if self.path == "/api/new":
            self._json(op_new(data.get("hand", ""), data.get("flowers", "")))
        elif self.path == "/api/event":
            self._json(op_event(data.get("line", "")))
        elif self.path == "/api/advice":
            self._json(op_advice())
        else:
            self._json({"ok": False, "error": f"未知接口 {self.path}"}, 404)


def run(host: str = "127.0.0.1", port: int = 8765) -> None:
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"麻将策略助手 Web 界面：http://{host}:{port}  （Ctrl+C 退出）")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    run(port=int(sys.argv[1]) if len(sys.argv) > 1 else 8765)
