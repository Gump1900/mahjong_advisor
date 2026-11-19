"use strict";
/* Block层：纯展示函数。不得读取SCENARIOS/current，也不得决定流程跳转。 */
window.Blocks = (() => {
  const assets = new URL(
    "../../src/simulation/webapp/tiles/",
    document.currentScript.src,
  ).href;
  const suits = { 万: "Man", 饼: "Pin", 条: "Sou" },
    specials = {
      东: "Ton",
      南: "Nan",
      西: "Shaa",
      北: "Pei",
      中: "Chun",
      发: "Hatsu",
      白: "HakuLocal",
      春: "Flower1",
      夏: "Flower2",
      秋: "Flower3",
      冬: "Flower4",
      梅: "Flower5",
      兰: "Flower6",
      竹: "Flower7",
      菊: "Flower8",
      背: "Back",
    };
  const esc = (x) =>
    String(x ?? "").replace(
      /[&<>"']/g,
      (c) =>
        ({
          "&": "&amp;",
          "<": "&lt;",
          ">": "&gt;",
          '"': "&quot;",
          "'": "&#39;",
        })[c],
    );
  const backs = new URL("../shared/assets/", document.currentScript.src).href;
  let backTheme = "green";
  function setBackTheme(theme) {
    if (!["green", "blue", "jade"].includes(theme)) return;
    backTheme = theme;
    document.documentElement.dataset.tileBack = theme;
    document
      .querySelectorAll("img[data-tile-back]")
      .forEach((img) => (img.src = backs + "back-" + theme + ".svg"));
  }
  function backPicker() {
    return (
      '<label class="back-picker">牌背 <select data-back-picker aria-label="牌背颜色">' +
      [
        ["green", "浅绿 · A副"],
        ["blue", "淡蓝 · B副"],
        ["jade", "玉白"],
      ]
        .map(
          ([k, v]) =>
            '<option value="' +
            k +
            '" ' +
            (k === backTheme ? "selected" : "") +
            ">" +
            v +
            "</option>",
        )
        .join("") +
      "</select></label>"
    );
  }
  function bindBackPicker(root = document) {
    root.querySelectorAll("[data-back-picker]").forEach((el) => {
      el.value = backTheme;
      el.onchange = () => setBackTheme(el.value);
    });
  }
  function tile(t, cls = "") {
    const m = /^([1-9])([万饼条])$/.exec(t);
    const back = t === "背" || (!m && !specials[t]);
    const src = back
      ? backs + "back-" + backTheme + ".svg"
      : assets + (m ? suits[m[2]] + m[1] : specials[t]) + ".svg";
    return `<img class="tile ${back ? "tile-back " : ""}${esc(cls)}" ${back ? "data-tile-back" : ""} draggable="false" src="${src}" alt="${esc(t)}" title="${esc(t)}">`;
  }
  const chiOptions = [
    ["1万", "2万", "3万"],
    ["2万", "3万", "4万"],
    ["3万", "4万", "5万"],
  ];
  function meld({
    kind,
    source = "上家",
    choice = 0,
    owner = true,
    tiles,
    claimed = "3万",
    callNumber,
  } = {}) {
    if (!kind) return "";
    let ts =
      tiles ??
      (kind === "chi"
        ? chiOptions[choice]
        : Array(kind === "peng" ? 3 : 4).fill(kind === "an" ? "背" : "5饼"));
    // 吃只来自上家：把实际吃进的牌移到最左，其余自持牌保持顺序。
    if (kind === "chi") {
      const at = ts.indexOf(claimed);
      if (at >= 0) ts = [ts[at], ...ts.filter((_, i) => i !== at)];
    }
    const index =
      kind === "chi"
        ? 0
        : source === "对家"
          ? 1
          : source === "下家"
            ? ts.length - 1
            : 0;
    const name =
      kind === "chi"
        ? "吃"
        : kind === "peng"
          ? "碰"
          : kind === "an"
            ? "暗杠"
            : "明杠";
    return `<div class="meld" data-kind="${esc(kind)}"><div class="meld-cards">${ts.map((t, i) => `<span class="meld-card ${kind !== "an" && i === index ? "claimed" : ""}">${tile(t)}</span>`).join("")}</div><small>${kind === "an" ? (owner ? "暗杠 · 仅本人可查" : "暗杠 · 牌种未知") : name + " · " + esc(source)}</small></div>`;
  }
  const maxFlowers = [
    "中",
    "中",
    "中",
    "中",
    "发",
    "发",
    "发",
    "发",
    "白",
    "白",
    "白",
    "白",
    "东",
    "东",
    "东",
    "东",
    "春",
    "夏",
    "秋",
    "冬",
    "梅",
    "兰",
    "竹",
    "菊",
  ];
  function publicArea({ melds = [], flowers = [], owner = true } = {}) {
    return `<div class="public-area" data-meld-count="${melds.length}" data-flower-count="${flowers.length}">${melds.length ? '<div class="public-melds">' + melds.map((m) => meld({ ...m, owner })).join("") + "</div>" : ""}${flowers.length ? '<div class="public-flowers"><span class="public-label">单张已换花 · ' + flowers.length + '张</span><div class="flower-grid">' + flowers.map((t) => tile(t)).join("") + "</div></div>" : ""}</div>`;
  }
  function capacityMelds() {
    return ["1万", "2饼", "3条", "南"].map((t) => ({
      kind: "ming",
      source: "上家",
      tiles: Array(4).fill(t),
    }));
  }
  function hand({
    tiles = [],
    selected = -1,
    canDiscard = true,
    drawn = true,
  } = {}) {
    return tiles
      .map(
        (t, j) =>
          `<button aria-label="${esc(t)}${j === selected ? "，已选中，再点出牌" : ""}" class="${drawn && j === tiles.length - 1 ? "drawn " : ""}${j === selected ? "selected " : ""}${["东", "中", "发", "白", "春", "夏", "秋", "冬", "梅", "兰", "竹", "菊"].includes(t) ? "flower" : ""}" ${!canDiscard ? 'aria-disabled="true"' : ""} data-can-discard="${canDiscard}" data-index="${j}" data-tile="${esc(t)}">${tile(t)}</button>`,
      )
      .join("");
  }
  function tileRow({
    melds = [],
    handTiles = [],
    owner = false,
    interactive = false,
    selected = -1,
    canDiscard = true,
    drawn = false,
  } = {}) {
    return `<div class="player-tile-row" data-meld-count="${melds.length}" data-hand-count="${handTiles.length}"><div class="rail-melds">${melds.map((m) => meld({ ...m, owner })).join("")}</div><div ${interactive ? 'id="hand"' : ""} class="rail-closed">${interactive ? hand({ tiles: handTiles, selected, canDiscard, drawn }) : handTiles.map((t) => tile(t)).join("")}</div></div>`;
  }
  const seatOrder = ["bottom", "right", "top", "left"],
    seatNames = { bottom: "你", right: "下家", top: "对家", left: "上家" };
  function callState(events = []) {
    const counts = {};
    const parts = {};
    for (const e of events) {
      if (
        e.successful === false ||
        !["chi", "peng", "ming"].includes(e.kind) ||
        !seatOrder.includes(e.from) ||
        !seatOrder.includes(e.source) ||
        e.from === e.source
      )
        continue;
      const key = e.from + ":" + e.source;
      counts[key] = (counts[key] ?? 0) + 1;
      parts[key] ??= { chi: 0, peng: 0, ming: 0 };
      parts[key][e.kind]++;
    }
    const pairKeys = new Set();
    for (const [key, count] of Object.entries(counts)) {
      if (count >= 3) pairKeys.add(key.split(":").sort().join(":"));
    }
    const pairs = [...pairKeys].map((k) => k.split(":"));
    return {
      counts,
      parts,
      pairs,
      partners: (position) =>
        pairs
          .filter((pair) => pair.includes(position))
          .map((pair) => pair.find((s) => s !== position)),
    };
  }
  function callBadge(position, state = callState()) {
    const partners = state.partners(position);
    if (partners.length)
      return `<button class="call-badge is-locked" data-call-details title="${esc(partners.map((p) => seatNames[p]).join("、"))}互锁：不能接炮；双方直接支付×3">互锁 ×3 · 与${partners.map((p) => seatNames[p]).join("、")}</button>`;
    return "";
  }
  function callSummary(events = []) {
    const state = callState(events);
    const rows = Object.entries(state.counts);
    return `<div class="call-summary"><p class="call-summary-rule">同一个人向同一家成功取得三口：吃、碰、接弃牌明杠合计。双方禁接所有人的炮，仍可自摸／杠开；双方直接支付×3。</p>${
      rows.length
        ? rows
            .map(([key, n]) => {
              const [from, source] = key.split(":"),
                p = state.parts[key];
              return `<div class="call-summary-row" data-count="${n}"><span>${seatNames[from]} → ${seatNames[source]}</span><strong>${n}口</strong><small>吃${p.chi} · 碰${p.peng} · 明杠${p.ming}</small></div>`;
            })
            .join("")
        : "<p>尚无吃碰明杠记录。</p>"
    }<p class="call-summary-result">${state.pairs.length ? state.pairs.map((pair) => pair.map((p) => seatNames[p]).join(" ↔ ") + "：互锁，双方禁接炮，直接支付×3").join("<br>") : "尚未互锁；不同来源或反方向的口数不合并。"}</p></div>`;
  }
  function meldsForSeat(events = [], position = "bottom") {
    const seen = {};
    return events
      .filter(
        (e) =>
          e.successful !== false &&
          e.from === position &&
          ["chi", "peng", "ming"].includes(e.kind),
      )
      .map((e) => {
        const d =
          (seatOrder.indexOf(e.source) - seatOrder.indexOf(position) + 4) % 4;
        seen[e.source] = (seen[e.source] ?? 0) + 1;
        return {
          kind: e.kind,
          tiles: e.tiles,
          claimed: e.claimed,
          source: { 1: "下家", 2: "对家", 3: "上家" }[d],
          callNumber: seen[e.source],
        };
      });
  }
  function playerIdentity(
    pos = "bottom",
    { thinking = false, calls = callState(), profile = null } = {},
  ) {
    const index = ["top", "left", "right", "bottom"].indexOf(pos);
    if (profile)
      return `<span class="${pos === "bottom" ? "own-avatar" : "avatar"}">${esc(profile.name.slice(0, 1))}</span><div>${esc(profile.name)} · ${seatNames[pos]}<small>${profile.type === "bot" ? "机器人" : "真人"}${profile.dealer ? " · 庄" : ""}</small>${callBadge(pos, calls)}</div>`;
    return `<span class="${pos === "bottom" ? "own-avatar" : "avatar"}">${["竹", "云", "山", "我"][index]}</span><div>${["竹影 · 对家", "云水 · 上家", "远山 · 下家", "林间听雨 · 你"][index]}<small>${pos === "bottom" ? "东 · 庄" : thinking && pos === "right" ? "机器人 · 思考中" : "机器人 · 在线"}</small>${callBadge(pos, calls)}</div>`;
  }
  function seats({
    empty = false,
    thinking = false,
    includeSelf = true,
    stressSeat = null,
    chows = false,
    opponentKong = false,
    callHistory = [],
  } = {}) {
    const positions = includeSelf
      ? ["top", "left", "right", "bottom"]
      : ["top", "left", "right"];
    return positions
      .map((pos) => {
        const stress = stressSeat === pos;
        let melds =
          chows && stress
            ? [
                ["1万", "2万", "3万"],
                ["4万", "5万", "6万"],
                ["1饼", "2饼", "3饼"],
                ["4条", "5条", "6条"],
              ].map((tiles) => ({ kind: "chi", tiles, claimed: tiles[2] }))
            : stress
              ? capacityMelds()
              : [];
        if (callHistory.length) melds = meldsForSeat(callHistory, pos);
        if (opponentKong && pos === "top") melds = [{ kind: "an" }];
        const handTiles =
          pos === "bottom"
            ? empty
              ? []
              : stress
                ? ["9饼", "9饼"]
                : [
                    "1万",
                    "2万",
                    "3万",
                    "4万",
                    "5万",
                    "6万",
                    "2饼",
                    "3饼",
                    "4饼",
                    "2条",
                    "3条",
                    "南",
                    "南",
                    "8饼",
                  ]
            : Array(
                empty
                  ? 0
                  : stress
                    ? 2
                    : opponentKong && pos === "top"
                      ? 11
                      : 13 - 3 * melds.length,
              ).fill("背");
        return `<div class="seat ${pos}" data-seat="${pos}">${playerIdentity(pos, { thinking, calls: callState(callHistory) })}</div><div class="seat-rail ${pos}">${tileRow({ melds, handTiles, owner: pos === "bottom" })}</div>${stress && !chows ? '<div class="seat-public ' + pos + '">' + publicArea({ flowers: maxFlowers, owner: pos === "bottom" }) + "</div>" : ""}`;
      })
      .join("");
  }
  function coachBrief({ unavailable = false } = {}) {
    if (unavailable) return '<p class="coach-reason">建议暂不可用</p>';
    return '<h3 class="coach-headline">建议打8饼</h3><p class="coach-reason">保留23条、56条两组搭子。</p><div class="coach-opponents">'+["下家","对家","上家"].map(seat=>`<div class="coach-opponent"><span>${seat}</span><strong class="unknown">无法推断</strong></div>`).join("")+'</div><details><summary>详细分析</summary><p>原型示例：实际牌效、候选和公开证据由策略结果提供。</p></details>';
  }
  function waits({ tiles = [], preview = "", restriction = "" } = {}) {
    if (!tiles.length) return "";
    return `<section class="own-waits" aria-label="我的听牌提示"><strong>${preview ? `打${esc(preview)}后听` : "我听的牌"}</strong><div class="own-waits-list">${tiles.map(w => `<span class="own-wait${w.unseen === 0 ? " exhausted" : ""}">${tile(w.tile)}<small>未见${w.unseen ?? "—"}</small><small>${w.canRon ? "可接炮" : "仅自摸"}</small></span>`).join("")}</div><small class="own-waits-note">${esc(restriction || "未见含他家暗牌，非牌墙剩余")}</small></section>`;
  }
  const actionOrder = ["过", "吃", "碰", "杠", "胡"];
  function actions(labels = []) {
    const aliases = {
      暗杠: "杠",
      加杠: "杠",
      四花暗杠: "杠",
      自摸: "胡",
      杠开: "胡",
    };
    const hasClaim = labels.some((a) =>
      ["吃", "碰", "杠", "胡"].includes(aliases[a] ?? a),
    );
    const canonical = actionOrder
      .map((name) => {
        if (name === "过" && !hasClaim) return null;
        const original = labels.find((a) => (aliases[a] ?? a) === name);
        return original ? { name, original } : null;
      })
      .filter(Boolean);
    const helpers = labels.filter(
      (a) => !actionOrder.includes(aliases[a] ?? a),
    );
    return (
      canonical
        .map(
          ({ name, original }) =>
            `<button class="${name === "过" ? "pass" : name === "胡" ? "win" : ""}" data-action="${esc(original)}">${name}</button>`,
        )
        .join("") +
      helpers
        .map(
          (a) =>
            `<button class="utility-action" data-action="${esc(a)}">${esc(a)}</button>`,
        )
        .join("")
    );
  }
  const riverLimit = 25,
    riverColumns = 9;
  function riverSample(count = 25) {
    const faces = ["万", "饼", "条"].flatMap((s) =>
      Array.from({ length: 9 }, (_, i) => i + 1 + s),
    );
    return Array.from({ length: count }, (_, i) => faces[i % faces.length]);
  }
  function river({ tiles = [], position = "bottom", latest = -1 } = {}) {
    if (!["top", "left", "right", "bottom"].includes(position))
      throw new Error("未知牌河方向");
    return `<div class="river ${position}" data-river-count="${tiles.length}" aria-label="${{ top: "对家", left: "上家", right: "下家", bottom: "本人" }[position]}牌河，${tiles.length}张">${tiles.length ? '<span class="river-count">' + tiles.length + " / " + riverLimit + "</span>" : ""}${tiles.map((t, i) => tile(t, i === latest ? "latest-discard" : "")).join("")}${tiles.length > riverLimit ? '<span class="river-warning">超出25张，请校验牌谱</span>' : ""}</div>`;
  }
  function choices({ options = [], kind = "chi" } = {}) {
    return (
      '<div class="choices">' +
      options
        .map(
          (ts, i) =>
            `<button class="${esc(kind)}-choice" data-choice="${i}" aria-pressed="false" aria-label="选择${ts.map(esc).join("、")}">${ts.map((t) => tile(t)).join("")}</button>`,
        )
        .join("") +
      "</div>"
    );
  }
  function dialog({
    small = "太湖麻将",
    title = "",
    copy = "",
    content = "",
    buttons = [],
  } = {}) {
    return `<section class="dialog" role="dialog" aria-modal="true" aria-labelledby="dialog-title"><small>${esc(small)}</small><h2 id="dialog-title">${esc(title)}</h2><p>${esc(copy)}</p>${content}<div class="dialog-actions">${buttons.map((b, i) => `<button class="${i === 0 && buttons.length > 1 ? "secondary" : ""}">${esc(b)}</button>`).join("")}</div></section>`;
  }
  function roomSeat({ name = "", label = "空座", ready = false } = {}) {
    return `<div class="room-seat"><strong>${name ? esc(name.slice(0, 1)) : "＋"}</strong><p>${esc(name || "等待入座")}</p><small>${esc(label)}${name ? (ready ? " · 已准备" : " · 未准备") : ""}</small></div>`;
  }
  return {
    coachBrief,
    waits,
    tile,
    callState,
    callBadge,
    callSummary,
    meldsForSeat,
    seatNames,
    tileRow,
    river,
    riverSample,
    riverLimit,
    riverColumns,
    setBackTheme,
    backPicker,
    bindBackPicker,
    playerIdentity,
    publicArea,
    maxFlowers,
    capacityMelds,
    meld,
    hand,
    seats,
    actions,
    choices,
    dialog,
    roomSeat,
    chiOptions,
    esc,
  };
})();
