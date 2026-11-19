"""桌面牌桌 UI 注入层（不改 simulation/，2026-11-19 用户需求）：

1. 副露记号：吃/碰/明杠的牌组里，"从别人那里拿的那张"旋转+金框标记，
   吃的组也显示"取自谁 · 第几口"。
2. 左侧常驻听牌面板：一听牌就在 info-sidebar 显示 胡哪些牌 × 未见几枚 ×
   可接炮/仅自摸，常驻不受手牌区提示语顶替。

实现方式：ev_table 在 HTTP 出口对运行时副本打补丁——
  /api/state   → desktop.view() 结果经 enrich_state 附加 meld.claimed
  /index.html  → 注入 <link>/<script> 指向面板资源（CSP 只许同源外链）
  /table.js    → 两处锚点字符串改写（找不到锚点时原样返回，优雅降级）
  /ui-panel.js /ui-panel.css → 本模块自带的面板资源
"""
import os
from typing import Tuple

PANEL_JS = r"""
(function () {
  "use strict";
  let fresh = null;
  function log(e) { try { console.error("[ui-panel]", e); } catch (_) {} }
  async function pollState() {
    try {
      const r = await fetch("/api/state", { cache: "no-store" });
      if (r.ok) fresh = await r.json();
    } catch (e) { /* 牌桌重启间隙忽略 */ }
  }
  function cur() { return fresh || (typeof state !== "undefined" && state) || null; }

  // A. 轮到你响应：不加横幅——动作按钮(只含可用项)上浮居中，本身就是提示
  const CALL_KINDS = ["chi", "peng", "ming_gang", "ron"];
  function renderAwait() {
    const s = cur();
    let awaiting = false;
    if (s && s.stage === "responses" && Array.isArray(s.legal_actions))
      awaiting = s.legal_actions.some(a => CALL_KINDS.includes(a.kind));
    document.body.classList.toggle("awaiting-call", awaiting);
  }

  // 听牌仅由本人 hand-dock 内的 #waits 渲染；不再向 body 挂固定徽章。
  // C. 左侧常驻面板（沿用，改用自取的最新状态）
  let lastPanelSig = "";
  function renderPanel() {
    try {
      const bar = document.querySelector(".info-sidebar");
      const s = cur();
      if (!bar || !s) return;
      let panel = document.getElementById("ui-tenpai-panel");
      if (!panel) {
        panel = document.createElement("div");
        panel.id = "ui-tenpai-panel";
        panel.className = "panel ui-tenpai-panel";
        bar.prepend(panel);
      }
      const self = s.self || {};
      const sig = JSON.stringify([s.stage, self.waiting_tiles, self.structural_shanten,
                                  self.held_flower_count, s.seat]);
      if (sig === lastPanelSig) return;
      lastPanelSig = sig;
      panel.replaceChildren();
      const waits = self.waiting_tiles || [];
      panel.hidden = s.stage === "ended" || !!self.held_flower_count || !waits.length;
      if (panel.hidden) return;
      const h2 = document.createElement("h2"); h2.textContent = "我听的牌";
      panel.append(h2);
      const box = document.createElement("div");
      box.className = "ui-wait-list";
      for (const w of waits) {
        const item = document.createElement("span");
        item.className = "ui-wait-item" + (w.unseen === 0 ? " exhausted" : "");
        item.title = (w.tile || "") + "：" + (w.reason || "") + "；未见仅扣自己牌与公开牌。";
        if (typeof image === "function") item.append(image(w.tile, "ui-wait-tile"));
        const n = document.createElement("small"); n.textContent = "未见 " + (w.unseen != null ? w.unseen : "?");
        const tag = document.createElement("small");
        tag.className = w.can_ron ? "ron-ok" : "ron-no";
        tag.textContent = w.can_ron ? "可接炮" : "仅自摸";
        item.append(n, tag);
        box.append(item);
      }
      panel.append(box);
      if (self.locked_with && self.locked_with.length) panel.append(mkNote("三口互锁中 · 本局只能自摸"));
    } catch (e) { log(e); }
  }
  function mkNote(text) {
    const el = document.createElement("span");
    el.className = "ui-wait-note"; el.textContent = text;
    return el;
  }

  async function tick() { renderAwait(); renderPanel(); }
  pollState();
  setInterval(tick, 700);
  setInterval(pollState, 1500);
})();
"""

