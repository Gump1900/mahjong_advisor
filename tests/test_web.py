"""Web API tests: spin the stdlib server on a random local port."""
import json
import threading
import urllib.request

import pytest

from src.web import Handler, op_new, op_event, op_advice, run  # noqa: F401


@pytest.fixture(scope="module")
def server():
    import http.server
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def call(base, path, body=None):
    if body is None:
        resp = urllib.request.urlopen(base + path)
    else:
        req = urllib.request.Request(
            base + path, data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"})
        resp = urllib.request.urlopen(req)
    return json.loads(resp.read())


class TestWebAPI:
    def test_index_served(self, server):
        html = urllib.request.urlopen(server + "/").read().decode()
        assert "麻将策略助手" in html
        assert "askLLM" not in html and "问 LLM" in html

    def test_state_before_new(self, server):
        # module-level game may exist from other tests; start fresh
        call(server, "/api/new", {"hand": "", "flowers": ""})
        d = call(server, "/api/state")
        assert d["ok"] is True
        assert d["state"]["hand"] == []
        assert d["analysis"]["shanten"] >= 0

    def test_full_flow(self, server):
        d = call(server, "/api/new", {
            "hand": "2万 3万 4万 5万 6万 6万 6万 1饼 1饼 1饼 2条 2条 2条",
            "flowers": "中",
        })
        assert d["ok"] is True

        d = call(server, "/api/event", {"line": "摸 2万"})
        assert d["ok"] is True
        d = call(server, "/api/state")
        assert len(d["state"]["hand"]) == 14
        assert d["state"]["flowers"] == ["中"]
        assert d["analysis"]["shanten"] == -1          # 完全体：已胡

        d = call(server, "/api/event", {"line": "l 9条"})
        assert d["ok"] is True
        d = call(server, "/api/event", {"line": "r碰 9条"})
        assert d["ok"] is True
        d = call(server, "/api/state")
        assert d["state"]["players"]["left"]["discards"] == []
        assert d["state"]["players"]["right"]["melds"][0]["type"] == "peng"

        d = call(server, "/api/event", {"line": "打 1饼"})
        assert d["ok"] is True
        d = call(server, "/api/event", {"line": "撤"})
        assert d["ok"] is True and d.get("undid") is True
        d = call(server, "/api/state")
        assert len(d["state"]["hand"]) == 14           # discard undone

    def test_invalid_event(self, server):
        d = call(server, "/api/event", {"line": "乱写"})
        assert d["ok"] is False and "无法识别" in d["error"]

    def test_advice_either_live_or_fallback(self, server):
        # 有凭证/网络 -> ok=True 且有建议文本；否则 ok=False + prompt 预览
        d = call(server, "/api/advice", {})
        if d["ok"]:
            assert isinstance(d["advice"], str) and d["advice"].strip()
        else:
            assert "prompt" in d and "向听数" in d["prompt"]
