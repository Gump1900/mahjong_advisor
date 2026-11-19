"""EV 军师侧栏：轮询桌面牌桌（scripts/ev_table.py, 默认 8766），同步显示 EV 建议。

启动：python3 -I scripts/play_web.py [port=8799] [table=http://127.0.0.1:8766]
页面：http://127.0.0.1:8799/ —— 与牌桌页并排摆放；每 2 秒自动刷新。
"""
import json
import os
import sys
import threading
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)

from src.decision.ev import opponent_panel, rank_candidates      # noqa: E402
from src.decision.ev_bot import build_state_from_observation     # noqa: E402
from src.decision.receipts import load_receipts, save_receipt    # noqa: E402
from src.decision.replay_review import dual_review               # noqa: E402
from src.players.base import LABELS                              # noqa: E402

TABLE_STATE = None      # filled from argv
_LOCK = threading.Lock()
_SAVED = set()          # (game_id, version) receipts already stored


def table_get(path="/api/state"):
    url = TABLE_STATE + path
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())


def seat_truth_from_view(state):
    """终局 revealed_hands + players[].melds -> dual_review truth（相对人类座位）。"""
    human = state.get("seat", 0)
    names = {}
    for offset, name in ((1, "right"), (2, "opposite"), (3, "left")):
        names[(human + offset) % 4] = name
    revealed = state.get("revealed_hands") or []
    if not revealed:
        return None
    truth = {}
    for index, player in enumerate(state.get("players", [])):
        if index == human:
            continue
        truth[names[index]] = {"hand": revealed[index] if index < len(revealed) else [],
                               "melds": len(player.get("melds", []))}
    return truth or None


def advice_payload():
    state = table_get()
    payload = {"ok": True, "stage": state.get("stage"),
               "version": state.get("version"), "game_id": state.get("game_id"),
               "awaiting_human": state.get("awaiting_human"),
               "hand": state["self"]["hand"],
               "shanten": state["self"].get("structural_shanten"),
               "wall_count": state.get("wall_count"),
               "ron_blocked": state["self"].get("ron_blocked", False),
               "peng_blocked": state["self"].get("peng_blocked", []),
               "locked_with": state["self"].get("locked_with", []),
               "held_flower_count": state["self"].get("held_flower_count", 0),
               "bot_thinking": state.get("bot_thinking")}
    if state.get("stage") == "ended":
        receipts = load_receipts(payload["game_id"])
        truth = seat_truth_from_view(state)
        payload["review"] = dual_review(receipts, truth) if receipts else []
        payload["net"] = (state.get("result") or {}).get("net")
        return payload
    if not state.get("awaiting_human"):
        payload["waiting"] = True
        return payload
    if payload["held_flower_count"]:
        payload["advice_note"] = ("手牌含未换花（花占位）：先在牌桌页完成换花，"
                                  "EV 层暂只支持换花后的手牌")
        return payload
    try:
        obs_state = build_state_from_observation(state)
        ranked = rank_candidates(obs_state, samples=64, seed=0)
        panel = opponent_panel(obs_state, samples=64, seed=0)
        payload["advice"] = [{
            "tile": str(c.tile), "ev": round(c.ev, 3),
            "p_win": round(c.p_win_next, 3), "v_win": round(c.v_win, 1),
            "p_point": round(c.p_point, 3), "v_deal": round(c.v_deal, 1),
            "neff": round(c.exp_neff_1ply, 1), "labels": c.labels,
        } for c in ranked[:5]]
        payload["opponents"] = panel
        with _LOCK:
            key = (payload["game_id"], payload["version"])
            if key not in _SAVED:
                save_receipt(payload["game_id"], payload["version"], ranked)
                _SAVED.add(key)
    except ValueError as exc:
        payload["advice_note"] = f"EV 不可用：{exc}"
    return payload


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def _json(self, payload, code=200):
        body = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/api/advice"):
            try:
                self._json(advice_payload())
            except Exception as exc:                    # noqa: BLE001
                self._json({"ok": False, "error": str(exc)})
            return
        body = INDEX.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