PANEL_CSS = r"""
/* ===== 行动按钮：大而醒目（欢乐麻将式印章感） ===== */
.actions{gap:10px;}
.actions button{min-width:92px;min-height:58px;font-size:20px;font-weight:700;
  border-radius:14px;border:2px solid #6b5b2a;padding:6px 16px;
  background:linear-gradient(#33424f,#1d2831);color:#f2ead8;
  box-shadow:0 4px 14px rgba(0,0,0,.45);}
.actions button img{width:32px;height:44px;vertical-align:middle;margin:0 2px;}
.actions button.winning{background:radial-gradient(circle at 35% 30%,#e05a4e,#8f2318);
  border-color:#f3c88a;color:#fff;font-size:24px;}
.actions button.pass{background:#20262d;color:#9aa4ad;border-color:#3a444e;}
.actions button.gold{background:linear-gradient(#f0b429,#c88f18);color:#221a06;border-color:#f7d98a;}

/* 轮到你响应：动作条上浮居中（按钮本身就是提示，只弹可用的那几个） */
/* ui-actions-float */
body.awaiting-call .actions:has(button){position:fixed;left:50%;bottom:200px;transform:translateX(-50%);
  z-index:58;display:flex;background:transparent;border-radius:18px;
  padding:0;box-shadow:none;border:0;}
/* 页面自带 #motion 动作提示：过牌类无内容=纯噪声空黑框，隐藏；
   吃碰杠胡等带牌提示保留 */
.motion.event-pass,.motion.event-all_pass,.motion:empty{display:none!important;}
#actions[hidden]{display:none!important;}
/* ===== 副露标记（定稿2026-11-18）：横放牌+位置编码来源 =====
   左=上家 中=对家 右=下家；吃恒上家=左。无动画。 */
.meld .claimed-tile{transform:rotate(90deg) scale(.86);margin:0 2px;display:inline-block;}
/* ===== 座位信息防重叠：左右家名牌加底垫 ===== */
.table .left .player-heading,.table .right .player-heading{position:relative;z-index:6;
  background:rgba(13,17,20,.9);border-radius:10px;padding:5px 10px;width:fit-content;
  max-width:100%;box-shadow:0 2px 8px rgba(0,0,0,.45);}
/* ===== 左侧常驻听牌面板 ===== */
.ui-tenpai-panel .ui-wait-list{display:flex;flex-wrap:wrap;gap:6px;margin-top:6px;}
.ui-tenpai-panel .ui-wait-item{display:inline-flex;align-items:center;gap:4px;
  background:rgba(240,180,41,.12);border:1px solid rgba(240,180,41,.4);
  border-radius:6px;padding:3px 6px;}
.ui-tenpai-panel .ui-wait-item.exhausted{opacity:.45;filter:grayscale(.6);}
.ui-tenpai-panel .ui-wait-item small{font-size:11px;}
.ui-tenpai-panel .ui-wait-item .ron-ok{color:#7fd18a;}
.ui-tenpai-panel .ui-wait-item .ron-no{color:#e0a0a0;}
.ui-tenpai-panel .ui-wait-note{display:block;color:var(--muted,#999);font-size:12px;margin-top:4px;}
.ui-tenpai-panel img.ui-wait-tile{width:34px;height:48px;object-fit:contain;}
"""

_CLAIM_KINDS = ("chi", "peng", "ming_gang")


def _claims_from_events(events) -> dict:
    """每个座位的副露组顺序对应的 claimed 牌（吃=来源上一张弃牌，碰/明杠=tiles[0]）。"""
    last_discard = {}
    claims = {seat: [] for seat in range(4)}
    for ev in events or []:
        kind = ev.get("kind")
        seat = ev.get("seat")
        if kind == "discard":
            last_discard[seat] = ev.get("tile")
        elif kind in _CLAIM_KINDS:
            if kind == "chi":
                claims[seat].append(last_discard.get(ev.get("source")))
            else:
                tiles = ev.get("tiles") or []
                claims[seat].append(tiles[0] if tiles else None)
        elif kind == "an_gang":
            claims[seat].append(None)          # 暗杠自成组，无来源张
    return claims


