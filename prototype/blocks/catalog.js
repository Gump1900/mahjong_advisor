"use strict";
const sample = [
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
  "春",
];
const catalog = [
  {
    id: "tile",
    name: "麻将牌",
    states: ["正面", "浅绿牌背 · A副", "淡蓝牌背 · B副", "玉白牌背", "花牌"],
    why: "牌背默认浅绿；A副浅绿、B副淡蓝按整副切换，不在一手牌中交替。另提供玉白预览。牌身与旋转共用同一实现。",
    empty: "未知牌使用牌背，不猜测牌种；不存在的牌不生成元素。",
    boundary: "38 × 54为手牌规格，牌河按其视觉层级使用独立规格。",
    render: (i) => {
      if (i >= 1 && i <= 3)
        Blocks.setBackTheme(["green", "blue", "jade"][i - 1]);
      return (
        '<div class="tile-samples">' +
        (i >= 1 && i <= 3
          ? ["背", "背", "背"]
          : i === 4
            ? ["东", "中", "春"]
            : ["1万", "5饼", "9条"]
        )
          .map((t) => Blocks.tile(t))
          .join("") +
        "</div>"
      );
    },
  },
  {
    id: "waits", name: "本人听牌提示",
    states: ["双面听", "多面听 · 横向滚动", "只能自摸", "未见为零", "选牌后预览", "未听牌"],
    why: "归属本人手牌上方，绝不悬浮到对家。与过吃碰杠胡操作分区；提示不是胡牌按钮。",
    empty: "未听牌不输出空框；未知张数显示—，不能写成0。",
    boundary: "未见包含他家暗牌；只能自摸要说明原因，多面听不截掉第七种以后的待牌。",
    render: i => `<div style="width:190px">${Blocks.waits({tiles:i===5?[]:(i===1?["1万","2万","3万","4万","5万","6万","7万","8万","9万"]:["4条","7条"]).map((tile,j)=>({tile,unseen:i===3?0:j%4,canRon:i!==2})),preview:i===4?"8饼":"",restriction:i===2?"三口互锁 · 本局仅自摸":""})}</div>`,
  },
  {
    id: "hand",
    name: "手牌",
    states: ["本人出牌阶段", "选中", "非本人出牌阶段", "尚未发牌"],
    why: "选择上抬，再点确认；选中状态由调用者传入，不在组件里偷偷出牌。",
    empty: "空数组渲染零张牌，布局保留；同步状态由上层另行说明。",
    boundary:
      "没有缺一门或禁打某门的规则。非本人出牌阶段只是不能提交出牌，牌面保持完整颜色。",
    render: (i) =>
      '<div id="hand">' +
      Blocks.hand({
        tiles: i === 3 ? [] : sample,
        selected: i === 1 ? 3 : -1,
        canDiscard: i !== 2,
      }) +
      "</div>",
  },
  {
    id: "seat",
    name: "四家座位",
    states: [
      "四家已入座",
      "下家思考中",
      "尚未发牌",
      "本人四杠＋24花",
      "上家四杠＋24花",
      "对家四杠＋24花",
      "下家四杠＋24花",
      "本人四组吃牌",
    ],
    why: "本人和另外三家都使用同一条“副露＋剩余手牌”牌列，成组越多暗手牌越少。四杠16张加摸后2张共18张，花区另检24张容量。",
    empty: "尚未发牌保留身份但不渲染牌背；未入座身份另由房间模型提供。",
    boundary: "座位不能获知其他玩家暗牌，展示数据由上层脱敏。",
    render: (i) =>
      '<div class="table-area">' +
      Blocks.seats({
        empty: i === 2,
        thinking: i === 1,
        stressSeat:
          i >= 3 ? ["bottom", "left", "top", "right", "bottom"][i - 3] : null,
        chows: i === 7,
      }) +
      "</div>",
  },
  {
    id: "meld",
    name: "副露",
    states: [
      "吃",
      "碰上家",
      "碰对家",
      "碰下家",
      "明杠",
      "加杠",
      "本人暗杠",
      "对手暗杠",
      "为空",
    ],
    why: "明杠与加杠统一展示四张明牌，不叠放。碰／杠的横牌只表示来源家；吃进的那张牌移到最左并横放。暗杠仍四背。",
    empty: "无副露不输出空框；留花不应误放入副露区。",
    boundary: "组件不累计口数，不负责计算结算，也不决定暗杠是否允许。",
    render: (i) =>
      Blocks.meld({
        kind: ["chi", "peng", "peng", "peng", "ming", "add", "an", "an", null][
          i
        ],
        source: i === 2 ? "对家" : i === 3 ? "下家" : "上家",
        owner: i !== 7,
      }),
  },
  {
    id: "actions",
    name: "操作按钮组",
    states: ["吃碰响应", "可胡", "无动作", "五项顺序", "胡与过", "无可选响应"],
    why: "固定顺序：过、吃、碰、杠、胡。只显示当前可用项，整个组在手牌上方居中，出现或消失不会改变相对顺序。",
    empty: "无动作时输出空内容，不留下空操作条。",
    boundary: "组件不判断规则，不自己把点击变成吃碰成功。",
    render: (i) =>
      '<div id="actions">' +
      Blocks.actions(
        i === 2
          ? []
          : i === 3
            ? ["胡", "杠", "碰", "吃", "过"]
            : i === 4
              ? ["过", "胡"]
              : i === 5
                ? []
                : i === 1
                  ? ["过", "碰", "杠", "胡"]
                  : ["过", "吃", "碰"],
      ) +
      "</div>",
  },
  {
    id: "dialog",
    name: "选择与确认弹窗",
    states: ["吃牌选择", "过胡提醒", "空组合"],
    why: "统一标题、内容、选择区和确认按钮，避免每条流程另造一种弹窗。",
    empty: "空组合禁用确认，提示刷新；不能确认一个没有选项的吃牌动作。",
    boundary: "弹窗只渲染；选择、取消和确认后去哪里由Flow控制。",
    render: (i) =>
      Blocks.dialog({
        title:
          i === 0
            ? "选择一种吃法"
            : i === 1
              ? "这张牌选择过胡？"
              : "可选组合已变化",
        copy:
          i === 0
            ? "选择后才可确认，返回不提交。"
            : i === 1
              ? "本次不胡，暂时不能接炮，但仍可自摸。轮到自己，或吃碰取得自己的回合后，即可恢复接炮。"
              : "没有可用组合，请返回并同步最新牌局。",
        content: i === 0 ? Blocks.choices({ options: Blocks.chiOptions }) : "",
        buttons:
          i === 1
            ? ["返回", "确认过胡"]
            : ["返回", i === 2 ? "暂无可选组合" : "确认吃牌"],
      }),
  },
  {
    id: "river",
    name: "牌河",
    states: [
      "空牌河",
      "1张弃牌",
      "9张 · 一行",
      "10张 · 换行",
      "24张",
      "25张上限",
      "四家各25张",
    ],
    why: "每家按9＋9＋7排列25张，四家使用同一25 × 35牌身并整体旋转。中央为行动区，四面牌河不混在一起。",
    empty:
      "没有弃牌时不绘制空框；被吃碰杠取走的弃牌从牌河移除，不留一张重复实体。",
    boundary:
      "25张是本轮确认的单家容量边界。四家各25张是布局压力样例，不代表一局合法完整牌谱；超过上限需报错，不静默裁剪。",
    render: (i) =>
      i === 6
        ? '<div class="table-area">' +
          Blocks.seats({ empty: true }) +
          ["top", "left", "right", "bottom"]
            .map((position) =>
              Blocks.river({ tiles: Blocks.riverSample(25), position }),
            )
            .join("") +
          '<div class="compass"><div class="wall">四家牌河</div><strong>25 × 4</strong><p>布局压力样例</p></div></div>'
        : '<div class="river-single">' +
          Blocks.river({
            tiles: Blocks.riverSample([0, 1, 9, 10, 24, 25][i]),
            position: "bottom",
          }) +
          "</div>",
  },
  {
    id: "tile-row",
    name: "副露＋手牌同排",
    states: [
      "未副露 · 14张",
      "吃一组＋11张",
      "两组副露＋8张",
      "三组副露＋5张",
      "四吃＋2张",
      "四杠＋2张",
    ],
    why: "副露和暗手牌共用一条横向牌列，副露在前，剩余手牌在后；有杠会多出实体牌，按四杠18张的最宽情况预留。",
    empty: "没有副露时副露段不占宽；尚未发牌时整列为空，不预摆示例牌。",
    boundary:
      "四家复用同一个tileRow组件，只旋转整个牌列。前方只放花牌和弃牌。例子是摸后／吃碰后待出牌状态，按14−3×组数计算暗手牌。",
    render: (i) => {
      const groups =
        i === 0
          ? []
          : i === 1
            ? [{ kind: "chi" }]
            : i === 2
              ? [
                  { kind: "chi" },
                  { kind: "peng", tiles: ["6饼", "6饼", "6饼"] },
                ]
              : i === 3
                ? [
                    { kind: "chi" },
                    { kind: "peng", tiles: ["6饼", "6饼", "6饼"] },
                    { kind: "ming", tiles: Array(4).fill("8条") },
                  ]
                : i === 4
                  ? [
                      ["1万", "2万", "3万"],
                      ["4万", "5万", "6万"],
                      ["1饼", "2饼", "3饼"],
                      ["4条", "5条", "6条"],
                    ].map((tiles) => ({
                      kind: "chi",
                      tiles,
                      claimed: tiles[2],
                    }))
                  : Blocks.capacityMelds();
      return Blocks.tileRow({
        melds: groups,
        handTiles:
          groups.length === 4
            ? ["9饼", "9饼"]
            : sample.slice(0, 14 - 3 * groups.length),
        owner: true,
        interactive: true,
        drawn: true,
      });
    },
  },
  {
    id: "call-lock",
    name: "三口关系",
    states: [
      "向下家两口",
      "碰下家三口",
      "碰对家三口",
      "吃碰明杠混合",
      "双向2＋1未锁",
      "第三口被拦截",
      "分别互锁两家",
    ],
    why: "按取得者→弃牌来源分别计口，吃、碰、接弃牌明杠合计；达到同向三口后，互锁双方都有标记。",
    empty: "没有互锁就不显示徽标，也不显示1/3、2/3口进度；口数仅保留在明细。未成功的第三口不计入。",
    boundary:
      "本组件仅演示已确认的规则状态，不修改真实裁判。互锁双方都禁接炮；直接支付×3，不给全桌统一乘3，也不传递给第三人。",
    render: (i) => {
      const events = [
        CallFixtures.rightTwo,
        CallFixtures.rightThree,
        CallFixtures.topThree,
        CallFixtures.mixed,
        CallFixtures.twoWay,
        CallFixtures.rejected,
        CallFixtures.twoLocks,
      ][i];
      return (
        '<div class="call-block-preview"><div class="call-block-badges">' +
        ["bottom", "right", "top", "left"]
          .map(
            (position) =>
              "<div><b>" +
              Blocks.seatNames[position] +
              "</b>" +
              Blocks.callBadge(position, Blocks.callState(events)) +
              "</div>",
          )
          .join("") +
        "</div>" +
        Blocks.callSummary(events) +
        "</div>"
      );
    },
  },
];
let active = 0,
  state = 0;
