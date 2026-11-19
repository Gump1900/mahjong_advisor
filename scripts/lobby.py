"""产品入口：大厅 → 房间 → 显式开局 → 牌桌（批次A，规划 §9.2 流程的最小实现）。

边界纪律（interface-baseline §7）：
- GET / 只发静态大厅页，不创建访客/房间/对局（边界验收①）
- 对局只能经 POST /rooms/<id>/start 显式创建，幂等（§9.4）
- 牌桌服复用 ev_table 全套注入（EVBot×3 + EVCoach + UI补丁），一局一服，同端口重建

用法：python3 -I scripts/lobby.py [--port 8765] [--table-port 8766]
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.simulation.engine import Table                     # noqa: E402
from src.simulation.web import (                           # noqa: E402
    DesktopHTTPServer, DesktopTable, make_handler,
)
from src.decision.ev_bot import EVBot                       # noqa: E402
from src.decision.ev_coach import EVCoach                    # noqa: E402
from src.webapp.table_ui_patch import (                     # noqa: E402
    make_patched_handler, wrap_desktop,
)
from src.rooms.service import RoomService                    # noqa: E402
from src.rooms.room import RoomError                         # noqa: E402

WEB = Path(__file__).with_name("..") / "src" / "rooms" / "web"
STATE_PATH = Path("runs/lobby/state.json")
BOT_SETUP = {1: "均衡", 2: "稳", 3: "凶"}


class LobbyApp:
    """大厅状态与牌桌服生命周期（一局一服，同端口重建）。"""

    def __init__(self, table_port: int):
        self.service = RoomService()
        if STATE_PATH.exists():
            try:
                self.service = RoomService.from_dict(
                    json.loads(STATE_PATH.read_text(encoding="utf-8")))
            except (ValueError, KeyError):
                pass                              # 状态损坏则从空开始
        self.table_port = table_port
        self.table_server = None
        self.table_room = None

    def persist(self):
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        STATE_PATH.write_text(json.dumps(self.service.to_dict(), ensure_ascii=False),
                              encoding="utf-8")

    def spin_table(self, room_id: str, seed: int, dealer: int) -> str:
        if self.table_server is not None and self.table_room == room_id:
            return self.table_url()               # 同局幂等
        self.stop_table()
        bots = {seat: EVBot(name, samples=32, seed=seat)
                for seat, name in BOT_SETUP.items() if seat != 0}
        desktop = DesktopTable(Table(seed, dealer), 0, "runs/lobby-table",
                               paced=True, bots=bots, background=True,
                               auto_coach=False)
        desktop.coach = EVCoach()
        desktop.coach_auto = True
        desktop.coach_suspended = False
        _orig = desktop._maybe_auto_coach
        def _free_auto_coach():
            desktop.coach_calls = 0
            return _orig()
        desktop._maybe_auto_coach = _free_auto_coach
        wrap_desktop(desktop)
        self.table_server = DesktopHTTPServer(
            ("127.0.0.1", self.table_port), make_patched_handler(make_handler(desktop)))
        import threading
        threading.Thread(target=self.table_server.serve_forever, daemon=True).start()
        self.table_room = room_id
        return self.table_url()

    def stop_table(self):
        if self.table_server is not None:
            self.table_server.shutdown()
            self.table_server.server_close()
            self.table_server = None
            self.table_room = None

    def table_url(self) -> str:
        return f"http://127.0.0.1:{self.table_port}/"


def make_lobby_handler(app: LobbyApp):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _send(self, status, data, ctype="application/json; charset=utf-8"):
            body = (json.dumps(data, ensure_ascii=False).encode()
                    if isinstance(data, dict) else data)
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; img-src 'self'; style-src 'self'; "
                             "script-src 'self'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(body)

        def _json(self):
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length) if 0 < length <= 10000 else b"{}"
            try:
                data = json.loads(raw or b"{}")
                return data if isinstance(data, dict) else {}
            except ValueError:
                return {}

        def _visitor(self):
            """从请求头取访客；GET /api/lobby/visitor 允许匿名新建。"""
            token = self.headers.get("X-Visitor-Token", "")
            if not token:
                return None, None
            try:
                return app.service.registry.resolve(token)["id"], token
            except KeyError:
                return None, None

        def do_GET(self):
            path = urlsplit(self.path).path
            if path in ("/", "/index.html", "/lobby.js", "/lobby.css"):
                name = {"": "lobby.html", "/": "lobby.html",
                        "/index.html": "lobby.html", "/lobby.js": "lobby.js",
                        "/lobby.css": "lobby.css"}[path]
                ctype = {"lobby.html": "text/html; charset=utf-8",
                         "lobby.js": "text/javascript; charset=utf-8",
                         "lobby.css": "text/css; charset=utf-8"}[name]
                return self._send(200, (WEB / name).read_bytes(), ctype)
            try:
                if path == "/api/lobby/visitor":
                    vid, token = self._visitor()
                    if vid:
                        return self._send(200, {"visitor": vid, "token": token,
                                                "nickname": app.service.registry.nickname(vid)})
                    return self._send(404, {"error": "访客凭证无效"})
                if path.startswith("/api/lobby/rooms/"):
                    room_id = path.rstrip("/").rsplit("/", 1)[-1]
                    return self._send(200, room_view(app, room_id))
            except RoomError as exc:
                return self._send(404, {"error": str(exc)})
            return self._send(404, {"error": "资源不存在"})

        def do_POST(self):
            path = urlsplit(self.path).path
            body = self._json()
            vid, _ = self._visitor()
            try:
                if path == "/api/lobby/visitor":
                    nickname = str(body.get("nickname", ""))[:12]
                    vid, token = app.service.registry.create(nickname)
                    app.persist()
                    return self._send(200, {"visitor": vid, "token": token,
                                            "nickname": app.service.registry.nickname(vid)})
                if not vid:
                    return self._send(403, {"error": "缺少有效访客凭证"})
                if path == "/api/lobby/rooms":
                    room = app.service.create_room(
                        visitor=vid,
                        nickname=app.service.registry.nickname(vid))
                    app.persist()
                    return self._send(200, {"room_id": room.room_id})
                room_id = path.split("/")[4] if len(path.split("/")) > 4 else ""
                room = app.service.room(room_id)
                if room.host_visitor != vid:
                    return self._send(403, {"error": "只有房主可以操作房间"})
                if path.endswith("/bots"):
                    app.service.fill_bots(room_id); app.persist()
                    return self._send(200, {"ok": True})
                if path.endswith("/ready"):
                    app.service.set_ready(room_id, vid, bool(body.get("ready", True)))
                    app.persist()
                    return self._send(200, {"ok": True})
                if path.endswith("/start"):
                    ref = app.service.start_hand(room_id)
                    url = app.spin_table(room_id, ref["seed"], ref["dealer"])
                    app.persist()
                    return self._send(200, {**ref, "table_url": url})
                if path.endswith("/leave"):
                    app.service.abort(room_id, reason="房主离开")
                    app.stop_table()
                    app.persist()
                    return self._send(200, {"ok": True})
            except RoomError as exc:
                return self._send(409, {"error": str(exc)})
            return self._send(404, {"error": "资源不存在"})

    return Handler


def room_view(app: LobbyApp, room_id: str) -> dict:
    room = app.service.room(room_id)
    view = room.to_dict()
    view["table_url"] = (app.table_url()
                         if app.table_room == room_id and room.state.value == "playing" else None)
    table = app.service.active_table(room_id)
    if table is not None and table.stage == "ended":
        view["table_result"] = getattr(table, "result", None)
        app.service.hand_finished(room_id,
                                  result=(table.result or {}).get("method", ""))
        app.persist()
        view.update({"state": "waiting", "table_url": None})
    return view


def main():
    parser = argparse.ArgumentParser(description="太湖麻将产品入口（大厅/房间/开局编排）")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--table-port", type=int, default=8766)
    args = parser.parse_args()
    app = LobbyApp(args.table_port)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_lobby_handler(app))
    print(f"大厅：http://127.0.0.1:{args.port}/ （牌桌将在 :{args.table_port}/ "
          f"显式开局后启动）", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.stop_table()
        app.persist()
        server.server_close()


if __name__ == "__main__":
    main()
