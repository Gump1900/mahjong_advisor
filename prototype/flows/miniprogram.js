"use strict";
/* Mobile Flow：本地可序列化的流程演示，无账号、网络或真实裁判。 */
window.MiniFlow = (() => {
  const base = [
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
  ];
  const scenes = [
    ["home", "入口与房间", "小程序首页", "portrait"],
    ["join", "入口与房间", "输入房号", "portrait"],
    ["join-error", "入口与房间", "加入失败", "portrait"],
    ["room", "入口与房间", "房间 · 等待好友", "portrait"],
    ["room-ready", "入口与房间", "机器人补齐与准备", "portrait"],
    ["room-friends", "入口与房间", "好友混合入座", "portrait"],
    ["rotate", "进入牌桌", "横屏进入对局", "portrait"],
    ["deal", "进入牌桌", "发牌与庄家起手", "landscape"],
    ["turn", "摸打与响应", "本人摸牌回合", "landscape"],
    ["selected", "摸打与响应", "选牌 · 再点打出", "landscape"],
    ["wait", "摸打与响应", "等待别人出牌", "landscape"],
    ["chi", "摸打与响应", "上家弃牌 · 可以吃", "landscape"],
    ["chi-options", "摸打与响应", "选择吃牌组合", "landscape"],
    ["chi-pending", "摸打与响应", "吃牌提交中", "landscape"],
    ["expired", "摸打与响应", "响应过期 · 未执行", "landscape"],
    ["peng", "摸打与响应", "对家弃牌 · 可以碰", "landscape"],
    ["ming", "摸打与响应", "接弃牌明杠", "landscape"],
    ["an", "摸打与响应", "自己摸齐 · 暗杠", "landscape"],
    ["add", "摸打与响应", "碰后第四张 · 加杠", "landscape"],
    ["flower", "花牌与听胡", "留花或换花", "landscape"],
    ["flower-select", "花牌与听胡", "选择换花批次", "landscape"],
    ["flower-chain", "花牌与听胡", "补回新花 · 再选择", "landscape"],
    ["tenpai", "花牌与听胡", "听牌 · 左侧常驻", "landscape"],
    ["ron", "花牌与听胡", "可胡 · 过胡确认", "landscape"],
    ["locked", "花牌与听胡", "三口互锁", "landscape"],
    ["win", "结束与恢复", "自摸成功", "landscape"],
    ["gang-win", "结束与恢复", "补牌胡 · 杠开", "landscape"],
    ["multi-win", "结束与恢复", "一炮多响结算", "portrait"],
    ["result", "结束与恢复", "本局结算", "portrait"],
    ["draw", "结束与恢复", "黄庄结算", "portrait"],
    ["reconnect", "结束与恢复", "连接中断", "landscape"],
    ["leave", "结束与恢复", "离开对局", "landscape"],
    ["capacity", "结束与恢复", "极限容量检查", "landscape"],
  ];
  const blank = () => ({
    scene: "home",
    nickname: "林间听雨",
    resume: null,
    owner: true,
    seats: [
      { name: "林间听雨", type: "human", ready: false },
      null,
      null,
      null,
    ],
    hand: [...base],
    melds: [],
    flowers: [],
    selected: -1,
    flowerSelection: [],
    chiSelection: -1,
    roomCode: "",
    joinError: "",
    round: 1,
    modal: null,
    toast: "",
    canSelfWin: false,
    wall: 62,
    blocked: false,
    waitTiles: [],
    winMethod: "zimo",
    locked: false,
  });
  function setup(scene, s = blank()) {
    const n = {
      ...s,
      scene,
      modal: null,
      toast: "",
      selected: -1,
      flowerSelection: [],
      chiSelection: -1,
    };
    if (scene === "home") {
      const b = blank();
      b.nickname = s.nickname || b.nickname;
      b.seats[0].name = b.nickname;
      return b;
    }
    if (scene === "join" || scene === "join-error") {
      n.roomCode = scene === "join-error" ? "999999" : "";
      n.joinError = scene === "join-error" ? "房间已满，换个房号试试" : "";
      return n;
    }
    if (scene === "room") {
      n.seats = [
        { name: n.nickname, type: "human", ready: false },
        null,
        null,
        null,
      ];
      n.owner = true;
      return n;
    }
    if (scene === "room-ready")
      n.seats = [
        { name: "林间听雨", type: "human", ready: false },
        ...["竹影", "远山", "云水"].map((name) => ({
          name,
          type: "bot",
          ready: true,
        })),
      ];
    if (scene === "room-friends")
      n.seats = [
        { name: "林间听雨", type: "human", ready: false },
        { name: "竹影", type: "human", ready: true },
        { name: "远山", type: "human", ready: true },
        { name: "云水", type: "bot", ready: true },
      ];
    n.seats[0].name = n.nickname || "林间听雨";
    if (
      ![
        "home",
        "join",
        "join-error",
        "room",
        "room-ready",
        "room-friends",
      ].includes(scene) &&
      n.seats.some((p) => !p)
    )
      n.seats = [
        { name: "林间听雨", type: "human", ready: true },
        ...["竹影", "远山", "云水"].map((name) => ({
          name,
          type: "bot",
          ready: true,
        })),
      ];
    n.canSelfWin = false;
    n.replacementIsFlower = scene === "flower-chain";
    n.winMethod = "zimo";
    n.wall = 62;
    n.hand = [...base];
    n.melds = [];
    n.flowers = [];
    n.waitTiles = [];
    n.blocked = false;
    n.locked = false;
    if (scene === "deal") n.wall = 91;
    if (scene === "selected") n.selected = 13;
    if (["wait", "tenpai", "ron"].includes(scene)) n.hand = base.slice(0, 13);
    if (["chi", "chi-options", "chi-pending", "expired"].includes(scene))
      n.hand = [
        "1万",
        "2万",
        "3万",
        "4万",
        "5万",
        "6万",
        "2饼",
        "3饼",
        "1条",
        "2条",
        "4条",
        "南",
        "南",
      ];
    if (scene === "peng")
      n.hand = [
        "1万",
        "2万",
        "3万",
        "4万",
        "5万",
        "6万",
        "5饼",
        "5饼",
        "2条",
        "3条",
        "4条",
        "南",
        "9饼",
      ];
    if (scene === "ming")
      n.hand = [
        "1万",
        "2万",
        "3万",
        "4万",
        "5万",
        "6万",
        "5饼",
        "5饼",
        "5饼",
        "2条",
        "3条",
        "南",
        "南",
      ];
    if (scene === "an")
      n.hand = [
        "北",
        "北",
        "北",
        "北",
        "1万",
        "2万",
        "3万",
        "4饼",
        "5饼",
        "6饼",
        "2条",
        "3条",
        "南",
        "南",
      ];
    if (scene === "add") {
      n.melds = [{ kind: "peng", source: "对家", tiles: ["北", "北", "北"] }];
      n.hand = [
        "1万",
        "2万",
        "3万",
        "4饼",
        "5饼",
        "6饼",
        "2条",
        "3条",
        "4条",
        "南",
        "北",
      ];
    }
    if (
      scene === "flower" ||
      scene === "flower-select" ||
      scene === "flower-chain"
    ) {
      n.hand[12] = "春";
      n.hand[13] = "中";
    }
    if (scene === "tenpai" || scene === "ron" || scene === "reconnect") {
      n.hand = base.slice(0, 13);
      n.waitTiles = ["1条", "4条"];
      n.flowers = ["春"];
    }
    if (scene === "locked") {
      n.melds = [
        { kind: "peng", source: "下家", tiles: ["5饼", "5饼", "5饼"] },
        { kind: "peng", source: "下家", tiles: ["7饼", "7饼", "7饼"] },
        { kind: "peng", source: "下家", tiles: ["北", "北", "北"] },
      ];
      n.hand = ["1万", "2万", "南", "南", "9条"];
      n.locked = true;
    }
    if (scene === "wait") n.waitTiles = ["1条", "4条"];
    if (scene === "win" || scene === "result") {
      n.hand = [...base.slice(0, 13), "1条"];
      n.winMethod = "zimo";
    }
    if (scene === "multi-win") {
      n.hand = [...base.slice(0, 13), "4条"];
      n.flowers = ["春"];
      n.winMethod = "multi";
    }
    if (scene === "gang-win") {
      n.melds = [
        { kind: "ming", source: "下家", tiles: ["5饼", "5饼", "5饼", "5饼"] },
      ];
      n.hand = [
        "1万",
        "2万",
        "3万",
        "4万",
        "5万",
        "6万",
        "2条",
        "3条",
        "4条",
        "南",
        "南",
      ];
      n.winMethod = "gangkai";
    }
    if (scene === "capacity") {
      n.melds = [
        { kind: "ming", source: "上家", tiles: ["1万", "1万", "1万", "1万"] },
        { kind: "ming", source: "对家", tiles: ["2饼", "2饼", "2饼", "2饼"] },
        { kind: "ming", source: "下家", tiles: ["3条", "3条", "3条", "3条"] },
        { kind: "ming", source: "上家", tiles: ["北", "北", "北", "北"] },
      ];
      n.hand = ["南", "南"];
      n.flowers = Blocks.maxFlowers;
    }
    return n;
  }
  const full = (s) => s.seats.every(Boolean),
    allReady = (s) => full(s) && s.seats.every((p) => p.ready);
  function transition(state, event, value) {
    let s = JSON.parse(JSON.stringify(state));
    s.toast = "";
    const go = (scene) => ({ ...s, scene, modal: null, selected: -1 });
    if (event === "scene") return setup(value);
    if (event === "create") return setup("room", s);
    if (event === "join") return setup("join");
    if (event === "submit-join") {
      const code = s.roomCode;
      if (!/^\d{6}$/.test(code)) {
        s.joinError = "请输入6位房号";
        return s;
      }
      const error = {
        404404: "房间不存在，请核对房号",
        999999: "房间已满，换个房号试试",
        888888: "这桌已开局，暂不能加入",
      }[code];
      if (error || code !== "286319") {
        s.joinError = error || "没有找到这间房";
        return s;
      }
      s = setup("room-friends", s);
      s.owner = false;
      s.seats[1].name = "房主 · 竹影";
      return s;
    }
    if (event === "fill") {
      s.seats = s.seats.map(
        (p, i) =>
          p || {
            name: ["林间听雨", "竹影", "远山", "云水"][i],
            type: "bot",
            ready: true,
          },
      );
      s.seats.forEach((p) => {
        if (p.type === "human") p.ready = false;
      });
      return s;
    }
    if (event === "ready") {
      s.seats[0].ready = !s.seats[0].ready;
      return s;
    }
    if (event === "start" || event === "remote-start") {
      if (!allReady(s) || (!s.owner && event === "start")) return s;
      return go("rotate");
    }
    if (event === "enter-table") return setup("deal", s);
    if (event === "deal-done") {
      const next = setup("turn", s);
      next.wall = s.wall;
      return next;
    }
    if (event === "invite") {
      s.modal = "invite";
      return s;
    }
    if (event === "rules") {
      s.modal = "rules";
      return s;
    }
    if (event === "back") {
      if (["join", "join-error"].includes(s.scene)) return setup("home");
      if (s.scene.startsWith("room")) {
        s.modal = "leave-room";
        return s;
      }
      s.modal = "leave";
      return s;
    }
    if (event === "cancel") {
      s.modal = null;
      if (s.scene === "leave") s.scene = "turn";
      return s;
    }
    if (event === "resume") return { ...s.resume, resume: null };
    if (event === "confirm-leave") {
      const ongoing =
        !s.scene.startsWith("room") &&
        s.seats.filter((p) => p?.type === "human").length > 1;
      const b = setup("home", s);
      if (ongoing)
        b.resume = {
          ...s,
          scene: s.scene === "leave" ? "turn" : s.scene,
          modal: null,
          resume: null,
        };
      return b;
    }
    if (event === "tile") {
      const i = Number(value);
      if (
        ![
          "turn",
          "selected",
          "flower",
          "flower-chain",
          "an",
          "add",
          "locked",
          "capacity",
        ].includes(s.scene)
      ) {
        s.toast = "请先完成响应，或等待轮到你";
        return s;
      }
      if (Blocks.maxFlowers.includes(s.hand[i])) {
        s.toast = "花牌不能打出，可以留着或选择换花";
        return s;
      }
      if (s.selected === i) {
        s.hand.splice(i, 1);
        s.scene = "wait";
        s.selected = -1;
        s.waitTiles =
          s.melds.length === 0 &&
          [...s.hand].sort().join(",") ===
            [...base.slice(0, 13)].sort().join(",")
            ? ["1条", "4条"]
            : [];
        return s;
      }
      s.selected = i;
      return s;
    }
    if (event === "chi") {
      s.scene = "chi-options";
      return s;
    }
    if (event === "select-chi") {
      s.chiSelection = Number(value);
      return s;
    }
    if (event === "confirm-chi") {
      if (s.chiSelection < 0) return s;
      s.scene = "chi-pending";
      return s;
    }
    if (event === "resolve-chi") {
      if (s.chiSelection < 0) return s;
      const groups = [
        ["1条", "2条", "3条"],
        ["2条", "3条", "4条"],
      ];
      const g = groups[s.chiSelection];
      for (const t of g.filter((t) => t !== "3条")) {
        const at = s.hand.indexOf(t);
        if (at < 0) return s;
        s.hand.splice(at, 1);
      }
      s.melds.push({ kind: "chi", source: "上家", tiles: g, claimed: "3条" });
      s.scene = "turn";
      s.selected = -1;
      return s;
    }
    if (event === "peng") {
      for (let i = 0; i < 2; i++) s.hand.splice(s.hand.indexOf("5饼"), 1);
      s.melds.push({
        kind: "peng",
        source: "对家",
        tiles: ["5饼", "5饼", "5饼"],
      });
      s.scene = "turn";
      return s;
    }
    if (event === "gang") {
      if (s.scene === "ming") {
        for (let i = 0; i < 3; i++) s.hand.splice(s.hand.indexOf("5饼"), 1);
        s.melds.push({
          kind: "ming",
          source: "下家",
          tiles: ["5饼", "5饼", "5饼", "5饼"],
        });
      } else if (s.scene === "an") {
        for (let i = 0; i < 4; i++) s.hand.splice(s.hand.indexOf("北"), 1);
        s.melds.push({
          kind: "an",
          tiles: ["背", "背", "背", "背"],
          owner: true,
        });
      } else if (s.scene === "add") {
        s.hand.splice(s.hand.indexOf("北"), 1);
        s.melds[0] = {
          kind: "ming",
          source: "对家",
          tiles: ["北", "北", "北", "北"],
        };
      } else return s;
      s.hand.push("8饼");
      s.scene = "turn";
      s.canSelfWin = false;
      s.toast = "已开杠，补回8饼";
      return s;
    }
    if (event === "pass") {
      if (s.scene === "ron") {
        s.modal = "pass-win";
        return s;
      }
      s.scene = "wait";
      return s;
    }
    if (event === "confirm-pass") {
      s.modal = null;
      s.scene = "tenpai";
      s.blocked = true;
      return s;
    }
    if (event === "keep") {
      s.scene = "flower";
      s.toast = "花仍留在手中，选择其他牌打出";
      return s;
    }
    if (event === "flowers") {
      s.scene = "flower-select";
      return s;
    }
    if (event === "select-flower") {
      const t = value;
      s.flowerSelection = s.flowerSelection.includes(t)
        ? s.flowerSelection.filter((x) => x !== t)
        : [...s.flowerSelection, t];
      return s;
    }
    if (event === "confirm-flowers") {
      if (!s.flowerSelection.length) return s;
      const chain = !!s.replacementIsFlower;
      let replaceWithFlower = chain;
      for (const t of s.flowerSelection) {
        s.hand.splice(s.hand.indexOf(t), 1);
        s.flowers.push(t);
        s.hand.push(replaceWithFlower ? "夏" : "8饼");
        replaceWithFlower = false;
      }
      s.flowerSelection = [];
      s.replacementIsFlower = false;
      s.scene = s.hand.some((t) => Blocks.maxFlowers.includes(t))
        ? "flower"
        : "turn";
      s.toast = chain ? "补到新花，是否继续换由你决定" : "";
      return s;
    }
    if (event === "win") {
      s.winMethod =
        s.scene === "ron"
          ? "ron"
          : s.winMethod === "gangkai"
            ? "gangkai"
            : "zimo";
      s.scene = "win";
      if (s.winMethod === "ron") s.hand.push("4条");
      return s;
    }
    if (event === "settle") return go("result");
    if (event === "result-room") {
      s.round++;
      s.seats.forEach((p) => {
        if (p?.type === "human") p.ready = false;
      });
      return go("room-ready");
    }
    if (event === "home") return setup("home", s);
    if (event === "sync") {
      s.scene = "wait";
      return s;
    }
    if (event === "retry") {
      s.scene = "tenpai";
      s.waitTiles = ["1条", "4条"];
      return s;
    }
    return s;
  }
  return { blank, setup, transition, scenes, full, allReady, base };
})();
