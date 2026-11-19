"""Web API tests: spin the stdlib server on a random local port."""
import json
import threading
import urllib.request

import pytest

from src.web import (  # noqa: F401
    Handler,
    _GAME,
    op_advice,
    op_event,
    op_claims,
    op_legal,
    op_new,
    op_score,
    run,
)

BASE = "1万 2万 3万 1饼 2饼 3饼 1条 2条 3条 南风 南风 南风 西风"


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
        call(server, "/api/new", {"hand": BASE, "flowers": ""})
        d = call(server, "/api/state")
        assert d["ok"] is True
        assert len(d["state"]["hand"]) == 13
        assert d["flow"]["phase"] == "need_draw"
        assert "remaining_by_tile" in d["flow"]
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

    def test_decision_endpoint_and_version_binding(self, server):
        call(server, "/api/new", {"hand": BASE, "flowers": ""})
        call(server, "/api/event", {"line": "摸 北风"})
        state = call(server, "/api/state")
        version = {k: state["flow"][k] for k in ("game_id", "revision")}
        result = call(server, "/api/decision", {**version, "samples": 8})
        assert result["ok"]
        assert result["decision"]["samples"] == 8
        assert result["decision"]["scope"] == "immediate_discard_only"
        assert not result["decision"]["calibrated"]
        call(server, "/api/event", {"line": "撤"})
        assert call(server, "/api/decision", {**version, "samples": 8})["stale"]
        assert not call(server, "/api/decision", {"samples": "bad"})["ok"]

    def test_advice_either_live_or_fallback(self, server):
        # 有凭证/网络 -> ok=True 且有建议文本；否则 ok=False + prompt 预览
        d = call(server, "/api/advice", {})
        if d["ok"]:
            assert isinstance(d["advice"], str) and d["advice"].strip()
        else:
            assert "prompt" in d and "向听数" in d["prompt"]


class TestWebOperationsWithoutSocket:

    def test_pending_discard_requires_explicit_pass_before_draw_or_flower_kong(self):
        assert op_new(BASE, "中")["ok"]
        assert op_event("l 9条")["ok"]
        pending = dict(_GAME["session"].pending)
        assert not op_event("摸 9万")["ok"]
        assert not op_event("kg 中")["ok"]
        assert _GAME["session"].pending == pending
        legal = op_legal()
        assert legal["pending"]["id"] == pending["id"]
        assert not legal["peng"] and not legal["ron"] and not legal["chi"]
        assert op_event("过", pending["id"])["ok"]
        assert op_event("摸 9万")["ok"]
    def test_no_flower_ron_is_hidden_but_self_draw_scores_six_each(self):
        hand = "1万 2万 3万 4万 5万 6万 7饼 8饼 9饼 1条 2条 3条 9条"
        assert op_new(hand, "")["ok"]
        assert op_event("l 9条")["ok"]
        assert op_legal()["ron"] is False
        assert not op_event("胡 放炮")["ok"]
        assert op_event("过")["ok"]
        assert op_event("摸 9条")["ok"]
        assert op_event("胡 自摸")["ok"]
        result = op_score()
        assert result["hua"] == 6
        assert result["settlement"] == {"me": 18, "left": -6, "opposite": -6, "right": -6}

    def test_batch_claims_dont_publish_a_partial_multi_ron_as_complete_settlement(self):
        assert op_new(BASE, "")["ok"]
        assert op_event("l 西风")["ok"]
        pending_id = _GAME["session"].pending["id"]
        assert op_claims(["r胡", "胡 放炮"], pending_id)["ok"]
        result = op_score()
        assert result["ok"] and not result["settlement_complete"]
        assert result["settlement"] is None
        assert result["settlement_missing_players"] == ["right"]

    def test_draw_returns_zero_not_kong_income(self):
        assert op_new(BASE, "中 中 中 中")["ok"]
        assert op_event("kg 中 4")["ok"]
        assert op_event("黄庄")["ok"]
        result = op_score()
        assert result["hua"] == 0
        assert set(result["settlement"].values()) == {0}

    def test_legal_is_derived_from_server_pending(self):
        assert op_new(BASE, "")["ok"]
        assert op_event("l 西风")["ok"]
        legal = op_legal()
        assert legal["ok"] and legal["ron"] is True
        assert legal["pending"]["player"] == "left"
        assert legal["pending"]["tile"] == "西风"

    def test_own_discard_never_offers_self_claim(self):
        assert op_new(BASE, "")["ok"]
        assert op_event("摸 9万")["ok"]
        assert op_event("打 9万")["ok"]
        assert op_legal() == {
            "ok": True, "pending": None, "peng": False, "chi": [], "ron": False,
        }

    def test_score_requires_confirmed_win_and_adds_ron_tile(self):
        assert op_new(BASE, "")["ok"]
        assert op_score()["ok"] is False
        assert op_event("l 西风")["ok"]
        pending_id = _GAME["session"].pending["id"]
        assert op_event("胡 放炮", pending_id)["ok"]
        result = op_score()
        assert result["ok"] is True
        assert result["hua"] >= 2
        assert result["breakdown"][0] == "放炮 2花"


