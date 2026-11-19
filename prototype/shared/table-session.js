"use strict";
const $ = (id) => document.getElementById(id),
  tile = Blocks.tile;
let current = 0,
  selected = -1,
  timer,
  chosenChi = 0,
  resultKind = "normal";
const base = [
  "1万",
  "2万",
  "4万",
  "5万",
  "5饼",
  "5饼",
  "5饼",
  "2条",
  "3条",
  "5条",
  "6条",
  "南",
  "南",
  "8饼",
];
function toast(msg) {
  clearTimeout(timer);
  $("toast").textContent = msg;
  $("toast").classList.add("show");
  timer = setTimeout(() => $("toast").classList.remove("show"), 2800);
}
function goto(id) {
  const i = SCENARIOS.findIndex((s) => s[0] === id);
  if (i >= 0) render(i);
}
function nav() {
  const q = $("search").value.trim();
  let group = "";
  $("scenarios").innerHTML = SCENARIOS.map((s, i) => {
    if (window.prototypeVisibleScene && !prototypeVisibleScene(s[0])) return "";
    if (q && !s.slice(0, 5).join("").includes(q)) return "";
    const heading = s[1] !== group ? `<h3>${s[1]}</h3>` : "";
    group = s[1];
    return (
      heading +
      `<button data-scene="${i}" class="${i === current ? "active" : ""}" aria-current="${i === current ? "true" : "false"}">${String(i + 1).padStart(2, "0")} · ${s[2]}</button>`
    );
  }).join("");
  if (!$("scenarios").innerHTML.trim())
    $("scenarios").innerHTML =
      '<p class="no-results">没有匹配场景。请尝试“吃牌”“留花”或清空搜索。</p>';
  $("scenarios")
    .querySelectorAll("button")
    .forEach((b) => (b.onclick = () => render(Number(b.dataset.scene))));
}
function meld(kind) {
  return Blocks.meld({
    kind,
    source: SCENARIOS[current][5].meldSource ?? "上家",
    choice: chosenChi,
  });
}
function render(i) {
  current = (i + SCENARIOS.length) % SCENARIOS.length;
  const s = SCENARIOS[current],
    o = window.prototypeSceneOptions ? prototypeSceneOptions(s) : s[5];
  renderAnnotations(s);
  document
    .querySelector(".game")
    .classList.toggle("stress-layout", !!o.stressSeat);
  document.querySelector(".game").dataset.stressSeat = o.stressSeat ?? "";
  const calls = Blocks.callState(o.callHistory ?? []);
  $("own-player").innerHTML = Blocks.playerIdentity("bottom", { calls });
  $("back-picker-mount").innerHTML = Blocks.backPicker();
  Blocks.bindBackPicker($("back-picker-mount"));
  selected = o.selected ?? -1;
  history.replaceState(null, "", "#" + s[0]);
  nav();
  if (window.updateFlowReview) updateFlowReview(s);
  $("scene-title").textContent = s[2];
  $("scene-note").textContent = s[3];
  $("scene-rule").textContent = s[4];
  $("progress").textContent = `${current + 1} / ${SCENARIOS.length}`;
  $("overlay").hidden = true;
  $("coach").hidden = !o.coach;
  $("coach-toggle").setAttribute("aria-expanded", String(!!o.coach));
  $("coach-copy").innerHTML = Blocks.coachBrief({ unavailable: !!o.coachError });
  $("toast").classList.remove("show");
  $("seats").innerHTML = Blocks.seats({
    empty: o.empty,
    thinking: o.locked,
    includeSelf: false,
    stressSeat: o.stressSeat,
    opponentKong: o.opponentKong,
    callHistory: o.callHistory ?? [],
  });
  const rivers = [
    ["1条", "9万", "西", "8饼", "9条", "北"],
    ["9饼", "1饼", "北"],
    ["9条", "1万", "西", "8万"],
    ["9万", "1饼", "北", "9饼"],
  ];
  if (o.empty || o.stressSeat) rivers.forEach((r) => (r.length = 0));
  if (o.longRiver)
    rivers.forEach((r) => r.push("1饼", "9条", "西", "8万", "9饼", "北"));
  if (o.riverCounts)
    o.riverCounts.forEach((n, i) => (rivers[i] = Blocks.riverSample(n)));
  $("rivers").innerHTML = ["top", "left", "right", "bottom"]
    .map((position, i) => Blocks.river({ tiles: rivers[i], position }))
    .join("");
  $("wall").textContent = o.unknown ? "—" : (o.wall ?? 62);
  $("turn").textContent = o.empty
    ? o.unknown
      ? "同步中"
      : "等待开局"
    : (o.actor ?? "东 · 你");
  $("clock").textContent = o.empty
    ? o.unknown
      ? "正在读取牌局"
      : "准备后开始"
    : o.locked
      ? "等待对手操作"
      : "等待你的操作";
  $("status-banner").textContent = o.banner ?? "";
  const partners = calls.partners("bottom");
  $("restrictions").textContent = partners.length
    ? "与" +
      partners.map((p) => Blocks.seatNames[p]).join("、") +
      "互锁 · 仅自摸／杠开 · 直接支付×3"
    : (o.restriction ?? "");
  document
    .querySelectorAll("[data-call-details]")
    .forEach((b) => (b.onclick = () => dialog("callRelations")));
  $("hint").innerHTML = o.empty
    ? ""
    : o.tenpai
      ? Blocks.waits({ tiles: o.waitTiles ?? [{tile:"4条", unseen:3, canRon:!o.restriction}, {tile:"7条", unseen:2, canRon:!o.restriction}], preview:o.waitPreview ?? "", restriction:o.restriction ?? "" })
      : (o.hint ?? "太湖玩法 · 留花可择时换出");
  $("last-discard").innerHTML = o.discard
    ? tile(o.discard) + `<small>${o.source ?? "下家"}打出</small>`
    : "";
  const ownMelds = o.callHistory?.length
    ? Blocks.meldsForSeat(o.callHistory)
    : o.stressSeat === "bottom"
      ? Blocks.capacityMelds()
      : o.meld
        ? [{ kind: o.meld, source: o.meldSource ?? "上家", choice: chosenChi }]
        : [];
  $("own-public").innerHTML = Blocks.publicArea({
    flowers:
      o.stressSeat === "bottom"
        ? Blocks.maxFlowers
        : o.publicFlowers
          ? ["春", "中", "中"]
          : [],
  });
  let hand = base.slice(0, o.empty ? 0 : (o.handCount ?? 14));
  if (o.stressSeat === "bottom") hand = ["9饼", "9饼"];
  if (o.callHistory?.length)
    hand = base.slice(0, o.handCount ?? 14 - 3 * ownMelds.length);
  if (o.tenpai)
    hand = [
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
      o.selfWin ? "4条" : "8饼",
    ];
  if (o.flower) hand[hand.length - 2] = "春";
  if (o.modal === "flowers") hand[hand.length - 3] = "中";
  if (o.fourFlowers) hand.splice(0, 4, "中", "中", "中", "中");
  $("own-row").innerHTML = Blocks.tileRow({
    melds: ownMelds,
    handTiles: hand,
    owner: true,
    interactive: true,
    drawn: true,
    selected,
    canDiscard: !(o.locked || o.modal || o.chi || o.discard),
  });
  $("hand")
    .querySelectorAll("button")
    .forEach(
      (b) =>
        (b.onclick = () => {
          if (b.dataset.canDiscard === "false") {
            toast("当前不是出牌阶段，请先完成响应或等待轮到你");
            return;
          }
          const j = Number(b.dataset.index);
          if (["春", "中"].includes(b.dataset.tile)) {
            toast("花牌不能打出，请选择换花或保留");
            return;
          }
          if (selected === j) {
            toast(`已打出${b.dataset.tile} · 模拟反馈`);
            goto("wait");
          } else {
            selected = j;
            $("hand")
              .querySelectorAll("button")
              .forEach((x) => {
                x.classList.toggle("selected", x === b);
                x.setAttribute(
                  "aria-label",
                  x.dataset.tile + (x === b ? "，已选中，再点出牌" : ""),
                );
              });
            $("instruction").textContent =
              `已选${b.dataset.tile} · 再点同一张打出`;
          }
        }),
    );
  $("instruction").textContent = o.empty
    ? o.unknown
      ? "牌局正在同步 · 暂不可操作"
      : "尚未发牌 · 等待明确开始"
    : o.locked
      ? "等待对手时不能出牌"
      : o.modal
        ? "请先完成当前选择"
        : o.discard || o.chi
          ? "请先响应当前弃牌 · 手牌保持完整显示"
          : "点一下选中，再点同一张打出 · 新摸牌在右侧";
  $("actions").innerHTML = Blocks.actions(o.actions ?? []);
  $("actions")
    .querySelectorAll("button")
    .forEach((b) => (b.onclick = () => action(b.dataset.action)));
  if (o.modal) dialog(o.modal);
  if (window.prototypeSceneChanged) prototypeSceneChanged(s);
}
$("search").oninput = nav;
$("prev").onclick = () => render(current - 1);
$("next").onclick = () => render(current + 1);
$("rules").onclick = () => dialog("rules");
$("leave").onclick = () => dialog("leave");
$("coach-toggle").onclick = () => {
  $("coach").hidden = !$("coach").hidden;
  $("coach-toggle").setAttribute("aria-expanded", String(!$("coach").hidden));
};
$("coach-close").onclick = () => {
  $("coach").hidden = true;
  $("coach-toggle").setAttribute("aria-expanded", "false");
};
$("sound").onclick = () => {
  const off = $("sound").getAttribute("aria-pressed") === "true";
  $("sound").setAttribute("aria-pressed", String(!off));
  $("sound").textContent = off ? "声音 开" : "声音 关";
  toast("原型不实际播放音频");
};
$("focus").onclick = () => document.body.classList.add("focus");
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    document.body.classList.remove("focus");
    if (!SCENARIOS[current][5].modal) $("overlay").hidden = true;
  }
  if (
    e.key === "Tab" &&
    !$("overlay").hidden &&
    $("overlay").getClientRects().length
  ) {
    const bs = [...$("overlay").querySelectorAll("button:not(:disabled)")];
    if (e.shiftKey && document.activeElement === bs[0]) {
      e.preventDefault();
      bs.at(-1).focus();
    } else if (!e.shiftKey && document.activeElement === bs.at(-1)) {
      e.preventDefault();
      bs[0].focus();
    }
  }
});
render(
  Math.max(
    0,
    SCENARIOS.findIndex((s) => s[0] === location.hash.slice(1)),
  ),
);
