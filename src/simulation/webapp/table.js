"use strict";
const $ = id => document.getElementById(id);
let state, live, selected = null, busy = false, playing = false, queue = [], remaining = 0;
let paused = false, speed = "normal", resultSeen = null, noticeTimer;
let flowerMode = false, flowerKeys = new Set();
let polling = false, coachRequest = false;
let coachRenderKey = null;
try { speed = localStorage.getItem("mahjong-speed") || "normal"; } catch {}
if (!["slow", "normal", "fast", "step"].includes(speed)) speed = "normal";
const special = {东风:"Ton",南风:"Nan",西风:"Shaa",北风:"Pei",中:"Chun",发:"Hatsu",白:"HakuLocal",春:"Flower1",夏:"Flower2",秋:"Flower3",冬:"Flower4",梅:"Flower5",兰:"Flower6",竹:"Flower7",菊:"Flower8"};
const labels = {win:"胡 · 自摸 / 杠开",ron:"胡 · 接炮",peng:"碰",chi:"吃",flower_kong:"换花",an_gang:"暗杠",ming_gang:"明杠",add_gang:"加杠",pass:"不吃碰胡 · 正常轮转"};
const words = {draw:"摸牌",discard:"打出",flower_kong:"单张换花",an_gang:"暗杠",add_gang:"加杠",peng:"碰",chi:"吃",ming_gang:"明杠",three_calls_lock:"三口互锁 · 双方只能自摸",end:"本局结束",win:"胡牌",all_pass:"无人鸣牌 · 正常轮转"};
function node(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}
function tileFile(t) {
  const m = /^([1-9])(万|饼|条)$/.exec(t);
  return m ? ({万:"Man",饼:"Pin",条:"Sou"}[m[2]] + m[1]) : special[t] || "Back";
}
function image(t, cls = "small-tile") {
  const el = node("img", cls);
  el.src = `/tiles/${tileFile(t)}.svg`;
  el.alt = t || "牌背"; el.title = t || "未知暗牌"; el.draggable = false;
  return el;
}
function tableTile(img, concealed = false) {
  const slot = node("span", concealed ? "table-tile concealed-tile" : "table-tile");
  slot.append(img); return slot;
}
function name(seat) { return ["你", "下家", "对家", "上家"][(seat - state.seat + 4) % 4]; }
function notify(text) {
  clearTimeout(noticeTimer); $("notice").textContent = text; $("notice").classList.add("visible");
  noticeTimer = setTimeout(() => $("notice").classList.remove("visible"), 6500);
}
async function request(path, body) {
  // GET may be retried safely. Never time out and blindly repeat a mutation.
  const controller = !body ? new AbortController() : null;
  const timer = controller ? setTimeout(() => controller.abort(), 10000) : null;
  try {
    const r = await fetch(path, body ? {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)} : {signal:controller.signal});
    const data = await r.json();
    if (!r.ok) throw new Error(data.error || "操作失败");
    return data;
  } catch(error) {
    if (error.name === "AbortError") throw new Error("连接裁判超时，请点击新的一局重试连接；不会自动重开或出牌。");
    throw error;
  } finally { if(timer) clearTimeout(timer); }
}
function accept(data) {
  if(live&&data.version?.split(":")[0]!==live.version?.split(":")[0])globalThis.TableAudio?.reset();
  queue = data.frames || []; delete data.frames;
  live = data; selected = null; flowerMode = false; flowerKeys.clear();
  if (queue.length) { playing = true; presentNext(); }
  else { playing = false; state = live; remaining = 1000; render(); }
}
async function run(path, extra = {}) {
  if (busy) return false;
  busy = true; controls();
  try { accept(await request(path, {version:live.version, ...extra})); return true; }
  catch (error) {
    paused = true; notify(error.message);
    try { accept(await request("/api/state")); } catch { notify("连接中断。已暂停，请确认服务后刷新；不会自动代你出牌。"); }
    return false;
  } finally {
    busy = false;
    if (state) { renderHand(); renderActions(); }
    controls();
  }
}
function doAction(id) {
  if (busy || playing || !state.awaiting_human) return;
  run("/api/action", {action_id:id});
}
function presentNext() {
  state = queue.shift(); selected = null;
  const kind = state.presentation?.kind;
  remaining = kind === "three_calls_lock" ? 2800 : kind === "discard" || kind === "win" ? 1700 : kind === "end" ? 800 : kind === "draw" ? 650 : 1100;
  render();
  globalThis.TableAudio?.present(state.presentation);
}
function finishPlayback() { playing = false; state = live; remaining = 1000; render(); }
function advancePhase(manual = false) {
  if (busy || !live) return;
  if (playing) {
    if (queue.length) { presentNext(); return; }
    finishPlayback();
    if (!manual) return;
  }
  if (live.can_advance) run("/api/step");
}
let lastTick = performance.now();
setInterval(() => {
  const now = performance.now(), elapsed = Math.min(200, now - lastTick); lastTick = now;
  if (!live || busy || paused || speed === "step" || document.hidden) return;
  if (!playing && !live.can_advance) return;
  remaining -= elapsed * ({slow:0.6, normal:1, fast:2.5}[speed] || 1);
  if (playing && state.presentation?.kind === "discard" && remaining < 300) $("motion").classList.add("leaving");
  if (remaining <= 0) advancePhase();
}, 50);
function controls() {
  globalThis.TableAudio?.pause(paused);
  document.body.classList.toggle("busy", busy);
  document.body.classList.toggle("playing", playing);
  document.body.classList.toggle("animation-paused", paused || speed === "step");
  $("pause").textContent = paused ? "继续" : "暂停";
  $("step").disabled = busy || !live || (!playing && !live.can_advance);
  $("save").disabled = busy;
  $("new").disabled = busy || playing;
  $("connection").textContent = busy ? "裁判处理中…" : live?.bot_thinking ? `机器人快速决策 · ${Math.round((live.bot_elapsed_ms||0)/1000)}秒` : live?.bot_error ? "机器人已暂停 · 查看下方原因" : paused ? "已暂停" : speed === "step" ? "逐步陪练" : playing ? "正在展示桌面动作" : "本地裁判已连接";
}
function latestDiscard() {
  for (let i = state.events.length - 1; i >= 0; i--) {
    const e = state.events[i];
    if (["chi", "peng", "ming_gang"].includes(e.kind)) return null;
    if (e.kind === "discard") return e;
  }
  return null;
}
function renderSeat(position, delta) {
  const seat = (state.seat + delta) % 4, p = state.players[seat], el = $(position);
  const dock=delta===0?document.querySelector(".hand-dock"):null;
  const surface=delta===0 ? el.querySelector(":scope > .seat-surface")||node("div","seat-surface") : node("div","seat-surface");
  // 本人的手牌底座始终留在文档中，避免待牌图片重挂载及滚动位置复位。
  if(delta===0){
    for(const child of [...el.children])if(child!==surface)child.remove();
    for(const child of [...surface.children])if(child!==dock)child.remove();
  }else el.replaceChildren();
  el.classList.toggle("active", state.stage !== "ended" && state.actor === seat);
  let handZone;
  const heading = node("div", "player-heading"), details = node("div");
  heading.append(node("div", "avatar", ["我","下","对","上"][delta]));
  const title = node("div", "seat-name", name(seat) + ` · 座位${seat}`);
  if (state.dealer === seat) title.append(node("b", "", "庄"));
  if (state.result) title.append(node("span", "seat-net", `${state.result.net[seat] > 0 ? "+" : ""}${state.result.net[seat]} 分`));
  details.append(title, node("div", "meta", `${p.hand_count} 张手牌 · 已换花 ${p.flowers.length} 张 / ${p.public_flower_hua} 花分`));
  if (p.locked_with?.length) details.append(node("div","warning",`三口互锁：${p.locked_with.map(name).join("、")} · 只能自摸 · 彼此付3倍`));

  heading.append(details); el.append(heading);
  if (delta) {
    const hand = node("div", "concealed" + (state.revealed_hands ? " revealed" : ""));
    const actual = state.revealed_hands?.[seat];
    const tiles = actual ? [...actual].sort((a,b) => tileOrder(a)-tileOrder(b)) : Array(p.hand_count).fill(null);
    tiles.forEach((t,i) => {
      const img = image(t, "");
      if (!actual && state.actor === seat && state.stage === "turn" && p.hand_count === 14 - 3*p.melds.length && i === tiles.length-1) img.classList.add("opponent-drawn");
      if (actual && state.result.method !== "dianpao" && state.result.winners.includes(seat) && t === state.result.tile && i === tiles.lastIndexOf(t)) img.classList.add("winning-tile");
      const slot = tableTile(img, true);
      if(img.classList.contains("opponent-drawn"))slot.classList.add("opponent-drawn");
      hand.append(slot);
    });
    if (actual && state.result.method === "dianpao" && state.result.winners.includes(seat)) {
      const claimed = image(state.result.tile, "winning-tile claimed-win");
      claimed.title = "接炮胡牌张（实体仍在放炮者牌河）"; hand.append(tableTile(claimed, true));
    }
    handZone=node("div","zone hand-zone");
    handZone.append(node("div","zone-title",actual?"局末手牌":`暗牌 · ${p.hand_count} 张`),hand);
  }
  const exposed = node("div", "exposed");
  let meldZone;
  {
    const zone=node("div","zone meld-zone"), row = node("div", "zone-cards");
    zone.append(node("div","zone-title","吃 / 碰 / 杠"));
    for (const meld of p.melds) {
      const group = node("span", "meld"+(meld.size===4?" quad":"")); group.title = {peng:"碰",chi:"吃",an_gang:"暗杠",ming_gang:"明杠"}[meld.type];
      const faces=node("span","meld-faces");
      for (let i=0; i<meld.size; i++) faces.append(tableTile(image(meld.hidden ? null : meld.tiles[i])));
      group.append(faces);
      if(meld.type!=="chi"&&Number.isInteger(meld.source)){
        group.append(node("small","meld-source",`取自${name(meld.source)}`));
        group.title+=`，来源座位${meld.source}，本方向第${meld.call_number}口；加杠不增加口数`;
      }
      row.append(group);
    }
    if(!p.melds.length)row.append(node("span","zone-empty","暂无"));
    zone.append(row); meldZone=zone; zone.hidden=!p.melds.length;
  }
  {
    const zone=node("div","zone flower-zone"),row=node("div","zone-cards");
    zone.append(node("div","zone-title",`已换花 · ${p.flowers.length} 张 / ${p.public_flower_hua} 分`));
    p.flowers.forEach(t => row.append(tableTile(image(t))));
    zone.hidden=!p.flowers.length;
    zone.append(row);exposed.append(zone);
  }
  surface.insertBefore(exposed,dock?.parentNode===surface?dock:null);
  if(handZone){const rail=node("div","tile-rail");rail.append(meldZone,handZone);surface.append(rail);}
  if(dock){
    const hand=dock.querySelector("#hand");
    let rail=dock.querySelector(".hand-row");
    if(!rail){rail=node("div","hand-row");dock.append(rail);}
    rail.replaceChildren(meldZone,hand);
    if(dock.parentNode!==surface)surface.append(dock);
  }
  if(surface.parentNode!==el)el.append(surface);
  const river = $("river-" + position), latest = latestDiscard(), cards=node("div","river-cards");
  river.replaceChildren(node("div","zone-title",`${name(seat)} · 弃牌 ${p.river.length}`),cards);
  p.river.forEach((t,i) => {
    const img = image(t, "");
    if (latest?.seat === seat && i === p.river.length-1 && latest.tile === t) {
      img.classList.add("latest");
      if (playing && state.presentation?.kind === "discard") img.classList.add("in-flight");
    }
    cards.append(tableTile(img));
  });
}
function tileOrder(t) {
  const m = /^([1-9])(万|饼|条)$/.exec(t);
  return m ? {万:0,饼:10,条:20}[m[2]] + Number(m[1]) : 30 + ["南风","西风","北风","东风","中","发","白","春","夏","秋","冬","梅","兰","竹","菊"].indexOf(t);
}
function renderHand() {
  const el = $("hand"); el.replaceChildren();
  const tiles = state.self.hand.map((tile,index) => ({tile,key:String(index)}));
  const fresh = new Set(), freshCounts = new Map();
  for (const t of state.batch_result?.drawn || []) freshCounts.set(t,(freshCounts.get(t)||0)+1);
  for (let i=tiles.length-1;i>=0;i--) {
    const t=tiles[i].tile;
    if(freshCounts.get(t)>0){fresh.add(tiles[i].key);freshCounts.set(t,freshCounts.get(t)-1);}
  }
  const drawn = state.self.drawn_tile;
  let separated;
  if (drawn && ["normal","replacement"].includes(state.self.draw_source)) {
    const index = tiles.map(x=>x.tile).lastIndexOf(drawn);
    if (index >= 0) separated = tiles.splice(index,1)[0];
  }
  const add = (item, isDrawn) => {
    const t = item.tile, discard = state.legal_actions.find(a => a.kind === "discard" && a.tiles[0] === t);
    const flower = state.legal_actions.find(a => a.kind === "flower_kong" && a.tiles[0] === t);
    const btn = node("button", "tile-button" + (isDrawn ? " drawn" : ""));
    btn.type = "button"; btn.dataset.tileKey = item.key;
    btn.setAttribute("aria-label", `${isDrawn?"新摸 ":""}${t}${flowerMode&&flower?"，点击选择或取消换花":discard?"，再点同一张打出":flower?"，花牌请用换花按钮":""}`);
    btn.setAttribute("aria-pressed", String(flowerMode ? flowerKeys.has(item.key) : selected?.key === item.key));
    btn.append(image(t,""));
    btn.classList.toggle("batch-new",fresh.has(item.key));
    btn.classList.toggle("tenpai-choice",!!state.self.discard_waits?.[t]?.length);
    if (state.result?.method !== "dianpao" && state.result?.winners.includes(state.seat) && t === state.result.tile && item.key === String(state.self.hand.lastIndexOf(t))) btn.classList.add("winning-tile");
    if (special[t] && !["南风","西风","北风"].includes(t)) btn.append(node("span","flower","花"));
    btn.disabled = (flowerMode ? !flower : !discard) || busy || playing;
    btn.classList.toggle("selected", flowerMode ? flowerKeys.has(item.key) : selected?.key === item.key);
    btn.onclick = () => {
      if (flowerMode) {
        if (flowerKeys.has(item.key)) flowerKeys.delete(item.key); else flowerKeys.add(item.key);
        renderHand(); renderActions(); return;
      }
      if (selected?.key === item.key) { doAction(discard.id); return; }
      globalThis.TableAudio?.select();
      selected = {...discard, key:item.key}; renderHand(); renderActions();
    };
    el.append(btn);
  };
  tiles.forEach(t => add(t,false)); if (separated) add(separated,true);
  if (state.result?.method === "dianpao" && state.result.winners.includes(state.seat)) {
    const claimed = image(state.result.tile,"winning-tile claimed-win"); claimed.title="接炮胡牌张（实体仍在放炮者牌河）"; el.append(claimed);
  }
  const ownScore=state.result?` · ${state.result.net[state.seat]>0?"+":""}${state.result.net[state.seat]}分`:"";
  const ownCalls=(state.call_counts?.[state.seat]||[]).map((n,s)=>n?`向${name(s)}${n>=3?`${n}口已互锁`:`${n}/3口`}`:"").filter(Boolean);
  const title=`你 · 座位${state.seat}${state.dealer===state.seat?" · 庄":""}${ownScore} · 手牌${state.self.hand.length}张（留花${state.self.held_flower_count}张）${ownCalls.length?" · "+ownCalls.join("、"):""}`;
  $("hand-title").textContent=title;$("hand-title").setAttribute("title",title);
  renderWaits();
}
function renderWaits() {
  const el=$("waits");
  let waits=state.self.waiting_tiles||[],previewTile=null;
  if(selected){previewTile=selected.tiles[0];waits=state.self.discard_waits?.[previewTile]||[];}
  // 摸牌后仍保留可维持原听口的提示，明确为出牌后预览，不缓存失效待牌。
  else if(!waits.length && state.self.drawn_tile){
    const drawnWaits=state.self.discard_waits?.[state.self.drawn_tile]||[];
    if(drawnWaits.length){previewTile=state.self.drawn_tile;waits=drawnWaits;}
  }
  if(state.stage==="ended" || state.self.held_flower_count) waits=[];
  const restriction=state.self.locked_with?.length?"互锁 · 仅自摸":state.self.ron_blocked?"过胡未过圈 · 仅自摸":waits.some(w=>!w.can_ron)?"无接炮资格 · 仅自摸":"未见不等于牌墙剩余";
  const sig=JSON.stringify([state.version?.split(":")[0],state.seat,previewTile,restriction,waits]);
  if(el.dataset.waitSignature===sig)return;
  el.dataset.waitSignature=sig;
  const scrollLeft=el.querySelector(".wait-items")?.scrollLeft||0;
  el.replaceChildren();
  if(!waits.length)return;
  el.append(node("strong","wait-title",previewTile?`打${previewTile}后听`:"听牌"));
  const items=node("div","wait-items");el.append(items);
  for(const w of waits){
    const item=node("span","wait-item"+(w.unseen===0?" exhausted":""));
    const selfPay=w.self_draw_payments?.map(p=>`${name(p.payer)}付${p.amount}`).join(" / ")||`每家 ${w.self_draw_hua} 分`;
    item.title=`${w.tile}：${w.reason}；普通自摸 ${selfPay}${w.can_ron?`，接炮 ${w.ron_hua} 分`:""}。未见不是牌墙活张。`;
    item.append(image(w.tile,""),node("small","",`未见 ${w.unseen}`),node("small",w.can_ron?"ron-ok":"ron-no",w.can_ron?"可接炮":"仅自摸"));items.append(item);
  }
  items.scrollLeft=scrollLeft;
  el.append(node("span","wait-explanation",restriction));
}
function renderActions() {
  const el = $("actions"); el.replaceChildren(); el.hidden=true;
  if (state.stage === "ended" || playing) return;
  if(state.pending&&state.self.peng_blocked?.includes(state.pending.tile))el.append(node("span","warning",`过碰${state.pending.tile}：本圈不能再碰这张，其他牌不受影响。`));
  if (state.bot_error) {
    el.append(node("span","warning",state.bot_error));
    const retry = node("button","gold","重试机器人（可能产生API费用）");
    retry.disabled=busy; retry.onclick=()=>run("/api/retry"); el.append(retry); el.hidden=false; return;
  }
  const flowerActions = state.legal_actions.filter(a=>a.kind==="flower_kong");
  if (flowerMode) {
    const chosen = [...flowerKeys].sort((a,b)=>Number(a)-Number(b)).map(key=>state.self.hand[Number(key)]);
    el.append(node("span","batch-summary",`选中 ${chosen.length} 张，换 ${chosen.length} 张 · 保留 ${state.self.held_flower_count-chosen.length} 张花`));
    const all = node("button","","全选花牌");
    all.onclick=()=>{ flowerKeys = new Set(state.self.hand.map((t,i)=>flowerActions.some(a=>a.tiles[0]===t)?String(i):null).filter(k=>k!==null)); renderHand();renderActions(); };
    const cancel = node("button","pass","取消多选");
    cancel.onclick=()=>{flowerMode=false;flowerKeys.clear();renderHand();renderActions();};
    const confirm = node("button","gold",`换这 ${chosen.length} 张`);
    confirm.disabled=busy||!chosen.length||chosen.length>state.wall_count;
    confirm.onclick=()=>run("/api/flowers",{tiles:chosen});
    el.append(all,cancel,confirm); el.hidden=false;
    if(chosen.length>state.wall_count)el.append(node("span","batch-summary","牌墙不足，请减少选择"));
    return;
  }
  if (flowerActions.length) {
    const multi = node("button","gold","多选换花"); multi.disabled=busy;
    multi.onclick=()=>{flowerMode=true;selected=null;flowerKeys.clear();renderHand();renderActions();}; el.append(multi);
  }
  if (state.legal_actions.some(a=>a.kind==="discard")) {
    const b = node("button","gold", selected ? `打出 ${selected.tiles[0]}` : "先选一张牌");
    b.disabled = !selected || busy; b.onclick = () => selected && doAction(selected.id); el.append(b);
  }
  const hasClaim=state.legal_actions.some(a=>["chi","peng","ming_gang","ron"].includes(a.kind));
  const actionOrder={pass:0,chi:1,peng:2,ming_gang:3,an_gang:3,add_gang:3,ron:4,win:4};
  for (const a of state.legal_actions.filter(a=>a.kind!=="discard"&&(a.kind!=="pass"||hasClaim)).sort((a,b)=>(actionOrder[a.kind]??5)-(actionOrder[b.kind]??5))) {
    const b = node("button", ["ron","win"].includes(a.kind) ? "winning" : a.kind==="pass" ? "pass" : "");
    b.dataset.kind=a.kind; b.disabled = busy; b.append(node("span","",a.kind==="pass"?"过":labels[a.kind] || a.kind)); a.tiles.forEach(t=>b.append(image(t)));
    if (a.score_per_payer) b.append(node("span","",a.payments?.length ? " "+a.payments.map(p=>`${name(p.payer)}付${p.amount}`).join(" / ") : ` ${a.kind==="ron"?"放炮者":"每家"}付 ${a.score_per_payer} 分`));
    b.onclick = () => {
      if (a.kind === "pass" && state.legal_actions.some(x=>x.kind==="ron") && !confirm("你现在可以胡牌。放弃后，过自己这一圈前不能接任何人的炮。确定放弃？")) return;
      if (["chi","peng","ming_gang"].includes(a.kind) && state.pending && state.call_counts?.[state.seat]?.[state.pending.source] === 2 && !state.self.locked_with?.includes(state.pending.source) && !confirm(`这是对${name(state.pending.source)}的第三口。双方本局只能自摸，彼此自摸付款乘3，确定吗？`)) return;
      doAction(a.id);
    };
    el.append(b);
  }
  el.hidden=!el.querySelector("button");
}
function statusLine(label,value) {
  const n = node("div","status-line"); n.append(node("span","",label),node("strong","",value)); return n;
}
function renderMotion() {
  const motion = $("motion"); motion.replaceChildren(); motion.className = "motion";
  const e = state.presentation;
  if (!playing || !e || ["pass","all_pass","end"].includes(e.kind)) return;
  const delta = Number.isInteger(e.seat) ? (e.seat-state.seat+4)%4 : 0;
  motion.classList.add("visible", "from-"+["bottom","right","top","left"][delta], "event-"+e.kind);
  const text = e.kind === "flower_batch" ? `${name(e.seat)} · 连续换花 ${e.tiles.length} 张` : e.kind === "win" ? (e.winners || [e.seat]).map(name).join("、")+" · 胡牌" : `${name(e.seat)} · ${e.kind==="draw"&&e.replacement?"补牌":words[e.kind]||e.kind}`;
  motion.append(node("div","motion-title",text));
  if (e.kind === "flower_batch") {
    const out=node("div","batch-row"), incoming=node("div","batch-row");
    out.append(node("span","","换出")); e.tiles.forEach(t=>out.append(image(t,"motion-tile")));
    incoming.append(node("span","","补回")); (e.drawn_tiles||Array(e.drawn_count).fill(null)).forEach(t=>incoming.append(image(t,"motion-tile")));
    motion.append(out,incoming);
  }
  else if (e.kind === "draw") motion.append(image(e.hidden ? null : e.tile,"motion-tile"));
  else if (e.kind === "an_gang") for (let i=0;i<4;i++) motion.append(image(e.hidden?null:e.tile,"motion-tile"));
  else if (e.tiles) e.tiles.forEach(t=>motion.append(image(t,"motion-tile")));
  else if (e.tile) motion.append(image(e.tile,"motion-tile"));
  motion.append(node("div","motion-caption",e.kind==="flower_batch"?(e.seat===state.seat?"只换所选花牌；新补花牌留在手中，由你决定":`公开换出 ${e.tiles.length} 张花，补回 ${e.drawn_count} 张暗牌；牌面不公开`):e.kind==="discard"?"请看清这张弃牌":e.kind==="draw"?"摸牌后，再作选择":e.kind==="win"?"即将四家摊牌验牌":"先完成动作，再继续轮转"));
}
function render() {
  renderSeat("bottom",0); renderSeat("right",1); renderSeat("top",2); renderSeat("left",3);
  $("wall").textContent = state.wall_count;
  $("turn").textContent = state.stage==="ended" ? "本局已结算" : state.stage==="responses" ? "弃牌响应" : `${name(state.actor)}${state.can_advance?"思考中":"的回合"}`;
  const pending = $("pending"); pending.replaceChildren();
  if (state.pending && !playing && state.stage !== "ended") pending.append(image(state.pending.tile,""),node("span","",name(state.pending.source)+"打出"));
  const phases = {initial:"庄家起手 · 直接选牌或换花",normal:"已摸牌 · 点牌冒头，再点打出",replacement:"已补牌 · 可继续换花或打牌",claim:"吃碰后 · 直接打牌，不再摸牌"};
  $("phase").textContent = playing ? "正在逐步展示桌面动作" : state.stage==="ended" ? "四家已摊牌 · 可继续验牌" : state.stage==="responses" ? "尚未摸牌 · 过只放弃本次响应" : phases[state.self.draw_source] || "等待正常轮转";
  renderHand(); renderActions(); renderMotion(); renderCoaching();
  const status = $("status");
  const handStatus=state.self.structural_shanten<0?"成牌":state.self.waiting_tiles?.length?"听牌":Object.keys(state.self.discard_waits||{}).length?"出牌后可听":`${state.self.structural_shanten} 向听`;
  status.replaceChildren(statusLine("对手",state.bot_description||"三个基础机器人"),statusLine("规则",state.rules_version),statusLine("结构向听",handStatus),statusLine("接炮资格",state.self.locked_with?.length?"三口互锁 · 本局只能自摸":state.self.ron_blocked?"过胡未过圈 · 暂不可接炮":"仍须满足成牌与资格花"));
  if (state.bot_error) status.append(node("p","warning",state.bot_error+"；已暂停，点击重试或保存，不会自动代打。"));
  if (state.credential_sources) status.append(node("p","hint","密钥来源："+state.credential_sources.join(" / ")));
  status.append(statusLine("剩余牌墙",`${state.wall_count} 张`));
  if(state.self.peng_blocked?.length)status.append(node("p","warning",`过碰：${state.self.peng_blocked.join("、")}，过自己回合前不能碰；其他牌仍可碰。`));
  if(state.bot_elapsed_ms!==null&&state.bot_elapsed_ms!==undefined)status.append(statusLine("机器人决策耗时",`${(state.bot_elapsed_ms/1000).toFixed(1)}秒${state.bot_thinking?"（进行中）":"（上次）"}`));
  if (playing) status.replaceChildren(node("p","hint","以当前展示为准，动作播放完成后再更新向听与资格分析。"));
  if (state.self.held_flower_count) status.append(node("p","warning","手中留花占位；胡牌前必须处理完。结构向听不代表换花后的收益。"));
  if (state.saved_file) status.append(node("p","hint","私有牌谱："+state.saved_file));
  const log = $("log"); log.replaceChildren();
  for (const e of state.events.slice(-60)) {
    const li = node("li"); li.append(document.createTextNode((Number.isInteger(e.seat)?name(e.seat)+" · ":"")+(e.kind==="draw"&&e.replacement?"补牌":words[e.kind]||e.kind)+" "));
    if (e.tile) li.append(image(e.tile)); else if (e.hidden) li.append(document.createTextNode("（不公开牌面）"));
    if (e.tiles) e.tiles.forEach(t=>li.append(image(t))); log.append(li);
    if (e.kind === "three_calls_lock") li.append(document.createTextNode(" · 与"+name(e.source)+"锁定"));
  }
  controls();
  if (state.result && !playing && resultSeen !== state.version) {
    resultSeen = state.version; renderResult(); $("result-dialog").showModal();
  }
}
function actionText(a) {
  if(!a)return "暂无";
  return (a.kind==="discard"?"打":labels[a.kind]||a.kind)+" "+(a.tiles||[]).join(" ");
}
function renderCoaching() {
  const el=$("coach-content"), explanation=$("coach-explanation"), button=$("ask-coach");
  if(!el||!explanation||!button)return;
  const renderKey=JSON.stringify([state.version,state.coach_job,state.strategy_revision,state.strategy_job?.status,state.coach_feed,state.coach_auto,state.coach_suspended,state.coach_limit,state.coach_calls_remaining,state.coach_available,!!state.coaching,!!state.review,coachRequest,playing]);
  if(renderKey===coachRenderKey)return;
  coachRenderKey=renderKey;
  el.replaceChildren();explanation.textContent="";
  const report=state.coaching, review=state.review, job=state.coach_job;
  const evidence=node("details");evidence.append(node("summary","",review?"查看逐步复盘与计算依据":"查看候选与公开证据"));
  const appendEvidence=(...items)=>evidence.append(...items);
  if(review){
    el.append(node("p","coach-muted",`本局有${review.decision_count}次决策可回看。${review.different_count}次存在其他代码候选，不等于打错。`));
    appendEvidence(node("p","coach-muted",review.summary));
    for(const d of review.decisions){
      const details=node("details"), summary=node("summary","",`第${d.step}步 · ${actionText(d.actual)}${d.different?" · 有其他候选":""}`);
      details.append(summary,node("p","",`当时手牌：${d.hand_then.join(" ")}`),node("p","",`代码候选：${actionText(d.recommended)}`));
      if(d.actual_metrics?.shanten!==undefined)details.append(node("p","",`你的选择：${d.actual_metrics.shanten}向听／未见进张${d.actual_metrics.unseen_improving}张`));
      for(const a of d.alternatives)if(a.shanten!==undefined)details.append(node("p","coach-muted",`${actionText(a)}：${a.shanten}向听／未见进张${a.unseen_improving}张`));
      details.append(node("p","coach-muted",d.assessment));appendEvidence(details);
    }
    appendEvidence(node("p","coach-muted",review.limitations));
  }else if(report){
    appendEvidence(node("p","coach-muted",`即时牌效备选：${actionText(report.recommended_action)}。${state.coach_available?"军师会结合对手和时机，给出自己的取舍。":"尚未连接军师，目前仅提供代码牌效。"}`));
    appendEvidence(node("p","coach-muted",report.approach));
    if(report.structure_before){
      const shape=report.structure_before;
      appendEvidence(node("p","coach-muted",`完全孤立的结构牌：${shape.isolated_playable.join("、")||"无"}；留花${shape.held_flowers.length}张占位。`));
      for(const parts of shape.decompositions.slice(0,2))appendEvidence(node("p","coach-muted","替代分解："+parts.map(g=>g.tiles.join(" ")).join(" / ")));
    }
    for(const a of report.alternatives){
      appendEvidence(node("p","",`${actionText(a)}${a.shanten!==undefined?` · ${a.shanten}向听 · 未见进张${a.unseen_improving}张`:""}`));
      if(a.risk_notes?.length)appendEvidence(node("p","coach-muted",a.risk_notes.join("；")));
    }
    for(const p of report.opponents){
      const details=node("details"),summary=node("summary","",`${name(p.seat)} · 资格花下限${p.known_hua}${p.cannot_ron?" · 已互锁不能接炮":""}`);
      details.append(summary);
      [...p.evidence,...p.tendencies,...p.exclusions].forEach(t=>details.append(node("p","coach-muted",t)));appendEvidence(details);
    }
    appendEvidence(node("p","coach-muted",report.limitations.join(" ")));
    for(const flower of report.strategy_facts?.three_identical_flower_options||[]){
      appendEvidence(node("p","coach-muted",`留三张${flower.tile}可等第四张暗杠：四单换${flower.four_singles_hua}花，暗杠${flower.four_concealed_kong_hua}花且成一组；代价是三个占位，当前可立即换${flower.immediate_replacements_available}张。第四张未见上限${flower.fourth_copy_unseen_upper_bound}，未必在墙。`));
    }
  }else el.append(node("p","coach-muted",state.bot_thinking?"机器人正在思考，动作展示不会等待下次API返回。轮到你后显示建议。":"等待自己的决策时机。"));
  button.disabled=coachRequest||!state.coach_available||state.coach_calls_remaining<=0||(!report&&!review)||job?.status==="thinking"||playing;
  if(report||review)el.append(evidence);
  button.textContent=job?.status==="thinking"?"军师正在想 · 你仍可出牌":state.coach_available?`${review?"请军师复盘":"现在问军师"}（剩${state.coach_calls_remaining}/${state.coach_limit}次）`:"尚未配置 LLM";
  const auto=$("coach-auto"),budget=$("coach-budget");
  if(auto){auto.checked=!!state.coach_auto;auto.disabled=!state.coach_available||coachRequest;}
  if(budget){
    const limit=String(state.coach_limit||20);
    if(budget.options&&![...budget.options].some(o=>o.value===limit)){const option=node("option","",`每局最多${limit}次`);option.value=limit;budget.append(option);}
    budget.value=limit;budget.disabled=!state.coach_available||coachRequest;
  }
  if(state.coach_suspended&&state.coach_auto)el.prepend(node("p","coach-muted","常驻已开启，下一局开始自动分析；当前续局不会擅自计费。"));
  const fresh=job?.status==="ready"?job.result:null;
  const previous=state.coach_feed?.at(-1);
  if(fresh&&fresh.verification_version!=="strategy-v2"){
    explanation.append(node("p","warning","旧版讲解未通过新的结构化事实约束，已隐藏。不会自动重试或产生费用。"));
  }
  else if(fresh){
    const brief=fresh.brief||{action:fresh.summary.split("｜")[0].split("（")[0]};
    explanation.append(node("h3","coach-headline",brief.action));
    if(brief.reason)explanation.append(node("p","coach-reason",brief.reason));
    if(brief.alternative)explanation.append(node("p","coach-muted",brief.alternative));
    const opponents=node("div","coach-opponents");
    for(const opponent of brief.opponents||[{seat:"下家",text:"无法推断"},{seat:"对家",text:"无法推断"},{seat:"上家",text:"无法推断"}]){
      const row=node("div","coach-opponent");row.append(node("span","",opponent.seat),node("strong",opponent.text==="无法推断"?"unknown":"",opponent.text));opponents.append(row);
    }
    explanation.append(opponents);
    const full=node("details","coach-calculation");full.append(node("summary","","详细分析"),node("div","coach-full-text",fresh.explanation));
    if(fresh.verification_note)full.append(node("p","coach-muted",fresh.verification_note));
    explanation.append(full);
    if(fresh.decision_note){
      const note=fresh.decision_note,details=node("details");details.append(node("summary","","军师的局势笔记 · 推测，不是已知暗牌"));
      const confidence={low:"低",medium:"中",high:"高"};
      for(const p of note.opponents){
        details.append(node("p","",`${name(p.seat)}：${p.hypothesis}（把握${confidence[p.confidence]}）`),
          node("p","coach-muted",`未知：${p.uncertainty}；改判信号：${p.revision_trigger}`));
      }
      details.append(node("p","",`当前计划：${note.plan}`),node("p","coach-muted",`备选取舍：${note.alternative_reason}`),node("p","coach-muted",`改打法的条件：${note.change_if}`));
      explanation.append(details);
    }

  }
  else if(previous&&previous.result.verification_version==="strategy-v2"){
    const history=node("details","coach-stale");history.append(node("summary","","上一条建议"),node("div","",previous.result.summary+"\n"+previous.result.explanation));explanation.append(history);
  }
  else if(previous){explanation.append(node("p","coach-stale","旧版历史讲解未经新约束，已隐藏；不会自动重新调用模型。"));}
  if(job?.status==="error")explanation.append(node("p","warning",job.error));
  const local=$("local-strategy"), strategy=state.strategy_job;
  if(local){local.disabled=!report||busy||playing||strategy?.status==="thinking";local.textContent=strategy?.status==="thinking"?"本地计算中 · 仍可出牌":"比较多步方案（本地免费）";}
  const comparison=strategy?.status==="ready"?strategy.result:fresh?.strategy_comparison;
  if(comparison){
    const details=node("details");details.append(node("summary","","多步方案 · 自身成牌试验，不是实战净收益"));
    for(const p of comparison.solo_search.plans.slice(0,4))details.append(node("p","coach-muted",`${p.label}：${p.samples}个样本中${p.solo_reached_ready}次到听、${p.solo_wins}次自摸；末态平均结构${p.mean_terminal_shanten.toFixed(2)}向听。`));
    details.append(node("p","coach-muted","模拟忽略他家先胡、吃碰和补花；风险另行抽样，零命中不是安全。影子对手模型未真人校准，不参与自动风险排序。"));
    explanation.append(details);
  }
  if(strategy?.status==="error")explanation.append(node("p","warning",strategy.error));
}
function renderResult() {
  const r = state.result;
  $("result-title").textContent = r.method==="draw" ? "黄庄 · 全部零收入" : r.winners.map(name).join("、")+({zimo:"自摸",gangkai:"杠开",dianpao:"接炮胡"}[r.method]||"胡牌");
  const body = $("result-body"); body.replaceChildren();
  for (const p of state.players) {
    const row = node("div","result-seat",name(p.seat)); row.append(node("strong","",`${r.net[p.seat]>0?"+":""}${r.net[p.seat]} 分`));
    const hand = node("div","result-hand");
    [...state.revealed_hands[p.seat]].sort((a,b)=>tileOrder(a)-tileOrder(b)).forEach(t=>hand.append(image(t)));
    if (r.method === "dianpao" && r.winners.includes(p.seat)) hand.append(image(r.tile,"winning-tile claimed-win"));
    p.melds.forEach(m=>{ const group=node("span","meld"); m.tiles.forEach(t=>group.append(image(t))); hand.append(group); });
    row.append(hand); body.append(row);
  }
  for (const [seat,score] of Object.entries(r.scores||{})) body.append(node("p","",name(Number(seat))+"："+score.breakdown.join(" + ")));
  const seats = {me:0,right:1,opposite:2,left:3};
  for (const p of r.payments||[]) body.append(node("p","",`${name(seats[p.payer])} → ${name(seats[p.winner])}：${p.amount} 分`));
  body.append(node("p","hint","关闭弹窗后四家仍摊牌；暗杠已翻开。右侧算牌教练提供当时可见信息下的逐步复盘，可另请LLM总结。私有完整牌谱已自动保存。"));
}
$("pause").onclick = () => { paused = !paused; globalThis.TableAudio?.pause(paused); controls(); };
const infoButton = node("button","","桌面信息");
infoButton.onclick = () => {
  const hidden=!document.body.classList.toggle("details-open");
  infoButton.textContent=hidden?"桌面信息":"关闭信息";
};
document.querySelector(".toolbar").append(infoButton);
$("step").onclick = () => { paused = true; advancePhase(true); controls(); };
$("speed").value = speed;
$("speed").onchange = e => { speed=e.target.value; try {localStorage.setItem("mahjong-speed",speed);} catch {} controls(); };
$("save").onclick = async () => {
  if (busy || !live) return;
  busy=true; controls();
  try {
    const saved=await request("/api/save",{version:live.version});
    live.saved_file=saved.saved_file;
    notify("已保存到 runs/mahjong/"+saved.saved_file+"；当前动画不会跳过，可用 --resume 续局。");
  } catch(error) { paused=true; notify(error.message); }
  finally { busy=false; if(state){renderHand();renderActions();} controls(); }
};
function newDialog() {
  if (busy || playing) return notify("正在处理桌面动作，请稍后再开新局。");
  paused=true;
  $("dealer").value=state?.dealer ?? 0;
  $("new-dialog").showModal();
}
$("new").onclick = newDialog; $("cancel-new").onclick = () => $("new-dialog").close();
function applyCoachData(data){
  if((data.coach_revision||0)<(live.coach_revision||0))return;
  for(const key of ["coach_revision","coach_auto","coach_suspended","coach_limit","coach_job","coach_feed","coach_calls_remaining"]){live[key]=state[key]=data[key];}
}
function applyStrategyData(data){
  if((data.strategy_revision||0)<(live.strategy_revision||0))return;
  for(const key of ["strategy_revision","strategy_job"]){live[key]=state[key]=data[key];}
}
if($("local-strategy"))$("local-strategy").onclick=async()=>{
  if(!live||playing)return;
  const version=live.version;
  try{const data=await request("/api/strategy",{version});if(live.version===version){applyStrategyData(data);renderCoaching();}}
  catch(error){notify(error.message);}
};
if($("ask-coach"))$("ask-coach").onclick=async()=>{
  if(coachRequest||!live||playing)return;
  coachRequest=true;renderCoaching();
  const version=live.version;
  try{
    const data=await request("/api/coach",{version,mode:state.review?"review":"current"});
    if(live.version===version){
      applyCoachData(data);
    }
  }catch(error){notify(error.message);}
  finally{coachRequest=false;if(state)renderCoaching();}
};
async function setCoachSettings(){
  if(coachRequest||!live)return;
  coachRequest=true;const version=live.version;
  try{
    const data=await request("/api/coach/settings",{version,enabled:$("coach-auto").checked,limit:Number($("coach-budget").value)});
    if(live.version===version)applyCoachData(data);
  }catch(error){notify(error.message);}
  finally{coachRequest=false;coachRenderKey=null;renderCoaching();}
}
if($("coach-auto"))$("coach-auto").onchange=setCoachSettings;
if($("coach-budget"))$("coach-budget").onchange=setCoachSettings;
// Only poll read-only status while a background task is outstanding. A delayed
// response must not replace a newer game or reset a selected physical tile.
setInterval(async()=>{
  if(polling||busy||playing||!live||document.hidden||(!live.bot_thinking&&live.coach_job?.status!=="thinking"&&live.strategy_job?.status!=="thinking"&&!(live.coach_auto&&!live.coach_suspended)))return;
  polling=true;const version=live.version;
  try{
    const data=await request("/api/state");
    if(busy||playing||live.version!==version)return;
    if(live.bot_thinking&&!data.bot_thinking){accept(data);return;}
    live.bot_elapsed_ms=state.bot_elapsed_ms=data.bot_elapsed_ms;
    applyStrategyData(data);
    applyCoachData(data);
    controls();renderCoaching();
  }catch(error){notify(error.message);}
  finally{polling=false;}
},1000);
$("new-form").onsubmit = async e => {
  e.preventDefault(); const raw=$("seed").value, seed=raw===""?null:Number(raw);
  if (seed!==null&&!Number.isSafeInteger(seed)) return notify("请输入合法整数种子");
  if (!live) {
    $("connection").textContent="重新连接裁判…";
    try { accept(await request("/api/state")); }
    catch(error) { $("connection").textContent="连接失败 · 可重试"; return notify(error.message); }
  }
  if (await run("/api/new",{seed,dealer:Number($("dealer").value)})) { paused=false; $("new-dialog").close(); controls(); }
};
$("inspect").onclick = () => $("result-dialog").close();
$("next").onclick = () => { $("result-dialog").close(); newDialog(); };
document.querySelector(".table").addEventListener("click", e => {
  if (e.target.closest("button")) return;
  if (selected) { selected=null; renderHand(); renderActions(); }
});
request("/api/state").then(data=>{if(!live)accept(data);}).catch(error=>{
  if(live)return; // A manual reconnect may already have opened a newer game.
  notify(error.message);$("connection").textContent="连接失败 · 点击新的一局重试";
});