def enrich_state(payload: dict) -> dict:
    """给 /api/state 附加 meld.claimed。幂等；无副露时原样返回。"""
    if not isinstance(payload, dict):
        return payload
    players = payload.get("players") or []
    if not players or (payload.get("players", [{}])[0].get("melds")
                       and "claimed" in payload["players"][0]["melds"][0]):
        return payload
    claims = _claims_from_events(payload.get("events"))
    for p in players:
        melds = p.get("melds") or []
        seat_claims = claims.get(p.get("seat"), [])
        offset = len(melds) - len(seat_claims)   # 与 observation 的 origins 对齐口径
        for i, meld in enumerate(melds):
            j = i - offset
            meld["claimed"] = seat_claims[j] if 0 <= j < len(seat_claims) else None
    return payload


def patch_index(html: str) -> str:
    if "/ui-panel.js" in html:
        return html
    tag = ('<link rel="stylesheet" href="/ui-panel.css">'
           '<script src="/ui-panel.js" defer></script>')
    return html.replace("</head>", tag + "</head>", 1)


_TABLEJS_ANCHORS = {
    "claimed_tile": (
        "for (let i=0; i<meld.size; i++) faces.append(tableTile(image(meld.hidden ? null : meld.tiles[i])));",
        "{ const __els=[]; let __claimed=null;"
        " for (let i=0; i<meld.size; i++){ const __t=tableTile(image(meld.hidden ? null : meld.tiles[i]));"
        " if(!__claimed && !meld.hidden && meld.claimed && meld.tiles[i]===meld.claimed){"
        " __t.classList.add('claimed-tile');"
        " __t.title='横放=来自'+(Number.isInteger(meld.source)?name(meld.source):'别家')+'的那张；位置：左上家中对家右下家';"
        " __claimed=__t; } __els.push(__t); }"
        " if(__claimed){ let __pos=1; try{ const __n=name(meld.source);"
        " const __delta=(meld.source-seat+4)%4; __pos=__delta===3?0:__delta===1?__els.length-1:1; }catch(e){ __pos=1; }"
        " if(meld.type==='chi') __pos=0;"
        " const __rest=__els.filter(t=>t!==__claimed);"
        " __rest.splice(Math.min(__pos,__rest.length),0,__claimed);"
        " __rest.forEach(t=>faces.append(t)); } else __els.forEach(t=>faces.append(t)); }",
    ),
    "chi_source": (
        "if(meld.type!==\"chi\"&&Number.isInteger(meld.source)){",
        "if(Number.isInteger(meld.source)){",
    ),
}


def patch_tablejs(js: str) -> Tuple[str, dict]:
    applied = {}
    for key, (old, new) in _TABLEJS_ANCHORS.items():
        if old in js:
            js = js.replace(old, new, 1)
            applied[key] = True
        else:
            applied[key] = (new in js)          # 已打过补丁视为成功
    return js, applied


def patched_assets(assets_dir) -> dict:
    """预生成所有运行时改写资源 {url路径: (bytes, mimetype)}。"""
    def read(name):
        with open(os.path.join(str(assets_dir), name), encoding="utf-8") as fh:
            return fh.read()

    index = patch_index(read("index.html"))
    tablejs, _ = patch_tablejs(read("table.js"))
    return {
        "/": (index.encode(), "text/html; charset=utf-8"),
        "/index.html": (index.encode(), "text/html; charset=utf-8"),
        "/table.js": (tablejs.encode(), "text/javascript; charset=utf-8"),
        "/ui-panel.js": (PANEL_JS.encode(), "text/javascript; charset=utf-8"),
        "/ui-panel.css": (PANEL_CSS.encode(), "text/css; charset=utf-8"),
    }


def wrap_desktop(desktop) -> None:
    """富化 desktop.view() 的返回（/api/state 出口）。"""
    import functools
    original = desktop.view
    @functools.wraps(original)
    def wrapped():
        return enrich_state(original())
    desktop.view = wrapped


def make_patched_handler(base_handler_class):
    """返回拦截静态资源的 Handler 子类（其余行为走原类）。"""
    from http.server import BaseHTTPRequestHandler
    from src.simulation.web import ASSETS
    assets = patched_assets(ASSETS)

    class PatchedHandler(base_handler_class):
        def do_GET(self):
            path = self.path.split("?")[0]
            if self._local() and path in assets:
                body, ctype = assets[path]
                return self._send(200, body, ctype)
            return super().do_GET()

    return PatchedHandler
