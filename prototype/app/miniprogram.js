"use strict";
/* App：只装配小程序页面、Flow事件与评审注释。 */
(() => {
  const B = MobileBlocks,
    F = MiniFlow,
    $ = (id) => document.getElementById(id),
    e = B.e;
  let s = F.blank(),
    autoTimer,
    toastTimer;
  try {
    const saved = JSON.parse(sessionStorage.getItem("taihu-mini-prototype"));
    if (saved && F.scenes.some((x) => x[0] === saved.scene)) s = saved;
  } catch {}
  const initial = location.hash.slice(1);
  if (F.scenes.some((x) => x[0] === initial) && initial !== s.scene)
    s = F.setup(initial);
  if (new URLSearchParams(location.search).has("present"))
    document.body.classList.add("present");
  const sceneInfo = () => F.scenes.find((x) => x[0] === s.scene) || F.scenes[0];
  const button = B.button;
  function dispatch(event, value) {
    clearTimeout(autoTimer);
    if (event === "close-chi") {
      s.scene = "chi";
      s.chiSelection = -1;
      render();
      return;
    }
    if (event === "close-flowers") {
      s.scene = "flower";
      s.flowerSelection = [];
      render();
      return;
    }
    if (event === "input-code") {
      s.roomCode = String(value).replace(/\D/g, "").slice(0, 6);
      s.joinError = "";
      save();
      return;
    }
    if (event === "digit") {
      s.roomCode = (s.roomCode + value).slice(0, 6);
      s.joinError = "";
      render();
      return;
    }
    if (event === "erase") {
      s.roomCode = s.roomCode.slice(0, -1);
      s.joinError = "";
      render();
      return;
    }
    if (event === "profile") {
      s.modal = "profile";
      render();
      return;
    }
    if (event === "save-name") {
      const name = $("nickname")?.value.trim();
      if (name) {
        s.nickname = name.slice(0, 8);
        s.seats[0].name = s.nickname;
      }
      s.modal = null;
      render();
      return;
    }
    if (event === "details") {
      s.modal = "result-details";
      render();
      return;
    }
    if (event === "friends") {
      s = F.setup("room-friends", s);
      render();
      return;
    }
    if (event === "next-turn") {
      s = {
        ...F.setup("turn", s),
        scene: "turn",
        hand: [...F.base.slice(0, 13), "1条"],
        waitTiles: [],
        selected: -1,
        canSelfWin: true,
        blocked: false,
        wall: 87,
      };
      render();
      return;
    }
    const before = s;
    s = F.transition(s, event, value);
    render();
    if (event === "confirm-chi" && s.scene === "chi-pending")
      autoTimer = setTimeout(() => dispatch("resolve-chi"), 700);
    if (
      event === "tile" &&
      before.hand.length > s.hand.length &&
      s.scene === "wait" &&
      !new URLSearchParams(location.search).has("review")
    ) {
      autoTimer = setTimeout(() => {
        if (s.scene !== "wait") return;
        s.hand.push("1条");
        s.scene = s.hand.some((t) => Blocks.maxFlowers.includes(t))
          ? "flower"
          : "turn";
        s.canSelfWin =
          s.melds.length === 0 &&
          [...s.hand].sort().join(",") ===
            [...F.base.slice(0, 13), "1条"].sort().join(",");
        s.wall = Math.max(0, (s.wall ?? 91) - 4);
        s.blocked = false;
        s.waitTiles = [];
        render();
      }, 1600);
    }
  }
  function save() {
    try {
      sessionStorage.setItem("taihu-mini-prototype", JSON.stringify(s));
    } catch {}
  }
  function home() {
    return (
      B.chrome("太湖麻将") +
      `<section class="portrait-page"><div class="home-profile">${B.avatar(s.seats[0].name)}<div><strong>${e(s.seats[0].name)}</strong><small>访客体验 · 暂无需登录</small></div><button data-event="profile" style="margin-left:auto;background:none;font-size:10px;color:#91a087">编辑昵称 ›</button></div><div class="home-hero"><span class="eyebrow">TAIHU · MAHJONG</span><h1>约一桌，<br>慢慢打。</h1><p>熟悉的玩法，熟悉的人。</p><div class="hero-tiles">${B.tile("南")}${B.tile("3条")}${B.tile("春")}</div><svg viewBox="0 0 350 180" aria-hidden="true"><path d="M0 98Q80 15 164 75T350 50V180H0Z" fill="#dbe5d0" opacity=".7"/><path d="M0 128Q80 75 156 107T350 90V180H0Z" fill="#c5d7bb" opacity=".5"/><path d="M0 156Q90 101 187 139T350 120V180H0Z" fill="#b3c9a9" opacity=".5"/><path d="M30 160q72-21 144-4m-81 12q100-18 186-4" stroke="#fffdf0" fill="none" stroke-width="1.2" opacity=".8"/></svg></div><div class="home-actions"><button class="entry-card" data-event="create"><i>＋</i><strong>开一桌</strong><span>邀请好友，机器人补位</span></button><button class="entry-card secondary" data-event="join"><i>↗</i><strong>加入牌桌</strong><span>输入朋友的6位房号</span></button></div>${s.resume ? '<button class="resume-table" data-event="resume">继续286319这一桌 →</button>' : ""}<div class="home-note"><span>一人也能打，三位机器人陪你</span><button data-event="rules">了解玩法 ›</button></div><div class="bottom-mark"><span>太湖地方玩法</span><span>好友同桌 · 自在相聚</span></div></section>`
    );
  }
  function join() {
    return (
      B.chrome("加入牌桌", { back: true }) +
      `<section class="portrait-page"><span class="eyebrow">JOIN A TABLE</span><h1 class="section-heading">朋友在哪一桌？</h1><p class="subcopy">输入朋友分享的6位房号。</p><label for="room-code" style="font-size:10px;color:#8b9b82">房间号</label><input id="room-code" class="code-input" aria-label="6位房间号" inputmode="numeric" maxlength="6" autocomplete="off" value="${e(s.roomCode)}" placeholder="— — — — — —"><div class="input-error" role="alert">${e(s.joinError)}</div><div class="number-pad">${[1, 2, 3, 4, 5, 6, 7, 8, 9, "", 0, "⌫"].map((x) => `<button ${x === "" ? 'class="empty" tabindex="-1" aria-hidden="true"' : ""} data-digit="${x}" aria-label="${x === "⌫" ? "删除一位" : x}">${x}</button>`).join("")}</div><div class="join-submit">${button("加入房间", "submit-join", { disabled: s.roomCode.length !== 6 })}</div><p class="room-hint">房号由开桌的朋友分享给你</p></section>`
    );
  }
  function room() {
    const filled = s.seats.filter(Boolean).length,
      ready = s.seats.filter((p) => p && p.ready).length;
    return (
      B.chrome("好友房间", { back: true }) +
      `<section class="portrait-page" style="padding-top:10px"><div class="room-code"><div><small>房间号 · 太湖麻将</small><strong>286 319</strong></div><span>${s.owner ? "我是房主" : "好友的牌桌"}</span></div><div class="room-board">${s.seats.map(B.seat).join("")}</div><div class="room-tools">${button("邀请好友", "invite", { secondary: true })}${s.owner ? button("机器人补齐", "fill", { secondary: true, disabled: F.full(s) }) : '<div style="font-size:11px;color:#91a184;align-self:center;text-align:center">由房主安排空座</div>'}</div><div class="room-footer">${button(s.seats[0].ready ? "取消准备" : "我准备好了", "ready", { secondary: s.seats[0].ready })}${s.owner ? button("开始对局", "start", { disabled: !F.allReady(s) }) : ""}<p class="room-hint">${filled < 4 ? `还有${4 - filled}个空座，邀请好友或补齐机器人` : !F.allReady(s) ? `已准备 ${ready}/4 · 等待大家准备` : s.owner ? "大家都准备好了，由你开局" : "已准备，等待房主开始"}</p></div></section>`
    );
  }
  function rotate() {
    return (
      B.chrome("准备开局", { back: true }) +
      `<section class="portrait-page rotate-page"><div class="rotate-symbol"></div><h1 class="section-heading">横过来，开打。</h1><p class="subcopy">更宽的牌桌，看清自己的每一张牌。</p>${button("进入横屏牌桌", "enter-table")}<small>这一局由你坐庄</small></section>`
    );
  }
  const riverBase = [
    ["9万", "北", "1饼", "西", "8饼", "9条"],
    ["北", "9条", "1饼", "西"],
    ["1万", "9饼", "西"],
    ["9条", "北", "1饼", "西", "8饼"],
  ];
  function table() {
    const id = s.scene,
      capacity = id === "capacity",
      waiting = ["wait", "tenpai", "reconnect"].includes(id),
      respond = ["chi", "chi-options", "peng", "ming", "ron"].includes(id),
      canPlay = [
        "turn",
        "selected",
        "flower",
        "flower-chain",
        "an",
        "add",
        "locked",
        "capacity",
      ].includes(id);
    let actions =
      id === "chi" || id === "chi-options"
        ? ["过", "吃"]
        : id === "peng"
          ? ["过", "碰"]
          : id === "ming"
            ? ["过", "杠"]
            : id === "ron"
              ? ["过", "胡"]
              : ["an", "add"].includes(id)
                ? ["杠"]
                : s.canSelfWin
                  ? ["胡"]
                  : [];
    const offered = id.startsWith("chi")
      ? "3条"
      : id === "peng" || id === "ming"
        ? "5饼"
        : id === "ron"
          ? "4条"
          : null;
    const opponents = [
      ["left", 3],
      ["top", 2],
      ["right", 1],
    ]
      .map(
        ([pos, index]) =>
          `<div class="opponent ${pos}">${B.avatar(s.seats[index]?.name || "好友", { bot: s.seats[index]?.type === "bot" })}<div>${e(s.seats[index]?.name || "好友")}<small>${pos === "left" ? "上家" : pos === "right" ? "下家" : "对家"}${waiting && pos === "right" ? " · 思考中" : ""}</small>${s.locked && pos === "right" ? '<span class="lock-tag">与你互锁 ×3</span>' : ""}</div></div><div class="opponent-row ${pos}">${Array(
            13,
          )
            .fill("背")
            .map((t) => B.tile(t))
            .join("")}</div>`,
      )
      .join("");
    const rivers = ["top", "left", "right", "bottom"]
      .map((pos, i) =>
        B.river(
          capacity
            ? Array.from(
                { length: 25 },
                (_, j) => ["1万", "9饼", "西", "2条", "北"][j % 5],
              )
            : riverBase[i],
          pos,
        ),
      )
      .join("");
    let overlay = "";
    if (id === "deal")
      overlay =
        '<div class="deal-note"><strong>发牌完成</strong><small>你是庄家 · 起手14张</small><button data-event="deal-done">看看手牌</button></div>';
    if (id === "win" || id === "gang-win")
      overlay = `<div class="win-note"><b>${s.winMethod === "ron" ? "胡" : s.winMethod === "gangkai" ? "杠开" : "自摸"}</b><small>林间听雨 · ${s.winMethod === "ron" ? "接炮4条" : "这一手，胡了"}</small><button data-event="settle">查看结算</button></div>`;
    if (id === "chi-pending")
      overlay =
        '<div class="deal-note"><strong>正在确认吃牌</strong><small>等待响应仲裁，请勿重复提交</small></div>';
    if (id === "expired")
      overlay =
        '<div class="deal-note"><strong>这张牌已被处理</strong><small>未执行吃牌，手牌保持原样</small><button data-event="sync">回到牌桌</button></div>';
    if (id === "reconnect")
      overlay =
        '<div class="connection-overlay"><div class="connection-card"><span class="connection-icon">⌁</span><h2>正在找回这一桌</h2><p>连接中断，先别着急。<br>恢复后继续原来的对局。</p><button data-event="retry">重试连接</button></div></div>';
    const isFlower = ["flower", "flower-select", "flower-chain"].includes(id);
    return `<section class="table-page">${B.chrome("太湖麻将", { back: true, landscape: true })}<span class="table-room" style="position:absolute;left:116px;top:12px">286 319 · 第${s.round}局</span><div class="table-tools"><span>好友房</span><button data-event="rules">玩法</button></div>${opponents}<div class="table-word">太湖</div>${rivers}${B.flowers(["夏", "梅"], "top")}${B.flowers(["兰"], "left")}${B.flowers(["秋"], "right")}${B.flowers(s.flowers, "bottom")}<div class="compass-mobile"><strong>${s.wall ?? 62}</strong><small>${waiting ? "下家回合" : respond ? "等待响应" : "你的回合"}</small></div>${offered ? `<div class="current-discard">${B.tile(offered)}<small>${id === "peng" ? "对家" : id === "ron" ? "下家" : id === "ming" ? "下家" : "上家"}打出</small></div>` : ""}<div class="my-identity">${B.avatar(s.seats[0]?.name || "林间听雨")}<div>${e(s.seats[0]?.name || "林间听雨")}<small>你 · 东 · 庄${s.locked ? " · 互锁×3" : ""}</small></div></div>${B.waits({ tiles: s.waitTiles, blocked: s.blocked || s.locked || !(s.flowers.length || s.melds.some((m) => m.kind !== "chi" && (m.kind !== "peng" || ["南", "西", "北"].includes(m.tiles?.[0])))) })}${B.actions(actions)}${isFlower ? `<div class="flower-actions">${button("留花", "keep", { secondary: true })}${button("换花", "flowers")}</div>` : ""}${s.locked ? '<div class="lock-notice">与下家互锁 ×3<br>本局仅自摸／杠开</div>' : ""}<div class="own-rail">${B.hand(s.hand, { selected: s.selected, melds: s.melds, canPlay, drawn: !waiting && !respond })}</div><div class="table-instruction">${s.selected >= 0 ? `已选${e(s.hand[s.selected])} · 再点同一张打出` : respond ? "请先选择如何响应这张弃牌" : waiting ? "等待对手操作" : isFlower ? "花牌可留或换，不能普通打出" : "点一下选牌，再点同一张打出"}</div>${overlay}<div class="home-indicator"></div></section>`;
  }
  function result() {
    const draw = s.scene === "draw",
      ron = s.winMethod === "ron",
      multi = s.winMethod === "multi";
    const value = draw
      ? 0
      : multi || ron
        ? 3
        : s.winMethod === "gangkai"
          ? 39
          : s.flowers.length
            ? 15
            : 18;
    const nets = draw
      ? [0, 0, 0, 0]
      : multi
        ? [3, -6, 3, 0]
        : ron
          ? [3, -3, 0, 0]
          : [value, -value / 3, -value / 3, -value / 3];
    return (
      B.chrome("本局结算") +
      `<section class="portrait-page" style="padding-top:10px"><div class="result-banner"><span class="round-label">太湖麻将 · 第${s.round}局</span><h1>${draw ? "这一局，黄庄" : multi ? "一炮双响" : "胡得漂亮"}</h1><strong>${value > 0 ? "+" : ""}${value}<span style="font-size:13px;letter-spacing:0;margin-left:5px">分</span></strong><p>${draw ? "牌墙已摸完，四家零结算" : multi ? "你与对家接炮 · 下家分别支付" : ron ? "接炮 · 下家打出4条" : s.winMethod === "gangkai" ? "杠开 · 三家分别支付" : "自摸 · 三家分别支付"}</p></div><div>${s.seats.map((p, i) => `<div class="result-row">${B.avatar(p?.name || "好友", { bot: p?.type === "bot" })}<div><strong>${e(p?.name || "好友")}</strong><small>${i === 0 ? "你 · 庄家" : p?.type === "bot" ? "机器人" : "好友"}</small></div><b class="${nets[i] < 0 ? "negative" : ""}">${nets[i] > 0 ? "+" : ""}${nets[i]}</b></div>`).join("")}</div><div class="result-explain"><button data-event="details" style="padding:0;background:none;color:inherit">查看牌型与付款明细 ›</button></div><div class="result-buttons">${button("回房间，准备下一局", "result-room")}${button("返回首页", "home", { secondary: true })}</div><p class="round-result-note">不会自动开始下一局</p></section>`
    );
  }
  function sheets() {
    let type =
      s.modal ||
      (s.scene === "chi-options"
        ? "chi"
        : s.scene === "flower-select"
          ? "flowers"
          : s.scene === "leave"
            ? "leave"
            : null);
    if (!type) return "";
    const cancel = { label: "取消", event: "cancel", secondary: true };
    if (type === "invite")
      return B.sheet({
        title: "叫上朋友，一起打",
        copy: "把这桌的房号告诉朋友：",
        body: '<strong style="display:block;font-size:34px;letter-spacing:6px;margin:22px 0;text-align:center">286 319</strong><p>朋友打开小程序，选择「加入牌桌」。</p>',
        buttons: [{ label: "知道了", event: "cancel" }],
      });
    if (type === "profile")
      return B.sheet({
        title: "怎么称呼你？",
        body: `<input id="nickname" maxlength="8" value="${e(s.seats[0]?.name || "林间听雨")}" aria-label="昵称" style="width:100%;border:1px solid #ccd9bf;border-radius:10px;padding:13px;background:#f1f4e8;color:#32583b">`,
        buttons: [cancel, { label: "保存昵称", event: "save-name" }],
      });
    if (type === "rules")
      return B.sheet({
        title: "这桌的玩法",
        body: "<p>太湖麻将 · 四人一桌，一胡即结束。<br>东、中、发、白及季节花是花牌，可留或择时换。<br>只能吃上家；碰、杠按当前合法动作提示。<br>过胡须过自己的回合，仍可自摸。<br>同方向成功取三口，双方互锁，仅能自摸／杠开。</p>",
        buttons: [{ label: "明白了", event: "cancel" }],
      });
    if (type === "pass-win")
      return B.sheet({
        title: "这张牌先不胡？",
        copy: "这张先过。过自己这一圈前暂不能接炮，仍可自摸；取得自己的回合后恢复。",
        buttons: [
          { label: "继续胡牌", event: "cancel", secondary: true },
          { label: "确认过", event: "confirm-pass" },
        ],
      });
    if (type === "leave" || type === "leave-room")
      return B.sheet({
        title: type === "leave-room" ? "离开这间房？" : "先离开这桌？",
        copy:
          type === "leave-room"
            ? s.owner
              ? "离开后将解散等待中的房间。"
              : "离开后释放你的座位。"
            : s.seats.filter((p) => p?.type === "human").length > 1
              ? "回到首页，保留这桌和你的座位。不会擅自替你出牌。"
              : "这一局会中止，不生成正常胡牌结算。",
        buttons: [
          { label: "继续留下", event: "cancel", secondary: true },
          { label: "确认离开", event: "confirm-leave" },
        ],
      });
    if (type === "chi") {
      const opts = [
        ["1条", "2条", "3条"],
        ["2条", "3条", "4条"],
      ];
      return B.sheet({
        title: "想怎么吃这张3条？",
        copy: "选一种组合，确认后还需要出一张牌。",
        body:
          '<div class="choice-list">' +
          opts
            .map(
              (g, i) =>
                `<button class="choice-card ${s.chiSelection === i ? "selected" : ""}" data-chi="${i}">${g.map((t) => B.tile(t)).join("")}</button>`,
            )
            .join("") +
          "</div>",
        buttons: [
          { label: "返回", event: "close-chi", secondary: true },
          {
            label: "确认吃牌",
            event: "confirm-chi",
            disabled: s.chiSelection < 0,
          },
        ],
      });
    }
    if (type === "flowers") {
      const flowers = [
        ...new Set(s.hand.filter((t) => Blocks.maxFlowers.includes(t))),
      ];
      return B.sheet({
        title: "这次换哪几张？",
        copy: "只换你选中的花，新补到花牌时再决定。",
        body:
          '<div class="choice-list">' +
          flowers
            .map(
              (t) =>
                `<button class="choice-card flower ${s.flowerSelection.includes(t) ? "selected" : ""}" data-flower="${t}" aria-pressed="${s.flowerSelection.includes(t)}">${B.tile(t)}<label>${s.flowerSelection.includes(t) ? "已选" : "选择"}</label></button>`,
            )
            .join("") +
          "</div>",
        buttons: [
          { label: "保留不换", event: "close-flowers", secondary: true },
          {
            label: s.flowerSelection.length
              ? `换这${s.flowerSelection.length}张`
              : "选择要换的花",
            event: "confirm-flowers",
            disabled: !s.flowerSelection.length,
          },
        ],
      });
    }
    if (type === "result-details") {
      const draw = s.scene === "draw",
        ron = s.winMethod === "ron";
      return B.sheet({
        title: "这一局怎么结算",
        copy: draw
          ? "黄庄，四家都是0分。没有额外杠收入、查听或罚款。"
          : s.winMethod === "multi"
            ? "你和对家各有一花，接炮各3分，由下家分别支付，共付6分。"
            : s.winMethod === "gangkai"
              ? "杠开底8分＋5饼明杠5分＝每家13分，三家共付39分。"
              : ron
                ? "接炮底2分＋已换春1分＝3分，由放炮的下家支付。"
                : s.flowers.length
                  ? "普通自摸底4分＋已换花分；本页样例为一花，每家付5，共收15。"
                  : "无资格花普通自摸，每家固定6分，三家共付18分。",
        body: draw
          ? ""
          : `<div class="result-hand">${s.hand.map((t) => B.tile(t)).join("")}</div>`,
        buttons: [{ label: "收起明细", event: "cancel" }],
      });
    }
    return "";
  }
  function annotations() {
    const id = s.scene,
      portrait = sceneInfo()[3] === "portrait";
    let notes;
    if (["home", "join", "join-error"].includes(id))
      notes = [
        [
          "入口先轻一点",
          "先提供开桌和加入，不把登录设为试打前置。昵称可改，真实微信身份后续接入。",
          "首页不自动发牌；房号空时不可提交。",
        ],
        [
          "保留微信空间",
          "顶部状态栏与胶囊留位，产品标题不过界。这里是原生外壳示意，不模拟胶囊菜单行为。",
          "原生分享与登录尚未调用。",
        ],
        [
          "失败留在当前页",
          "房号支持输入、粘贴和样例数字键盘。错误贴近输入区，不清空房号。",
          "286319可加入；404404不存在、999999满员、888888已开局。",
        ],
      ];
    else if (id.startsWith("room"))
      notes = [
        [
          "四个人，先看清是谁",
          "真人、机器人、空座和准备状态分别呈现。房主只能补空座，不能替换已入座真人。",
          "配置改变重置真人准备，机器人自动准备。",
        ],
        [
          "准备与开局分开",
          "每人准备自己；房主在四座齐全、全部准备后明确开始。按钮禁用时下方解释缺什么。",
          "不是房主时等待房主，不能越权开局。",
        ],
        [
          "分享是系统能力",
          "邀请弹层展示房号。当前不实际发消息；正式微信分享通过原生能力接入。",
          "这份本地原型不提供真实跨设备房间。",
        ],
      ];
    else if (id === "rotate")
      notes = [
        [
          "横屏是当前设计提案",
          "大厅和房间用竖屏，牌桌用横屏，优先留足手牌触摸宽度。切换前解释即将进入对局。",
          "这里切换的是画板，不操作设备方向；正式微信端适配另行验证。",
        ],
        [
          "不偷偷开局",
          "只有房主显式开始才到这里；查看单个场景属于评审工具。",
          "正常进入保留同一房间、座位和局号。",
        ],
      ];
    else if (["result", "draw", "multi-win"].includes(id))
      notes = [
        [
          "结果先于明细",
          "先看自己的得失，再看四家分数。明细按需展开，避免手机首屏堆满牌和公式。",
          "示例总分为零，正式值只能来自裁判。",
        ],
        [
          "下一局重新准备",
          "回房保留座位，重置真人准备。不会点开结算就自动开始下一局。",
          "黄庄、中止和胡牌结算分开。",
        ],
        [
          "横竖屏衔接",
          "结算回到竖屏，便于阅读付款和继续邀请。",
          "是否在实机采用此切换，需要后续适配验证。",
        ],
      ];
    else
      notes = [
        [
          "手机牌桌的新尺度",
          "本人手牌32×44，独立触控；三家暗牌统一14×20，左右整体旋转，完全同规格。",
          "横屏844×390；原生胶囊、系统安全区单独留位。",
        ],
        [
          "副露跟手牌同一排",
          "多一组副露，暗手少三张。四杠16张＋2手牌也保留空间；花和牌河在前方。",
          "吃进张最左横放；碰杠横牌表达来源，加杠不叠牌。",
        ],
        [
          "高频操作一眼就懂",
          "过、吃、碰、杠、胡按固定顺序居中。只显示可用项，没响应时整个按钮组消失。",
          "留花不能打出；吃牌组合／换花批次未选时不能确认。",
        ],
        [
          "听牌留在自己的区域",
          "本人区域最左侧常驻，不随对手动作隐藏、不闪。未听牌就留空。",
          "未见含他家暗牌，非墙内活张；过胡仍能自摸，过自己后恢复。",
        ],
      ];
    if (id === "capacity")
      notes.push([
        "满载不是合法牌谱",
        "此页专门检查本人四杠、两张手牌、24张单花和四家25张牌河的区域容量。",
        "是布局压力数据，不声称四家同时拥有这些实体牌。",
      ]);
    if (id === "reconnect" || id === "leave")
      notes.push([
        "断线与主动离开分开",
        "断线阻止提交、恢复原局；多人暂离不擅自托管；单人退出确认中止。",
        "倒计时、超时托管、房主转让仍待确认。",
      ]);
    $("annotations").innerHTML =
      "<small>DESIGN ANNOTATIONS</small><h2>这里为什么这样设计</h2>" +
      notes
        .map(
          (n, i) =>
            `<section><h3><b>0${i + 1}</b>${n[0]}</h3><p>${n[1]}</p><p>${n[2]}</p></section>`,
        )
        .join("") +
      '<div class="boundary">可点击的设计原型。样例状态不构成连续合法牌谱，不接微信、账号或真实裁判。本版不展示军师模块。</div>';
  }
  function controls() {
    let c = [];
    if (s.scene.startsWith("room"))
      c = [
        ["friends", "模拟好友入座"],
        ["remote-start", "模拟房主开始"],
      ];
    else if (s.scene === "wait")
      c = [
        ["scene:chi", "演示可吃"],
        ["scene:peng", "演示可碰"],
        ["next-turn", "切换到自摸样例"],
      ];
    else if (sceneInfo()[3] === "landscape")
      c = [
        ["scene:tenpai", "查看听牌"],
        ["scene:ron", "演示可胡"],
        ["scene:reconnect", "模拟断线"],
        ["scene:result", "查看结算"],
      ];
    $("review-controls").innerHTML =
      '<span style="font-size:10px;color:#91a087">评审模拟</span>' +
      c
        .map(
          ([event, label]) =>
            `<button data-review="${event}">${label}</button>`,
        )
        .join("") +
      '<button data-review="reset">从首页重新走一遍</button>';
  }
  function render() {
    save();
    const info = sceneInfo(),
      landscape = info[3] === "landscape";
    document.title = "太湖麻将 · " + info[2];
    $("scene-title").textContent = info[2];
    $("canvas-size").textContent = landscape
      ? "844 × 390 · 横屏牌桌"
      : "390 × 844 · 竖屏";
    $("device").classList.toggle("landscape", landscape);
    let body = ["home"].includes(s.scene)
      ? home()
      : ["join", "join-error"].includes(s.scene)
        ? join()
        : s.scene.startsWith("room")
          ? room()
          : s.scene === "rotate"
            ? rotate()
            : ["result", "draw", "multi-win"].includes(s.scene)
              ? result()
              : table();
    // Overlay stays inside the mini-program safe canvas, not the desktop viewport.
    if (landscape) {
      const at = body.lastIndexOf("</section>");
      body =
        body.slice(0, at) +
        sheets() +
        (s.toast
          ? `<div class="toast" role="status">${e(s.toast)}</div>`
          : "") +
        body.slice(at);
    } else
      body +=
        sheets() +
        (s.toast
          ? `<div class="toast" role="status">${e(s.toast)}</div>`
          : "") +
        '<div class="home-indicator"></div>';
    $("screen").innerHTML = body;
    history.replaceState(null, "", "#" + s.scene);
    $("flow-position").textContent = landscape
      ? "04 / 牌桌"
      : s.scene === "home"
        ? "01 / 首页"
        : s.scene.startsWith("room")
          ? "03 / 房间"
          : s.scene === "result" ||
              s.scene === "draw" ||
              s.scene === "multi-win"
            ? "05 / 结算"
            : "02 / 进入牌桌";
    let group = "";
    $("scene-nav").innerHTML =
      F.scenes
        .map(([id, g, title]) => {
          const h = g !== group ? `<h3>${g}</h3>` : "";
          group = g;
          return (
            h +
            `<button data-scene="${id}" class="${s.scene === id ? "active" : ""}" aria-current="${s.scene === id ? "page" : "false"}">${title}</button>`
          );
        })
        .join("") + '<a href="../design.md">查看统一设计规范 ↗</a>';
    annotations();
    controls();
    resize();
    bind();
    if (s.toast) {
      clearTimeout(toastTimer);
      toastTimer = setTimeout(() => {
        s.toast = "";
        document.querySelector(".toast")?.remove();
        save();
      }, 2400);
    }
  }
  function bind() {
    document.querySelectorAll("[data-event]").forEach(
      (b) =>
        (b.onclick = () => {
          if (b.dataset.event === "close-chi") {
            s.scene = "chi";
            s.chiSelection = -1;
            render();
          } else if (b.dataset.event === "close-flowers") {
            s.scene = "flower";
            s.flowerSelection = [];
            render();
          } else dispatch(b.dataset.event);
        }),
    );
    document
      .querySelectorAll("[data-scene]")
      .forEach((b) => (b.onclick = () => dispatch("scene", b.dataset.scene)));
    document
      .querySelectorAll("[data-tile]")
      .forEach((b) => (b.onclick = () => dispatch("tile", b.dataset.tile)));
    document
      .querySelectorAll("[data-digit]")
      .forEach(
        (b) =>
          (b.onclick = () =>
            dispatch(
              b.dataset.digit === "⌫" ? "erase" : "digit",
              b.dataset.digit,
            )),
      );
    document
      .querySelectorAll("[data-chi]")
      .forEach(
        (b) => (b.onclick = () => dispatch("select-chi", b.dataset.chi)),
      );
    document
      .querySelectorAll("[data-flower]")
      .forEach(
        (b) => (b.onclick = () => dispatch("select-flower", b.dataset.flower)),
      );
    document.querySelectorAll("[data-review]").forEach(
      (b) =>
        (b.onclick = () => {
          const v = b.dataset.review;
          if (v === "reset") {
            clearTimeout(autoTimer);
            s = F.blank();
            render();
          } else if (v.startsWith("scene:")) dispatch("scene", v.slice(6));
          else dispatch(v);
        }),
    );
    const input = $("room-code");
    if (input)
      input.oninput = () => {
        dispatch("input-code", input.value);
        input.value = s.roomCode;
        document.querySelector('[data-event="submit-join"]').disabled =
          s.roomCode.length !== 6;
        document.querySelector(".input-error").textContent = "";
      };
    if (input)
      input.onkeydown = (ev) => {
        if (ev.key === "Enter" && s.roomCode.length === 6)
          dispatch("submit-join");
      };
  }
  function resize() {
    const landscape = sceneInfo()[3] === "landscape",
      w = landscape ? 844 : 390,
      h = landscape ? 390 : 844,
      present = document.body.classList.contains("present"),
      border = present ? 0 : 16;
    const scale = Math.min(
      1,
      ($("device-stage").clientWidth - (present ? 0 : 12)) / (w + border),
      Math.max(320, innerHeight - (present ? 0 : 205)) / (h + border),
    );
    $("device").style.width = w + border + "px";
    $("device").style.height = h + border + "px";
    $("device").style.transform = `scale(${scale})`;
    $("device-stage").style.height =
      (h + border) * scale + (present ? 0 : 22) + "px";
    $("device-stage").style.minHeight = "0";
  }
  $("present").onclick = () => {
    const u = new URL(location);
    u.searchParams.set("present", "1");
    window.open(u, "_blank", "noopener");
  };
  window.addEventListener("resize", resize);
  document.addEventListener("keydown", (ev) => {
    const sheet = document.querySelector(".sheet");
    if (!sheet) return;
    if (ev.key === "Escape") {
      if (s.scene === "chi-options") dispatch("close-chi");
      else if (s.scene === "flower-select") dispatch("close-flowers");
      else dispatch("cancel");
    }
    if (ev.key === "Tab") {
      const items = [
        ...sheet.querySelectorAll("button:not(:disabled),input,a[href]"),
      ];
      if (!items.includes(document.activeElement)) {
        ev.preventDefault();
        items[0]?.focus();
      } else if (ev.shiftKey && document.activeElement === items[0]) {
        ev.preventDefault();
        items.at(-1)?.focus();
      } else if (!ev.shiftKey && document.activeElement === items.at(-1)) {
        ev.preventDefault();
        items[0]?.focus();
      }
    }
  });
  window.MiniPrototype = {
    get state() {
      return s;
    },
    dispatch,
    render,
  };
  render();
})();