class TestOpEv:
    def test_requires_session(self):
        from src.web import op_ev_advice, _GAME
        _GAME["session"] = None
        d = op_ev_advice(128, 0)
        assert d["ok"] is False

    def test_returns_candidates_and_opponents(self):
        from src.web import op_ev_advice, op_new, _GAME
        op_new(BASE, "")
        d = op_ev_advice(32, 0)
        assert d["ok"] is True
        assert isinstance(d["candidates"], list) and d["candidates"]
        first = d["candidates"][0]
        for key in ("tile", "ev", "p_point", "p_lo", "p_hi", "v_deal", "labels"):
            assert key in first
        assert set(d["opponents"]) == {"left", "opposite", "right"}
        for seat in d["opponents"].values():
            assert 0.0 <= seat["tenpai_prior"] <= 1.0
            assert isinstance(seat["wait_top"], list)
        assert d["receipt_path"].endswith(".jsonl")

    def test_rejects_bad_samples(self):
        from src.web import op_ev_advice, op_new
        op_new(BASE, "")
        assert op_ev_advice(0, 0)["ok"] is False
        assert op_ev_advice(True, 0)["ok"] is False

    def test_stale_guard(self):
        from src.web import op_ev_advice, op_new
        op_new(BASE, "")
        d = op_ev_advice(8, 0, game_id="wrong-id")
        assert d["ok"] is False

    def test_http_endpoint(self, server):
        call(server, "/api/new", {"hand": BASE, "flowers": ""})
        d = call(server, "/api/ev", {"samples": 8, "seed": 0})
        assert d["ok"] is True
        assert d["candidates"]


class TestOpEvStalenessAndDedupe:
    def test_stale_if_revision_advances_during_compute(self, monkeypatch):
        import src.web as web
        from src.web import op_ev_advice
        web._GAME["session"] = None
        op_new(BASE, "")
        session = web._GAME["session"]
        captured = {}

        def slow_rank(state, *, samples=128, seed=0):
            captured["result"] = session.apply("摸 9饼")   # 计算期间局面前进
            from src.decision.ev import rank_candidates
            return rank_candidates(state, samples=samples, seed=seed)

        monkeypatch.setattr(web, "rank_candidates", slow_rank)
        d = op_ev_advice(8, 0)
        assert captured["result"]["ok"] is True
        assert d["ok"] is False and d.get("stale") is True

    def test_receipt_dedupes_same_revision(self):
        from src.web import op_ev_advice
        from src.decision.receipts import load_receipts
        op_new(BASE, "")
        first = op_ev_advice(8, 0)
        second = op_ev_advice(8, 0)
        assert first["ok"] and second["ok"]
        lines = load_receipts(first["game_id"])
        assert len([r for r in lines if r["revision"] == first["revision"]]) == 1
