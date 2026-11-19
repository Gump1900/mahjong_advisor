from pathlib import Path

from src.simulation.engine import Table
from src.simulation.web import DesktopHTTPServer, DesktopTable, make_handler


def test_resumed_bot_game_can_start_without_paid_calls(tmp_path):
    class NeverCall:
        def choose(self, obs):
            raise AssertionError("must not call a bot during deferred startup")

    d = DesktopTable(Table(42, dealer=1), output_dir=tmp_path, paced=True,
                     bots={i: NeverCall() for i in (1, 2, 3)}, defer_bots=True)
    v = d.view()
    assert v["bot_error"] and not v["can_advance"]
    assert len(v["self"]["hand"]) == 13


def test_cold_load_server_uses_keepalive_and_large_backlog():
    assert DesktopHTTPServer.request_queue_size >= 64
    assert make_handler(None).protocol_version == "HTTP/1.1"


def test_new_dialog_is_available_before_initial_state():
    js = (Path(__file__).parents[1] / "src/simulation/webapp/table.js").read_text()
    dialog = js.split("function newDialog()", 1)[1].split('$("new").onclick', 1)[0]
    assert "!state" not in dialog
    assert 'state?.dealer ?? 0' in dialog
    assert "AbortController" in js
    assert 'if (!live)' in js and '连接失败 · 点击新的一局重试' in js