function render() {
  const c = catalog[active];
  if (c.id === "seat" && state >= 3)
    document.getElementById("catalog-feedback")?.remove();
  document.getElementById("block-tabs").innerHTML = catalog
    .map(
      (x, i) =>
        `<button data-block="${i}" class="${i === active ? "active" : ""}">${x.name}</button>`,
    )
    .join("");
  document.getElementById("block-states").innerHTML = c.states
    .map(
      (x, i) =>
        `<button data-state="${i}" class="${i === state ? "active" : ""}">${x}</button>`,
    )
    .join("");
  document.getElementById("block-preview").className =
    "gallery-stage game block-" + c.id;
  document.getElementById("block-preview").innerHTML = c.render(state);
  document.getElementById("block-notes").innerHTML =
    `<span class="eyebrow">组件契约</span><h2>${c.name}</h2><h3>为什么这样设计</h3><p>${c.why}</p><h3>为空怎么办</h3><p>${c.empty}</p><h3>边界</h3><p>${c.boundary}</p><h3>唯一维护位置</h3><p><code>blocks/ui.js</code><br>尺寸：<code>shared/tokens.css</code><br>共用样式：<code>shared/review.css</code></p>`;
  document.querySelectorAll("[data-block]").forEach(
    (b) =>
      (b.onclick = () => {
        active = Number(b.dataset.block);
        state = 0;
        render();
      }),
  );
  document.querySelectorAll("[data-state]").forEach(
    (b) =>
      (b.onclick = () => {
        state = Number(b.dataset.state);
        render();
      }),
  );
  const preview = document.getElementById("block-preview");
  preview.classList.toggle("river-board", c.id === "river" && state === 6);
  if (c.id === "dialog") {
    const bs = preview.querySelectorAll(".dialog-actions button");
    bs[1].disabled = state !== 1;
    preview.querySelectorAll(".chi-choice").forEach(
      (b) =>
        (b.onclick = () => {
          preview
            .querySelectorAll(".chi-choice")
            .forEach((x) => x.classList.remove("chosen"));
          b.classList.add("chosen");
          bs[1].disabled = false;
        }),
    );
    bs.forEach(
      (b) =>
        (b.onclick = () => {
          document.getElementById("catalog-feedback").textContent =
            "这里只检查组件反馈。完整跳转请进入 Flow → 吃牌。";
        }),
    );
  }
  if (!document.getElementById("catalog-feedback"))
    preview.insertAdjacentHTML(
      "afterend",
      '<p id="catalog-feedback" class="catalog-feedback" aria-live="polite">组件状态由上方切换；流程行为请在 Flow 中检查。</p>',
    );
  if (c.id === "seat" || (c.id === "river" && state === 6)) {
    const frame = preview.parentElement;
    const scale = frame.clientWidth / 1100;
    preview.style.cssText = `width:1100px;height:820px;min-width:0;transform:scale(${scale});transform-origin:top left`;
    frame.style.height = 820 * scale + "px";
    preview.classList.toggle("capacity-board", state >= 3);
  } else {
    preview.removeAttribute("style");
    preview.parentElement.style.height = "";
  }
  history.replaceState(null, "", "#" + c.id);
}
const initial = catalog.findIndex((x) => x.id === location.hash.slice(1));
active = initial < 0 ? 0 : initial;
render();

window.addEventListener("resize", () => {
  const preview = document.getElementById("block-preview");
  preview.classList.toggle(
    "river-board",
    catalog[active].id === "river" && state === 6,
  );
  if (
    !preview.classList.contains("block-seat") &&
    !preview.classList.contains("river-board")
  )
    return;
  const frame = preview.parentElement,
    scale = frame.clientWidth / 1100;
  preview.style.transform = `scale(${scale})`;
  frame.style.height = 820 * scale + "px";
});
