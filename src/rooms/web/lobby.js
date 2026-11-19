"use strict";
let TOKEN = localStorage.getItem("taihu.token") || "";
let VISITOR = localStorage.getItem("taihu.visitor") || "";
let ROOM_ID = localStorage.getItem("taihu.room") || "";

const $ = (id) => document.getElementById(id);
function notify(text) { $("notice").textContent = text; }

async function api(path, body) {
  const r = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-Visitor-Token": TOKEN },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || r.statusText);
  return data;
}

async function ensureVisitor() {
  if (TOKEN && VISITOR) {
    try { const v = await api("/api/lobby/visitor"); showWho(v); return; } catch (e) { /* 过期重建 */ }
  }
  const v = await api("/api/lobby/visitor", { nickname: $("nickname").value.trim() });
  TOKEN = v.token; VISITOR = v.visitor;
  localStorage.setItem("taihu.token", TOKEN);
  localStorage.setItem("taihu.visitor", VISITOR);
  showWho(v);
}
function showWho(v) { $("whoami").textContent = `访客：${v.nickname}`; }

async function createRoom() {
  const room = await api("/api/lobby/rooms", {});
  ROOM_ID = room.room_id;
  localStorage.setItem("taihu.room", ROOM_ID);
  render();
}
async function poll() {
  if (!ROOM_ID || !TOKEN) return;
  try {
    const data = await api(`/api/lobby/rooms/${ROOM_ID}`);
    renderRoom(data);
  } catch (e) {
    if (String(e.message).includes("不存在")) { ROOM_ID = ""; localStorage.removeItem("taihu.room"); render(); }
  }
}

function renderRoom(data) {
  $("room-id").textContent = "#" + data.room_id.slice(1, 7);
  $("room-state").textContent =
    data.state === "playing" ? "对局中" :
    data.last_game ? (data.last_game.outcome === "aborted"
      ? `上一局已中止（${data.last_game.reason || ""}）` : "上一局已结束") : "等待准备";
  const tbody = $("seats"); tbody.replaceChildren();
  for (const s of data.seats) {
    const tr = document.createElement("tr");
    const who = s.kind === "empty" ? "空座" : `${s.nickname || ""}${s.kind === "bot" ? "（机器人）" : ""}`;
    tr.innerHTML = `<td>${who}</td><td>${s.kind === "bot" ? "就绪" : (s.ready ? "已准备" : "未准备")}</td>`;
    tbody.append(tr);
  }
  const playing = data.state === "playing";
  $("fill-bots").disabled = playing;
  $("ready").disabled = playing;
  $("ready").textContent = "准备";
  $("start").disabled = playing;
  $("open-table").hidden = !playing;
  if (playing && data.table_url) $("open-table").onclick = () => window.open(data.table_url, "_blank");
  const hist = $("history"); hist.replaceChildren();
  for (const g of (data.history || []).slice(-5).reverse()) {
    const li = document.createElement("li");
    li.textContent = `${g.game_id.slice(0, 8)}… ${g.outcome === "aborted" ? "中止" : "结束"}`;
    hist.append(li);
  }
}

function render() {
  $("room-card").hidden = !ROOM_ID;
  $("lobby-card").hidden = !!ROOM_ID;
  if (ROOM_ID) poll();
}

document.addEventListener("DOMContentLoaded", () => {
  $("create-room").onclick = async () => { try { await createRoom(); } catch (e) { notify(e.message); } };
  $("fill-bots").onclick = async () => { try { await api(`/api/lobby/rooms/${ROOM_ID}/bots`, {}); poll(); } catch (e) { notify(e.message); } };
  $("ready").onclick = async () => { try { await api(`/api/lobby/rooms/${ROOM_ID}/ready`, { ready: true }); poll(); } catch (e) { notify(e.message); } };
  $("start").onclick = async () => {
    try {
      const ref = await api(`/api/lobby/rooms/${ROOM_ID}/start`, {});
      notify("对局已创建，进入牌桌开始打牌");
      poll();
      if (ref.table_url) window.open(ref.table_url, "_blank");
    } catch (e) { notify(e.message); }
  };
  $("leave").onclick = async () => {
    if (!confirm("离开将中止进行中的陪打局（不按正常结算）。确定？")) return;
    try { await api(`/api/lobby/rooms/${ROOM_ID}/leave`, {}); ROOM_ID = ""; localStorage.removeItem("taihu.room"); render(); }
    catch (e) { notify(e.message); }
  };
  ensureVisitor().then(render).catch((e) => notify("访客身份失败：" + e.message));
  setInterval(poll, 2000);
});