INDEX = """<!doctype html>
<html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>EV 军师侧栏</title>
<style>
:root{--bg:#101613;--card:#18211c;--line:#2a3a31;--txt:#e8f0ea;--dim:#9db3a5;
--acc:#e0b34c;--red:#e07a5f;--green:#81b29a}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--txt);font:14px/1.6 -apple-system,"PingFang SC",sans-serif;padding:16px;max-width:520px;margin:auto}
h1{font-size:16px;margin-bottom:2px}.sub{color:var(--dim);font-size:12px;margin-bottom:12px}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:10px 12px;margin-bottom:10px}
.hand{font-size:18px;letter-spacing:3px;font-weight:600}
.tag{display:inline-block;background:#0c1210;border:1px solid var(--line);border-radius:5px;padding:0 7px;font-size:11px;color:var(--dim);margin:2px 4px 2px 0}
table{width:100%;border-collapse:collapse;font-size:13px}
th{color:var(--dim);font-weight:500;text-align:left;padding:3px 6px;border-bottom:1px solid var(--line)}
td{padding:4px 6px;border-bottom:1px solid #1e2a23}
.pos{color:var(--green)}.neg{color:var(--red)}
.note{color:var(--acc);font-size:12px}
.wait{color:var(--dim);font-size:13px;padding:8px 0}
.opp{font-size:12px;color:var(--dim);margin-top:6px}
#err{color:var(--red);font-size:12px}
</style></head><body>
<h1>EV 军师 <span style="color:var(--acc)">侧栏</span></h1>
<div class="sub">数学核心实时计算 · LLM 零参与 · 每 2 秒自动同步牌桌</div>
<div id="err"></div><div id="main"><div class="card wait">连接牌桌中…</div></div>
<script>
const $=q=>document.querySelector(q);
const pct=v=>v==null?'-':(v*100).toFixed(0)+'%';
function render(s){
  $('#err').textContent='';
  if(!s.ok){$('#main').innerHTML='<div class="card note">'+(s.error||'不可用')+'</div>';return}
  let h='<div class="card"><div class="hand">'+s.hand.join(' ')+'</div><div style="margin-top:6px">'
   +'<span class="tag">牌墙'+(s.wall_count??'-')+'</span><span class="tag">向听'+(s.shanten??'-')+'</span>'
   +(s.ron_blocked?'<span class="tag" style="color:var(--red)">过胡未过圈</span>':'')
   +(s.locked_with&&s.locked_with.length?'<span class="tag" style="color:var(--red)">互锁'+s.locked_with+'</span>':'')
   +(s.peng_blocked&&s.peng_blocked.length?'<span class="tag">过碰'+s.peng_blocked.join('')+'</span>':'')
   +'</div></div>';
  if(s.stage==='ended'){
    h+='<div class="card"><b>对局结束</b> 净分 '+JSON.stringify(s.net)
     +'<div class="note" style="margin-top:6px">复盘双通道（先验 vs 摊牌真值）</div>'
     +((s.review||[]).length?'<table><tr><th>打</th><th>先验</th><th>真值</th><th>偏差</th></tr>'
       +s.review.map(r=>'<tr><td>'+r.tile+'</td><td>'+r.prior_p.toFixed(2)+'</td><td>'
         +(r.true_p==null?'不全':r.true_p)+'</td><td>'
         +(r.delta==null?'-':r.delta.toFixed(2))+'</td></tr>').join('')+'</table>'
       :'<div class="wait">本局无弃牌 receipt</div>')+'</div>';
    $('#main').innerHTML=h;return}
  if(!s.awaiting_human){h+='<div class="card wait">'+(s.bot_thinking?'机器人思考中…':'等待你的回合…')+'</div>';$('#main').innerHTML=h;return}
  if(s.advice_note){h+='<div class="card note">'+s.advice_note+'</div>'}
  if(s.advice&&s.advice.length){
    h+='<div class="card"><b>EV 建议</b>（本巡：自摸概率×收益−点炮概率×损失）<table style="margin-top:4px">'
     +'<tr><th>打</th><th>EV</th><th>自摸</th><th>收益</th><th>点炮</th><th>损失</th><th>进张</th></tr>'
     +s.advice.map(a=>'<tr><td><b>'+a.tile+'</b></td><td class="'+(a.ev>=0?'pos':'neg')+'">'
       +a.ev.toFixed(3)+'</td><td>'+pct(a.p_win)+'</td><td>'+a.v_win+'</td><td>'+pct(a.p_point)
       +'</td><td>'+a.v_deal+'</td><td>'+a.neff+'张</td></tr>').join('')+'</table>'
     +'<div style="margin-top:4px">'+(s.advice[0].labels||[]).slice(0,3).map(l=>'<span class="tag">'+l+'</span>').join('')+'</div></div>';
    if(s.opponents){h+='<div class="card"><b>对手听牌先验</b>'
     +[['上家','left'],['对家','opposite'],['下家','right']].map(([zh,k])=>{const o=s.opponents[k];if(!o)return'';
       return '<div class="opp">'+zh+'：<b style="color:var(--acc)">'+pct(o.tenpai_prior)+'</b>'
        +(o.wait_top&&o.wait_top.length?'｜高频等待 '+o.wait_top.map(w=>w[0]).join(' '):'')+'</div>'}).join('')+'</div>'}
  } else if(!s.advice_note){h+='<div class="card wait">EV 不可用</div>'}
  $('#main').innerHTML=h;
}
async function tick(){
  try{const r=await fetch('/api/advice');render(await r.json())}
  catch(e){$('#err').textContent='牌桌未连接（先启动 scripts/ev_table.py）'}
}
tick();setInterval(tick,2000);
</script></body></html>
"""


def main():
    global TABLE_STATE
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    TABLE_STATE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8766"
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"EV adviser panel: http://127.0.0.1:{port}/ (table: {TABLE_STATE})", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
