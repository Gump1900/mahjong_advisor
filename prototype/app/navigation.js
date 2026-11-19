"use strict";
/* App只组装页面；房间和产品流程状态由ProductFlow维护。 */
window.PrototypeApp = (() => {
  const root = document.getElementById("prototype-root"),
    entry = document.createElement("section"),
    bar = document.createElement("div");
  entry.className = "product-entry";
  document.body.append(entry);
  bar.className = "app-routebar";
  root.querySelector("main").prepend(bar);
  const key = "taihu-product-prototype",
    esc = Blocks.esc;
  let s = ProductFlow.blank(),
    review = false,
    rendering = false;
  try {
    const saved = JSON.parse(sessionStorage.getItem(key));
    if (saved?.page && typeof saved.nickname === "string") s = saved;
  } catch {}
  function save() {
    try {
      sessionStorage.setItem(key, JSON.stringify(s));
    } catch {}
  }
  function dispatch(event, payload = {}) {
    s = ProductFlow.transition(s, event, payload);
    save();
    render();
  }
  function path() {
    return (
      '<div class="product-stepper">' +
      [
        ["lobby", "大厅"],
        ["room", "房间"],
        ["table", "对局"],
        ["result", "结算"],
      ]
        .map(
          ([id, label], i) =>
            '<span class="' +
            (s.page === id ? "current" : "") +
            '">' +
            (i + 1) +
            " · " +
            label +
            "</span>",
        )
        .join("<i>→</i>") +
      "</div>"
    );
  }
  function reviewNotes() {
    const n = ProductFlow.notes[s.page] ?? ProductFlow.notes.lobby;
    return (
      '<small class="eyebrow">FLOW NOTES / 流程说明</small><h2>' +
      n.title +
      "</h2><dl><dt>为什么这样设计</dt><dd>" +
      n.why +
      "</dd><dt>交互与权限</dt><dd>" +
      n.interaction +
      "</dd><dt>为空怎么办</dt><dd>" +
      n.empty +
      "</dd><dt>异常与恢复</dt><dd>" +
      n.failure +
      "</dd></dl>" +
      simulationControls()
    );
  }
  function simulationControls() {
    return (
      '<section class="product-sim"><b>原型模拟事件</b><p>用于设计评审，不是真实联网功能。</p>' +
      (s.page === "room"
        ? '<button data-sim="remoteJoin">模拟好友加入</button><button data-sim="remoteReady">模拟其他真人准备</button><button data-sim="remoteLeave">模拟好友离开</button>' +
          (!ProductFlow.owner(s)
            ? '<button data-sim="remoteStart">模拟房主开始</button>'
            : "")
        : "") +
      (s.page === "table"
        ? '<button data-sim="nextEvent">推进下一事件</button><button data-sim="win">模拟本局自摸</button><button data-sim="draw">模拟黄庄</button><button data-sim="multi">模拟一炮多响</button>'
        : "") +
      (s.room && s.page !== "result"
        ? '<button data-sim="disconnect">模拟断线</button>'
        : "") +
      (s.connection === "offline"
        ? '<button data-sim="reconnect">恢复连接</button>'
        : "") +
      '<a href="../flows/product.html">查看完整流程地图 →</a><a href="index.html?review=1#turn">查看牌桌场景库 →</a></section>'
    );
  }
  function shell(title, content) {
    root.hidden = true;
    entry.hidden = false;
    document.body.classList.remove("focus");
    entry.innerHTML =
      '<header class="entry-nav"><strong>太湖麻将</strong><a href="../index.html">Block / Flow / App · 原型导航</a></header>' +
      path() +
      '<div class="product-layout"><section class="entry-content"><small>太湖麻将 · 访客体验</small><h1>' +
      title +
      "</h1>" +
      content +
      (s.notice
        ? '<p class="room-status" role="status">' + esc(s.notice) + "</p>"
        : "") +
      '</section><aside class="product-notes">' +
      reviewNotes() +
      '</aside></div><div id="product-overlay" ' +
      (!s.dialog ? "hidden" : "") +
      "></div>";
    bindCommon();
    renderDialog();
  }
  function button(id, label, secondary = false, disabled = false) {
    return (
      '<button id="' +
      id +
      '" class="' +
      (secondary ? "secondary" : "") +
      '" ' +
      (disabled ? "disabled" : "") +
      ">" +
      label +
      "</button>"
    );
  }
  function lobby() {
    shell(
      "一桌麻将，随时相聚。",
      '<p>太湖玩法 · 好友同桌 · 机器人陪打</p><label class="product-label">访客昵称<input id="guest-name" maxlength="12" value="' +
        esc(s.nickname) +
        '" autocomplete="off"></label><div class="product-actions">' +
        button("create-room", "创建房间", false, !!s.room) +
        button("join-room", "加入房间", true, !!s.room) +
        (s.room
          ? button(
              "continue-room",
              s.round?.status === "playing"
                ? "继续当前对局"
                : s.result
                  ? "查看本局结算"
                  : "继续当前房间",
            )
          : "") +
        "</div>" +
        (s.room
          ? '<div class="resume-card"><b>房间 ' +
            s.room.code +
            "</b><p>" +
            (s.round?.status === "playing"
              ? "第" + s.round.number + "局进行中，座位已保留。"
              : s.result
                ? "第" + s.result.roundNumber + "局已结束，可查看结算。"
                : "你已入座，可继续准备。") +
            "</p>" +
            button("leave-existing", "离开当前房间", true) +
            "</div>"
          : "") +
        '<p class="entry-note">无需登录。本页为本地原型，不创建真实联网房间。</p>',
    );
    $("guest-name").oninput = (e) => {
      s = ProductFlow.transition(s, "rename", { name: e.target.value });
      save();
    };
    $("create-room").onclick = () => {
      s = ProductFlow.transition(s, "rename", { name: $("guest-name").value });
      dispatch("create");
    };
    $("join-room").onclick = () => dispatch("openJoin");
    if (s.room) {
      $("continue-room").onclick = () => dispatch("continue");
      $("leave-existing").onclick = () => dispatch("askLeave");
    }
  }
  function join() {
    shell(
      "加入好友的牌桌。",
      '<p>输入朋友提供的6位房间号。</p><form id="join-form"><label class="product-label">房间号<input id="room-code" inputmode="numeric" maxlength="6" value="' +
        esc(s.joinCode) +
        '" placeholder="例如 286319" autocomplete="off" aria-describedby="join-error"></label><p id="join-error" class="product-error" role="alert">' +
        esc(s.joinError) +
        '</p><div class="product-actions"><button id="join-submit" type="submit" ' +
        (!s.joinCode ? "disabled" : "") +
        '>加入房间</button><button id="join-back" class="secondary" type="button">返回大厅</button></div></form>',
    );
    $("room-code").oninput = (e) => {
      $("join-submit").disabled = !e.target.value.trim();
    };
    $("join-form").onsubmit = (e) => {
      e.preventDefault();
      dispatch("join", { code: $("room-code").value });
    };
    $("join-back").onclick = () => dispatch("home");
  }
  function roomView() {
    const owner = ProductFlow.owner(s),
      combo = ProductFlow.combinations(s),
      missing = s.room.seats.filter((x) => !x).length,
      unready = s.room.seats.filter(
        (x) => x?.type === "human" && !x.ready,
      ).length,
      allReady = ProductFlow.canStart(s);
    const why = missing
      ? "还缺" + missing + "个座位，可邀请朋友或由房主补齐机器人。"
      : unready
        ? "等待" + unready + "位真人准备。"
        : owner
          ? "四家已就绪，可以开始。"
          : "四家已就绪，等待房主开始。";
    shell(
      "房间 · " + s.room.code,
      "<p>太湖麻将 · " +
        combo.humans +
        "位真人＋" +
        combo.bots +
        "位机器人 · 第" +
        (s.room.roundNumber + 1) +
        '局待开始</p><div class="room-seats">' +
        s.room.seats
          .map(
            (x, i) =>
              '<div class="product-seat">' +
              Blocks.roomSeat({
                name: x?.name ?? "",
                label: x
                  ? (i === s.room.localSeat ? "你" : "") +
                    (i === s.room.owner ? " · 房主" : "") +
                    " · " +
                    (x.type === "bot" ? "机器人" : "真人")
                  : "空座",
                ready: x?.ready ?? false,
              }) +
              (owner && x?.type === "bot"
                ? '<button class="remove-bot" data-remove="' +
                  i +
                  '">移除机器人</button>'
                : "") +
              "</div>",
          )
          .join("") +
        '</div><p class="room-status">' +
        why +
        '</p><div class="product-actions">' +
        (owner ? button("fill-bots", "机器人补齐", false, missing === 0) : "") +
        button("copy-invite", "邀请好友", true) +
        button(
          "prepare",
          s.room.seats[s.room.localSeat].ready ? "取消准备" : "准备",
          true,
        ) +
        button(
          "start-game",
          owner ? "开始对局" : "等待房主开始",
          false,
          !owner || !allReady,
        ) +
        button("room-back", owner ? "解散房间" : "离开房间", true) +
        '</div><p class="entry-note">尚未发牌。真人入座变化会重置准备，机器人不会顶替已入座真人。</p>',
    );
    if (owner) $("fill-bots").onclick = () => dispatch("fill");
    $("copy-invite").onclick = () => dispatch("copyInvite");
    $("prepare").onclick = () => dispatch("ready");
    $("start-game").onclick = () => dispatch("start");
    $("room-back").onclick = () => dispatch("askLeave");
    entry
      .querySelectorAll("[data-remove]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            dispatch("removeBot", { index: Number(b.dataset.remove) })),
      );
  }
  function resultView() {
    const kind = s.result.kind,
      draw = kind === "draw",
      multi = kind === "multi";
    const scores = draw
      ? [0, 0, 0, 0]
      : multi
        ? [10, -22, 12, 0]
        : s.room.seats.map((_, i) => (i === s.room.localSeat ? 15 : -5));
    shell(
      draw
        ? "黄庄 · 本局结束"
        : multi
          ? "一炮双响 · 本局结束"
          : "自摸 · 本局结束",
      "<p>房间 " +
        s.room.code +
        " · 第" +
        s.result.roundNumber +
        "局 · " +
        s.result.roundId +
        '</p><div class="product-result">' +
        s.room.seats
          .map(
            (x, i) =>
              '<div class="score-row"><span>' +
              esc(x.name) +
              (i === s.room.localSeat ? "（你）" : "") +
              "</span><strong>" +
              (scores[i] > 0 ? "+" : "") +
              scores[i] +
              "</strong></div>",
          )
          .join("") +
        "<details><summary>查看结算依据</summary><p>" +
        (draw
          ? "无人胡牌，四家零结算，无额外杠收入或罚款。"
          : multi
            ? "座位0与座位2分别接炮，座位1支付10和12，座位3不付款。"
            : "样例赢家为你：普通自摸底4＋资格花1＝每家5点，三家共付15。") +
        '</p><p>本页为设计样例，正式分数应由裁判与规则版本生成。</p></details></div><div class="product-actions">' +
        button("next-round", "再来一局") +
        button("result-room", "返回房间", true) +
        button("result-home", "返回大厅", true) +
        '</div><p class="entry-note">再来一局仍需回房间准备并明确开始，不会自动发牌。</p>',
    );
    $("next-round").onclick = () => dispatch("room");
    $("result-room").onclick = () => dispatch("room");
    $("result-home").onclick = () => dispatch("home");
  }
  function renderDialog() {
    const el = $("product-overlay");
    if (!el) return;
    if (!s.dialog) {
      el.hidden = true;
      return;
    }
    const single = ProductFlow.combinations(s).humans <= 1;
    let title = "",
      copy = "",
      actions = [];
    if (s.dialog === "invite") {
      title = "邀请朋友入座";
      copy =
        "房间号：" +
        s.room.code +
        "。朋友可以从大厅选择加入房间，输入此号码。当前为本地设计原型，不能跨设备真实加入，也不会发送邀请消息。";
      actions = [["知道了", "cancel"]];
    } else if (s.dialog === "connection") {
      title = "连接暂时中断";
      copy =
        "暂停动作提交。恢复后仍是房间" +
        s.room.code +
        (s.round ? "的第" + s.round.number + "局" : "") +
        "，不会重新发牌。";
      actions = [["重试连接", "reconnect"]];
    } else {
      title =
        s.dialog === "dismissRoom"
          ? "解散这个房间？"
          : s.dialog === "leaveRoom"
            ? "离开这个房间？"
            : single
              ? "中止这局陪打？"
              : "暂离当前牌桌？";
      copy =
        s.dialog === "dismissRoom"
          ? "房间尚未开局，解散后本地演示座位释放。"
          : s.dialog === "leaveRoom"
            ? "尚未开局，离开后可重新输入房间号加入。"
            : single
              ? "这是一人陪打局。确认会中止本局，不产生正常胡牌结算。"
              : "返回大厅，对局和座位保留，可以继续返回。本原型不自动替你出牌；多人托管政策待专项确定。";
      actions = [
        ["取消", "cancel"],
        ["确认", "confirmLeave"],
      ];
    }
    el.hidden = false;
    el.innerHTML = Blocks.dialog({
      title,
      copy,
      buttons: actions.map((x) => x[0]),
    });
    el.querySelectorAll(".dialog-actions button").forEach(
      (b, i) => (b.onclick = () => dispatch(actions[i][1])),
    );
    el.querySelector("button")?.focus();
  }
  function bindCommon(scope = entry) {
    scope.querySelectorAll("[data-sim]").forEach(
      (b) =>
        (b.onclick = () => {
          const ev = b.dataset.sim;
          if (ev === "win" || ev === "draw" || ev === "multi")
            dispatch("finish", { kind: ev === "win" ? "zimo" : ev });
          else if (ev === "nextEvent") {
            const next = {
              deal: "turn",
              turn: "wait",
              selected: "wait",
              wait: "chi",
              chi: "chi-options",
              "chi-options": "chi-submit",
              "chi-submit": "chi-done",
              "chi-done": "flower",
              flower: "flower-select",
              "flower-select": "flower-chain",
              "flower-chain": "ron",
              ron: "settlement",
            };
            table(next[s.round.scene] ?? "turn");
          } else dispatch(ev);
        }),
    );
  }
  function render() {
    if (rendering) return;
    rendering = true;
    document.body.classList.toggle("product-app", !review);
    if (s.page === "table" && s.round) {
      root.hidden = false;
      entry.hidden = true;
      bar.innerHTML =
        path() +
        '<div class="app-route-controls"><button id="app-home">返回大厅（保留对局）</button><button id="app-leave">离开牌桌</button><span>产品流程原型 · 非真实牌谱</span></div>';
      $("app-home").onclick = () => dispatch("home");
      $("app-leave").onclick = () => dispatch("askLeave");
      goto(s.round.scene);
      const offsets = { bottom: 0, right: 1, top: 2, left: 3 };
      root.querySelectorAll("[data-seat]").forEach((node) => {
        const pos = node.dataset.seat,
          index = (s.room.localSeat + offsets[pos]) % 4;
        node.innerHTML = Blocks.playerIdentity(pos, {
          profile: { ...s.room.seats[index], dealer: index === 0 },
        });
      });
      root
        .querySelectorAll("[data-call-details]")
        .forEach((b) => (b.onclick = () => dialog("callRelations")));
      if (s.round.scene === "deal") {
        $("status-banner").textContent =
          "发牌完成 · 庄家示例：" + s.room.seats[0].name;
        $("turn").textContent =
          s.room.localSeat === 0 ? "轮到你" : "庄家 · " + s.room.seats[0].name;
      }
      const heading = root.querySelector(".annotations .annotation-heading");
      heading.innerHTML =
        '<span class="eyebrow">PRODUCT FLOW / 对局</span><h2>第' +
        s.round.number +
        "局 · 房间" +
        s.room.code +
        "</h2>" +
        simulationControls();
      bindCommon(heading);
      if (s.dialog) {
        const el = $("overlay");
        el.hidden = false;
        const offline = s.dialog === "connection";
        el.innerHTML = Blocks.dialog({
          title: offline ? "连接暂时中断" : "离开当前牌桌？",
          copy: offline
            ? "正在恢复原局，暂不能提交动作。"
            : ProductFlow.combinations(s).humans <= 1
              ? "确认后中止本次陪打，不生成正常胡牌结算。"
              : "暂离后返回大厅，保留座位与当前牌局，不自动托管。",
          buttons: offline ? ["恢复连接"] : ["继续打牌", "确认离开"],
        });
        const bs = el.querySelectorAll(".dialog-actions button");
        if (offline) bs[0].onclick = () => dispatch("reconnect");
        else {
          bs[0].onclick = () => dispatch("cancel");
          bs[1].onclick = () => dispatch("confirmLeave");
        }
      }
      scaleArtboard();
    } else if (s.page === "join") join();
    else if (s.page === "room" && s.room) roomView();
    else if (s.page === "result" && s.result) resultView();
    else {
      s.page = "lobby";
      lobby();
    }
    if (s.page !== "table") history.replaceState(null, "", "#" + s.page);
    rendering = false;
    save();
  }
  function table(id) {
    if (!s.round) {
      review = true;
      root.hidden = false;
      entry.hidden = true;
      document.body.classList.remove("product-app");
      goto(id);
      scaleArtboard();
      return;
    }
    if (["settlement", "draw", "multi-win"].includes(id)) {
      dispatch("finish", {
        kind: id === "draw" ? "draw" : id === "multi-win" ? "multi" : "zimo",
      });
      return;
    }
    s = ProductFlow.transition(s, "scene", { scene: id });
    s.page = "table";
    save();
    render();
  }
  document.addEventListener("keydown", (e) => {
    const overlay = $("product-overlay");
    if (!overlay || overlay.hidden || !overlay.getClientRects().length) return;
    if (e.key === "Escape" && s.dialog !== "connection") {
      dispatch("cancel");
      return;
    }
    if (e.key === "Tab") {
      const bs = [...overlay.querySelectorAll("button:not(:disabled)")];
      if (e.shiftKey && document.activeElement === bs[0]) {
        e.preventDefault();
        bs.at(-1)?.focus();
      } else if (!e.shiftKey && document.activeElement === bs.at(-1)) {
        e.preventDefault();
        bs[0]?.focus();
      }
    }
  });
  window.prototypeSceneOptions = (scene) => {
    if (review || !s.round || s.page !== "table") return scene[5];
    if (scene[0] === "deal")
      return {
        ...scene[5],
        handCount: s.room.localSeat === 0 ? 14 : 13,
        locked: s.room.localSeat !== 0,
        wall: 91,
      };
    return scene[5];
  };
  window.prototypeSceneChanged = (scene) => {
    if (rendering || review || s.page !== "table" || !s.round) return;
    if (["settlement", "draw", "multi-win"].includes(scene[0])) {
      dispatch("finish", {
        kind:
          scene[0] === "draw"
            ? "draw"
            : scene[0] === "multi-win"
              ? "multi"
              : "zimo",
      });
      return;
    }
    s = ProductFlow.transition(s, "scene", { scene: scene[0] });
    save();
  };
  window.prototypeFlowHooks = {
    returnToRoom: () => dispatch("room"),
    leave: () => dispatch("confirmLeave"),
    requestLeave: () => {
      if (review) return false;
      dispatch("askLeave");
      return true;
    },
  };
  const initial = window.prototypeInitialHash,
    query = new URLSearchParams(location.search),
    demo = query.get("case");
  if (demo) {
    s = ProductFlow.blank();
    if (demo === "join" || demo === "join-error") {
      s = ProductFlow.transition(s, "openJoin");
      if (demo === "join-error")
        s = ProductFlow.transition(s, "join", { code: "999999" });
    } else if (demo !== "solo") {
      s = ProductFlow.transition(s, "create");
      if (demo === "friends") s = ProductFlow.transition(s, "remoteJoin");
      else {
        s = ProductFlow.transition(s, "fill");
        s = ProductFlow.transition(s, "ready");
        s = ProductFlow.transition(s, "start");
        if (demo === "reconnect") s = ProductFlow.transition(s, "disconnect");
        if (demo === "result")
          s = ProductFlow.transition(s, "finish", { kind: "zimo" });
        if (demo === "leave") s = ProductFlow.transition(s, "askLeave");
      }
    }
  } else if (
    query.has("review") ||
    (initial &&
      !["#lobby", "#join", "#room", "#result"].includes(initial) &&
      (!s.round || initial.slice(1) !== s.round.scene))
  ) {
    review = true;
    root.hidden = false;
    entry.hidden = true;
    bar.innerHTML = '<a href="index.html">进入完整产品流程 →</a>';
    goto(initial.slice(1) || "turn");
    scaleArtboard();
    return {
      lobby: () => {
        review = false;
        s.page = "lobby";
        render();
      },
      room: () => {
        review = false;
        dispatch("room");
      },
      table,
    };
  } else if (initial === "#join") s.page = "join";
  else if (initial === "#room" && s.room) s.page = "room";
  else if (initial === "#result" && s.result) s.page = "result";
  else if (s.round?.status === "playing" && initial === "#" + s.round.scene)
    s.page = "table";
  else s.page = "lobby";
  render();
  return {
    lobby: () => dispatch("home"),
    room: () => dispatch("room"),
    table,
    dispatch,
    state: () => cloneState(),
  };
  function cloneState() {
    return JSON.parse(JSON.stringify(s));
  }
})();
