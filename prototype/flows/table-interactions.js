"use strict";
/* 流程层：动作、选择、取消与结果编排。仅通过Blocks生成界面。 */
function action(a) {
  if (a === "杠开") resultKind = "gang";
  else if (a === "自摸") resultKind = "nohua";
  else if (a === "胡") resultKind = "ron";
  const o = SCENARIOS[current][5];
  if (a === "过") {
    if (SCENARIOS[current][0] === "ron") dialog("pass");
    else {
      goto("wait");
      toast("已过 · 等待下一次行动");
    }
    return;
  }
  const routes = {
    确认吃牌成功: "chi-done",
    演示响应过期: "expired",
    吃: "chi-options",
    碰: "peng-done",
    留花: "flower-keep",
    换花: "flower-select",
    暗杠: "an-self-done",
    杠: "ming-done",
    加杠: "gang-done",
    逐张换: "flower-select",
    四花暗杠: "flower-four-done",
    演示有人胡: "multi-win",
    自摸: "settlement",
    胡: "settlement",
    杠开: "settlement",
  };
  if (a === "牌型说明") {
    dialog("winTypes");
    return;
  }
  if (a === "花分说明") {
    dialog("flowerInfo");
    return;
  }
  if (routes[a]) {
    goto(routes[a]);
    return;
  }
  if (o.next) goto(o.next);
}
function dialog(kind) {
  if (kind === "leave" && window.prototypeFlowHooks?.requestLeave?.()) return;
  const overlay = $("overlay");
  overlay.hidden = false;
  let title = "",
    copy = "",
    content = "",
    buttons = [],
    small = "太湖麻将";
  if (kind === "ready") {
    title = "四家已就座";
    copy = "太湖玩法 · 你是庄家 · 三位机器人陪打";
    buttons = [["开始对局", () => goto("deal")]];
  }
  if (kind === "chi") {
    title = "选择一种吃法";
    copy = "上家打出3万。选好组合后确认，尚未提交前可返回。";
    content = Blocks.choices({ options: Blocks.chiOptions, kind: "chi" });
    buttons = [
      ["返回", () => goto("chi")],
      [
        "确认吃牌",
        () => {
          chosenChi = Number(overlay.querySelector(".chosen").dataset.choice);
          goto("chi-submit");
        },
      ],
    ];
  }
  if (kind === "flowers") {
    title = "选择本次换出的花";
    copy = "本批只换选中的牌。保留的花继续占手牌位置；新补到的花需重新选择。";
    const fs = SCENARIOS[current][5].fourFlowers
      ? ["中", "中", "中", "中"]
      : ["春", "中"];
    content =
      '<div class="choices">' +
      fs
        .map(
          (t, i) =>
            `<button class="flower-choice" data-choice="${i}" aria-pressed="false">${tile(t)}</button>`,
        )
        .join("") +
      '</div><p id="flower-count">已选0张 · 每张补一张</p>';
    buttons = [
      ["取消", () => goto("flower")],
      ["确认换花", () => goto("flower-chain")],
    ];
  }
  if (kind === "pass") {
    title = "这张牌选择过胡？";
    copy =
      "本次不胡，暂时不能接炮，但仍可自摸。轮到自己，或吃碰取得自己的回合后，即可恢复接炮。";
    buttons = [
      ["返回", () => goto("ron")],
      ["确认过胡", () => goto("ron-blocked")],
    ];
  }
  if (kind === "lock") {
    const o = SCENARIOS[current][5],
      target = o.lockTarget ?? "right";
    title = "这次碰牌成功后，将达第三口";
    copy =
      "你向" +
      Blocks.seatNames[target] +
      "累计取得三口后，双方本局都不能接任何人的炮，只能自摸／杠开；双方直接支付按完整分值×3。";
    content =
      Blocks.callSummary(o.callHistory ?? CallFixtures.rightTwo) +
      "<p>当前仍是两口。只有本次动作经裁判仲裁成功才记第三口；被胡拦截不计。</p>";
    buttons = [
      [
        "取消",
        () => goto(target === "top" ? "call-two-top" : "call-two-right"),
      ],
      ["确认碰牌", () => goto(o.lockResult ?? "locked")],
    ];
  }
  if (kind === "callRelations") {
    title = "三口关系";
    copy = "“三口”不是只算吃牌，吃、碰、接弃牌明杠都算。";
    content = Blocks.callSummary(SCENARIOS[current][5].callHistory ?? []);
    buttons = [
      [
        "知道了",
        () => {
          overlay.hidden = true;
        },
      ],
    ];
    if (Blocks.callState(SCENARIOS[current][5].callHistory ?? []).pairs.length)
      buttons.push(["查看支付示例", () => dialog("callPayment")]);
  }
  if (kind === "callPayment") {
    const state = Blocks.callState(SCENARIOS[current][5].callHistory ?? []),
      partners = state.partners("bottom");
    let total = 0;
    title = "自摸支付示例";
    copy = "假设你自摸，完整单家基础分为10点，逐家按直接互锁关系计算。";
    content =
      ["right", "top", "left"]
        .map((pos) => {
          const multiple = partners.includes(pos) ? 3 : 1,
            totalPaid = 10 * multiple;
          total += totalPaid;
          return (
            '<div class="score-row"><span>' +
            Blocks.seatNames[pos] +
            " · " +
            (multiple === 3 ? "直接互锁" : "未直接互锁") +
            " ×" +
            multiple +
            "</span><strong>−" +
            totalPaid +
            "</strong></div>"
          );
        })
        .join("") +
      '<div class="score-row"><span>你的净收入</span><strong>+' +
      total +
      "</strong></div><p>样例分数。互锁不是全桌统一乘3；黄庄仍为0。</p>";
    buttons = [["返回三口关系", () => dialog("callRelations")]];
  }
  if (kind === "multi") {
    title = "一炮双响";
    copy = "下家放炮，你与对家同时胡牌。胡牌机会不按点击先后截取。";
    content =
      '<div class="score-row"><span>你 · 接炮</span><strong>+10</strong></div><div class="score-row"><span>对家 · 接炮</span><strong>+12</strong></div><div class="score-row"><span>下家 · 放炮</span><strong>−22</strong></div><div class="score-row"><span>上家</span><strong>0</strong></div><p>演示分数 · 实际以裁判结算为准</p>';
    buttons = [
      [
        "返回房间",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
      [
        "再来一局",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
    ];
  }
  if (kind === "result") {
    const type = resultKind;
    const ron = type === "ron";
    const per =
      type === "gang" ? 9 : type === "nohua" ? 6 : type === "ron" ? 3 : 5;
    const label =
      type === "gang"
        ? "杠开"
        : type === "nohua"
          ? "无花自摸"
          : ron
            ? "接炮胡"
            : "普通自摸";
    title = label + " · 本局结束";
    copy =
      type === "nohua"
        ? "示例：无资格花、无额外牌型与互锁，普通自摸固定每家6点。"
        : "示例：1资格花，无额外牌型与互锁。";
    content =
      '<div class="result-tiles">' +
      [
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
        "4条",
        "南",
        "南",
      ]
        .map((t) => tile(t))
        .join("") +
      '</div><div class="score-row"><span>' +
      label +
      (type === "nohua" ? "固定分" : "底分") +
      "</span><strong>" +
      (type === "gang" ? 8 : type === "nohua" ? 6 : ron ? 2 : 4) +
      "</strong></div>" +
      (type === "nohua"
        ? ""
        : '<div class="score-row"><span>资格花</span><strong>1</strong></div>') +
      '<div class="score-row"><span>' +
      (ron ? "放炮者支付" : "另外三家分别支付") +
      "</span><strong>" +
      per +
      '点</strong></div><div class="score-row"><span>你的净得分</span><strong>+' +
      per * (ron ? 1 : 3) +
      "</strong></div><p>设计样例；真实结果和牌谱须由服务端生成。</p>";
    buttons = [
      [
        "返回房间",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
      [
        "再来一局",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
    ];
  }
  if (kind === "draw") {
    title = "黄庄 · 本局结束";
    copy = "牌墙耗尽，无人胡牌。四家净得分均为0，不另计杠收入、查听或罚款。";
    buttons = [
      [
        "返回房间",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
      [
        "再来一局",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
    ];
  }
  if (kind === "reconnect") {
    title = "连接暂时中断";
    copy = "正在恢复当前牌局，请不要重复提交。恢复后仍是原房间、原牌局。";
    buttons = [
      [
        "模拟恢复连接",
        () => {
          goto("turn");
          toast("连接已恢复 · 已同步当前牌局");
        },
      ],
    ];
  }
  if (kind === "leave") {
    title = "离开这局陪打？";
    copy =
      "当前是一名真人与三个机器人的陪打局。确认后中止本局，不生成正常胡牌结算。";
    buttons = [
      [
        "继续打牌",
        () => {
          overlay.hidden = true;
        },
      ],
      [
        "确认离开",
        () => {
          window.prototypeFlowHooks?.leave
            ? prototypeFlowHooks.leave()
            : goto("ready");
          toast("本局已中止 · 原型返回开局场景");
        },
      ],
    ];
  }
  if (kind === "lockedScore") {
    title = "互锁支付示例";
    copy = "赢家与下家、对家直接互锁，基础单家分值为10。";
    content =
      '<div class="score-row"><span>下家 · 直接互锁 ×3</span><strong>−30</strong></div><div class="score-row"><span>对家 · 直接互锁 ×3</span><strong>−30</strong></div><div class="score-row"><span>上家 · 无直接互锁 ×1</span><strong>−10</strong></div><div class="score-row"><span>赢家</span><strong>+70</strong></div>';
    buttons = [
      [
        "返回房间",
        () =>
          window.prototypeFlowHooks?.returnToRoom
            ? prototypeFlowHooks.returnToRoom()
            : goto("ready"),
      ],
    ];
  }
  if (kind === "winTypes") {
    title = "牌型加分";
    copy = "自摸／杠开 与 接炮分别计分，以下为加分，不含底分与资格花。";
    content =
      [
        ["碰碰胡、清一色、七对", "10 / 5"],
        ["豪华、双豪华、三豪华七对", "20/10 · 40/20 · 60/30"],
        ["小吊车", "10 / 5"],
        ["大吊车", "20 / 10"],
      ]
        .map(
          (r) =>
            '<div class="score-row"><span>' +
            r[0] +
            "</span><strong>" +
            r[1] +
            "</strong></div>",
        )
        .join("") +
      "<p>七对系取最高档；大吊车不叠碰碰胡。清一色可与适用牌型叠加。</p>";
    buttons = [
      [
        "知道了",
        () => {
          overlay.hidden = true;
        },
      ],
    ];
  }
  if (kind === "rules") {
    title = "太湖玩法要点";
    copy =
      "花可以留，留花占位。胡前须处理全部留花。接炮需要资格花；过胡须过圈，过碰按牌种。第三口互锁仅能自摸；黄庄全桌零结算。";
    content =
      "<p>暗杠牌种和类别对他人保密。不允许抢加杠胡。完整规则见本原型目录的场景清单及项目确认规则。</p>";
    buttons = [
      [
        "知道了",
        () => {
          overlay.hidden = true;
        },
      ],
    ];
  }
  if (kind === "flowerInfo") {
    title = "花分与杠分";
    copy = "季节花每张1。中发白东持有与单张已换按同款1/2/4/6计算。";
    content =
      "<p>四张同款一次暗杠计12，替代该组阶梯分；移出4张只补1张并占一组面子。杠分仅胡牌时结算，未胡不单独收钱。</p>";
    buttons = [
      [
        "知道了",
        () => {
          overlay.hidden = true;
        },
      ],
    ];
  }
  overlay.innerHTML = Blocks.dialog({
    small,
    title,
    copy,
    content,
    buttons: buttons.map((b) => b[0]),
  });
  const bs = overlay.querySelectorAll(".dialog-actions button");
  bs.forEach((b, i) => (b.onclick = buttons[i][1]));
  if (kind === "chi" || kind === "flowers") {
    const confirm = bs[bs.length - 1];
    confirm.disabled = true;
    overlay.querySelectorAll(".choices button").forEach(
      (b) =>
        (b.onclick = () => {
          if (kind === "chi")
            overlay
              .querySelectorAll(".choices button")
              .forEach((x) => x.classList.remove("chosen"));
          b.classList.toggle("chosen");
          b.setAttribute(
            "aria-pressed",
            String(b.classList.contains("chosen")),
          );
          const n = overlay.querySelectorAll(".chosen").length;
          confirm.disabled = n === 0;
          if (kind === "flowers")
            $("flower-count").textContent = `已选${n}张 · 补${n}张`;
        }),
    );
  }
  overlay.querySelector("button")?.focus();
}
