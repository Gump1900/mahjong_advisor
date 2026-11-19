"use strict";
/* Mobile Block：只负责呈现，复用已有牌面与副露，不决定跳转。 */
window.MobileBlocks = (() => {
  const e = Blocks.esc,
    tile = Blocks.tile;
  function capsule() {
    return '<div class="wx-capsule" aria-label="微信原生胶囊示意"><span>···</span><i></i><span class="wx-circle"></span></div>';
  }
  function chrome(title, { back = false, landscape = false } = {}) {
    return `${!landscape ? '<div class="status-bar"><b>9:41</b><span>▮▮▮  ᴡɪғɪ ▰</span></div>' : ""}<header class="mini-nav">${back ? '<button data-event="back" class="back" aria-label="返回">‹</button>' : '<span class="nav-seal">太</span>'}<span>${e(title)}</span>${capsule()}</header>`;
  }
  function avatar(name, { bot = false, empty = false } = {}) {
    return `<span class="avatar ${empty ? "empty" : bot ? "bot" : ""}">${empty ? "+" : bot ? "✦" : e(name.slice(-1))}</span>`;
  }
  function seat(player, index) {
    return `<div class="room-seat ${player ? "filled" : ""}">${avatar(player?.name || "", { bot: player?.type === "bot", empty: !player })}<strong>${player ? e(player.name) : "等待好友"}</strong><small>${player ? (player.type === "bot" ? "机器人" : index === 0 ? "我" : "好友") : "空座"}</small>${player ? `<span class="ready-label ${player.ready ? "on" : ""}">${player.ready ? "已准备" : "未准备"}</span>` : ""}</div>`;
  }
  function hand(
    tiles,
    { selected = -1, melds = [], canPlay = true, drawn = true } = {},
  ) {
    return `<div class="mobile-tile-rail">${melds.length ? '<div class="mobile-melds">' + melds.map((m) => Blocks.meld(m)).join("") + "</div>" : ""}<div class="mobile-hand">${tiles.map((t, i) => `<button data-tile="${i}" class="hand-card ${selected === i ? "selected" : ""} ${drawn && i === tiles.length - 1 ? "drawn" : ""}" aria-label="${e(t)}${selected === i ? "，再次点击打出" : ""}" aria-pressed="${selected === i}" ${!canPlay ? 'aria-disabled="true"' : ""}>${tile(t)}${Blocks.maxFlowers.includes(t) ? "<em>留</em>" : ""}</button>`).join("")}</div></div>`;
  }
  function actions(names = []) {
    const order = ["过", "吃", "碰", "杠", "胡"];
    if (!names.some((n) => order.slice(1).includes(n))) return "";
    return (
      '<div class="mobile-actions">' +
      order
        .filter((n) => names.includes(n))
        .map(
          (n) =>
            `<button class="action ${n === "胡" ? "win" : n === "过" ? "pass" : ""}" data-event="${{ 过: "pass", 吃: "chi", 碰: "peng", 杠: "gang", 胡: "win" }[n]}">${n}</button>`,
        )
        .join("") +
      "</div>"
    );
  }
  function waits({ tiles = [], blocked = false, preview = "" } = {}) {
    if (!tiles.length) return "";
    return `<section class="mobile-waits" aria-label="我的听牌提示"><b>${preview ? `打${e(preview)}后听` : "听牌"}</b><div class="wait-cards">${tiles.map((t, i) => `<span>${tile(t)}<small>未见${i ? 2 : 3}</small></span>`).join("")}</div><small>${blocked ? "仅自摸" : "可接炮"} · 未见非墙内</small></section>`;
  }
  function river(tiles, pos) {
    return `<div class="mobile-river ${pos}" aria-label="${e(pos)}弃牌，共${tiles.length}张">${tiles.map((t) => tile(t)).join("")}</div>`;
  }
  function flowers(tiles, pos) {
    return tiles.length
      ? `<div class="mobile-flowers ${pos}" aria-label="已换花${tiles.length}张">${tiles.map((t) => tile(t)).join("")}</div>`
      : "";
  }
  function button(label, event, { secondary = false, disabled = false } = {}) {
    return `<button class="button ${secondary ? "secondary" : ""}" data-event="${event}" ${disabled ? "disabled" : ""}>${e(label)}</button>`;
  }
  function sheet({ title, copy = "", body = "", buttons = [] }) {
    return `<div class="sheet-backdrop"><section class="sheet" role="dialog" aria-modal="true" aria-labelledby="sheet-title"><span class="sheet-grip"></span><h2 id="sheet-title">${e(title)}</h2>${copy ? `<p>${e(copy)}</p>` : ""}${body}<div class="sheet-actions">${buttons.map((b) => button(b.label, b.event, b)).join("")}</div></section></div>`;
  }
  return {
    capsule,
    chrome,
    avatar,
    seat,
    hand,
    actions,
    waits,
    river,
    flowers,
    button,
    sheet,
    tile,
    e,
  };
})();
