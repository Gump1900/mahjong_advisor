"use strict";
const NOTE_REGIONS = [
  { x: 1, y: 1, w: 98, h: 6, px: 2, py: 7 },
  { x: 7, y: 14, w: 86, h: 56, px: 90, py: 15 },
  { x: 26, y: 23, w: 48, h: 42, px: 70, py: 25 },
  { x: 13, y: 67, w: 73, h: 8, px: 13, py: 65 },
  { x: 13, y: 78, w: 73, h: 19, px: 13, py: 79 },
  { x: 27, y: 27, w: 46, h: 46, px: 73, py: 47 },
];
function sceneAnnotations(s) {
  const [id, group, title, note, rule, o] = s;
  const opening = ["ready", "deal"].includes(id),
    isEmpty = id === "empty-table",
    loading = id === "loading-table";
  const response = !!o.discard,
    flower = group === "花牌" || id === "confirm-flower-win";
  const actions = o.actions ?? [];
  const items = [
    {
      title: "入口、身份与桌面工具",
      why: "房间身份和返回入口固定在顶栏，声音与玩法放在右侧，避免混入高频出牌区。",
      interaction:
        "返回先判断对局是否进行中；进行中先说明离开后果。声音只改变本地偏好；玩法可随时查看。",
      empty:
        "尚无房间数据时使用“正在读取房间”，不编造房号；没有连接时禁用开始和动作提交。",
      feedback:
        "加载失败显示重试；恢复时保留原局。多人离开与托管政策尚待确定。",
    },
    {
      title: "四家同排牌列与座位方向",
      why: "四家共用副露＋暗手牌牌列，按座位整体旋转。每多一组副露，暗手牌基准少3张；四杠按18张实体牌的最宽状态预留，不压扁侧家牌。",
      interaction:
        "本人单击选中、再次点击同张出牌；对手手牌不可操作，牌背不暴露牌种。摸牌留14像素间距。",
      empty: opening
        ? "等待开局时四家手牌为空，不用已发好的示例牌冒充等待状态。"
        : "手牌尚未读取时不渲染虚构牌；重试期间保留上次确认的牌并禁用提交。正常对局不应无故变空。",
      feedback:
        "选牌上抬12像素，换选只移动选中态。正式实现出牌等待确认，失败回到可选状态，不重复提交。",
    },
    {
      title: "独立牌河、行动与剩余牌墙",
      why: "四家牌河分别靠近对应座位，按同一25 × 35尺寸整体旋转。中心只表达轮次和牌墙，不放长篇说明。",
      interaction: response
        ? "当前弃牌独立放大并注明来源；响应完成后进入牌河或被取走组成副露。"
        : "等待时手牌不可提交；行动标记变化而非反复弹出“过”。牌河按行扩展，每家最多25张，按9＋9＋7分三行。",
      empty:
        "尚未出牌时牌河保持真实留白；无响应弃牌时不留空卡片。牌墙未知显示“—”，真实0则显示黄庄。",
      feedback:
        "弃牌被吃碰后必须从牌河移除，不能重复展示同一实体。未见张数不是剩余牌墙张数。",
    },
    {
      title: "同排副露、前方花牌与限制",
      why: "副露与暗手牌共用同一排，副露在前、剩余手牌在后。前方只保留花牌与弃牌；花牌记录批次与计分，限制靠近本人。",
      interaction: o.meld
        ? "副露紧接剩余手牌，不另起一排。吃进的牌在组内最左横放；碰杠横牌表示来源。暗杠本人可查，对手只见四背。"
        : flower
          ? "花仍在手牌时标“留”，只有换出后进入单花区；四花暗杠进入面子区。"
          : "没有副露时整条牌列只有暗手牌；前方没有花时自然留白，限制原因仍可查询。",
      empty:
        "没有副露、没有已换花就不画空槽和“暂无”卡片，保留可扩展位置；没有限制就隐藏标签。",
      feedback:
        "过胡、过碰与互锁分别表达；临时限制可解除，互锁持续全局；吃、碰、接弃牌明杠按同来源合计，双方直接支付×3。分数仅为胡后价值，不写成已到账收益。",
    },
    {
      title: "操作、听牌与本人手牌",
      why: "响应固定按过、吃、碰、杠、胡排列，仅显示可用项，整体在手牌上方居中；听牌说明靠左。",
      interaction: actions.length
        ? "此场景可演示：" +
          actions.join("、") +
          "。" +
          (response
            ? "先选动作，再等待响应仲裁；点击不等于已经成功执行。"
            : "选择后反馈结果，不自动替玩家执行其他可选动作。")
        : "此场景没有响应按钮。只有轮到本人出牌阶段才可提交出牌；不能把空操作条当作故障。",
      empty:
        "没有吃碰杠胡可选时整个按钮组不显示，不单独展示过；未听牌时不展示空听牌框。数据缺失显示同步状态，不能当作“没有动作”。",
      feedback: flower
        ? "花牌不可普通打出；留花仍占手牌位。未选任何换花对象前，确认按钮禁用并解释原因。"
        : "出牌选中与提交分开；选中态提示明确。不能接炮时保留原因说明，不展示一个误导性的可点胡按钮。",
    },
    {
      title: o.modal ? "本场景的弹层与结果" : "本场景反馈与空状态",
      why: note,
      interaction: rule,
      empty: o.modal
        ? "组合列表为空时撤回该动作并刷新，不展示可确认的空弹窗；结算分项未到齐时显示“结算中”，不伪造0分。"
        : "无待确认事项时不出现遮罩。军师没有建议可提示等待或主动分析，但不影响正常操作。",
      feedback: o.modal
        ? "取消保留当前局面；确认按钮有未选、可提交、提交中、成功／拒绝状态。拒绝时说明并同步最新状态。"
        : "短提示不遮挡手牌，长期限制保持可查询。弹窗键盘焦点限制在弹层内；关闭返回原触发点。",
    },
  ];
  if (isEmpty || loading) {
    items[5] = {
      title: loading ? "加载、缺失与失败" : "未开局的真实空态",
      why: loading
        ? "数据还没到与确实为空是不同状态，不能在加载期展示示例牌或把未知数字写成0。"
        : "未发牌时保留完整桌面结构，玩家能理解座位与开始操作；不放无意义占位牌。",
      interaction: loading
        ? "禁用出牌和响应；只提供重试或返回。收到完整状态后一次性呈现，不逐块拼成错误牌局。"
        : "点击开始前必须满足房间开局条件。设计工作台的“开始”只演示场景切换。",
      empty:
        "无手牌、无牌河、无副露、无待牌时均不渲染牌或空框；未知牌墙为“—”。",
      feedback: loading
        ? "重试失败保留可重试入口，避免无限空转；恢复原局不重新发牌。"
        : "准备状态变化就地反馈，未准备时解释开局条件，不偷偷开局。",
    };
  }
  if (o.tenpai) {
    items[4] = {
      title:"本人听牌提示：归属与操作分区",
      why:"胡什么是本人的私有辅助信息，常驻本人手牌上方最左侧，别家动作播放时不消失、不闪烁；只在待牌信息变化时更新。不使用视口顶部fixed浮层，不得覆盖对家头像、手牌或牌河。",
      interaction:"每种待牌展示牌面、未见张数、可接炮或仅自摸。多面听横向滚动查看全部；选牌预览写明打某张后听，不能等同当前已听。过吃碰杠胡仍居中独立显示。",
      empty:"未听牌不画空卡；未见为0弱化但保留，未知用—。留花尚未处理时说明原因，不展示失效待牌。",
      feedback:"过胡、无资格花、互锁分别说明仅自摸的原因。动作被拒绝或断线时保留最后确认状态并提示同步；结算后清除待牌提示。"
    };
  }
  return items;
}
function renderAnnotations(s) {
  const notes = sceneAnnotations(s);
  $("annotation-content").innerHTML =
    '<div style="padding:16px 20px 0"><span class="annotation-view-label">' +
    s[1] +
    " / " +
    s[2] +
    "</span></div>" +
    notes
      .map(
        (n, i) =>
          `<section class="annotation-card" id="annotation-${i + 1}"><button data-note="${i + 1}" aria-label="定位注释${i + 1}：${n.title}"><span class="annotation-number">${String(i + 1).padStart(2, "0")}</span>${n.title}</button><dl><dt>为什么这样设计</dt><dd>${n.why}</dd><dt>交互与状态</dt><dd>${n.interaction}</dd><dt>为空／缺失怎么办</dt><dd>${n.empty}</dd><dt>反馈与异常</dt><dd>${n.feedback}</dd></dl></section>`,
      )
      .join("");
  $("design-pins").innerHTML = NOTE_REGIONS.map(
    (r, i) =>
      `<button class="design-pin" data-note="${i + 1}" style="left:${r.px}%;top:${r.py}%" aria-label="查看注释${i + 1}">${String(i + 1).padStart(2, "0")}</button>`,
  ).join("");
  document
    .querySelectorAll("[data-note]")
    .forEach((b) => (b.onclick = () => selectNote(Number(b.dataset.note))));
  selectNote(5, false);
  scaleArtboard();
}
function selectNote(n, scroll = true) {
  document
    .querySelectorAll(".annotation-card,.design-pin")
    .forEach((e) => e.classList.remove("active"));
  $("annotation-" + n)?.classList.add("active");
  document
    .querySelector(`.design-pin[data-note="${n}"]`)
    ?.classList.add("active");
  document.querySelector(".design-region")?.remove();
  const r = NOTE_REGIONS[n - 1],
    box = document.createElement("div");
  box.className = "design-region";
  box.style.cssText = `left:${r.x}%;top:${r.y}%;width:${r.w}%;height:${r.h}%`;
  $("design-pins").append(box);
  if (scroll) {
    const card = $("annotation-" + n),
      panel = document.querySelector(".annotations");
    panel.scrollTo({ top: card.offsetTop - 100, behavior: "smooth" });
  }
}
function scaleArtboard() {
  const stage = document.querySelector(".artboard-stage"),
    game = document.querySelector(".game");
  if (!stage || !game) return;
  const scale = stage.clientWidth / 1100;
  game.style.transform = `scale(${scale})`;
  stage.style.height = 820 * scale + "px";
}
window.addEventListener("resize", scaleArtboard);
new ResizeObserver(scaleArtboard).observe(
  document.querySelector(".artboard-stage"),
);
