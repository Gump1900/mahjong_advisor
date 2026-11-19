"use strict";
/* 产品Flow：可序列化的原型状态和流程编排。没有网络、规则裁判或真实账号。 */
window.ProductFlow = (() => {
  const clone = (x) => JSON.parse(JSON.stringify(x));
  const blank = () => ({
    page: "lobby",
    nickname: "林间听雨",
    room: null,
    round: null,
    result: null,
    connection: "online",
    dialog: null,
    notice: "",
    joinCode: "",
    joinError: "",
  });
  const names = ["远山", "竹影", "云水"];
  const seat = (type, name, ready = false) => ({
    type,
    name,
    ready: type === "bot" || ready,
  });
  const resetReady = (s) => {
    if (s.room)
      s.room.seats.forEach((x) => {
        if (x) x.ready = x.type === "bot";
      });
  };
  const local = (s) => s.room?.seats[s.room.localSeat];
  const canStart = (s) =>
    !!s.room &&
    s.connection === "online" &&
    !s.round &&
    s.room.seats.every((x) => x && x.ready);
  const combinations = (s) => {
    const humans = s.room?.seats.filter((x) => x?.type === "human").length ?? 0,
      bots = s.room?.seats.filter((x) => x?.type === "bot").length ?? 0;
    return { humans, bots };
  };
  const owner = (s) => s.room?.localSeat === s.room?.owner;
  function begin(s) {
    s.round = {
      id: "DEMO-" + (s.room.roundNumber + 1),
      number: ++s.room.roundNumber,
      scene: "deal",
      status: "playing",
    };
    s.result = null;
    s.page = "table";
    s.notice = "";
  }
  function transition(before, event, payload = {}) {
    const s = clone(before);
    s.notice = "";
    switch (event) {
      case "rename":
        s.nickname =
          String(payload.name ?? "")
            .trim()
            .slice(0, 12) || "林间听雨";
        break;
      case "home":
        s.page = "lobby";
        s.dialog = null;
        break;
      case "create":
        if (s.room) {
          s.notice = "你已有房间，请继续或先离开。";
          break;
        }
        s.room = {
          code: "286319",
          owner: 0,
          localSeat: 0,
          roundNumber: 0,
          seats: [seat("human", s.nickname), null, null, null],
        };
        s.page = "room";
        break;
      case "openJoin":
        if (s.room) {
          s.notice = "你已有房间，请先继续或离开。";
          break;
        }
        s.page = "join";
        s.joinError = "";
        break;
      case "join": {
        const code = String(payload.code ?? "").replace(/\s/g, "");
        s.joinCode = code;
        if (!/^\d{6}$/.test(code)) {
          s.joinError = "请输入6位房间号。";
          break;
        }
        if (code === "404404") {
          s.joinError = "没有找到这个房间，请核对房间号。";
          break;
        }
        if (code === "999999") {
          s.joinError = "房间已满，请换一个房间。";
          break;
        }
        if (code === "888888") {
          s.joinError = "这桌已经开局，当前不支持中途加入。";
          break;
        }
        if (code !== "286319") {
          s.joinError = "这个演示房间不存在，请使用286319。";
          break;
        }
        s.room = {
          code,
          owner: 0,
          localSeat: 1,
          roundNumber: 0,
          seats: [seat("human", "远山"), seat("human", s.nickname), null, null],
        };
        s.page = "room";
        s.joinError = "";
        break;
      }
      case "continue":
        s.page =
          s.round?.status === "playing"
            ? "table"
            : s.result
              ? "result"
              : s.room
                ? "room"
                : "lobby";
        break;
      case "fill":
        if (!owner(s) || s.round) break;
        s.room.seats = s.room.seats.map(
          (x, i) => x ?? seat("bot", names[(i - 1 + 3) % 3]),
        );
        resetReady(s);
        break;
      case "removeBot":
        if (!owner(s) || s.round || s.room.seats[payload.index]?.type !== "bot")
          break;
        s.room.seats[payload.index] = null;
        resetReady(s);
        break;
      case "ready":
        if (s.room && !s.round && s.connection === "online")
          local(s).ready = !local(s).ready;
        break;
      case "start":
        if (!owner(s)) break;
        if (!canStart(s)) {
          s.notice = "需要四个座位齐全，且所有真人已准备。";
          break;
        }
        begin(s);
        break;
      case "remoteJoin": {
        if (!s.room || s.round) break;
        const i = s.room.seats.findIndex((x) => !x);
        if (i < 0) {
          s.notice = "座位已满，先移除一个机器人再模拟好友加入。";
          break;
        }
        s.room.seats[i] = seat("human", names[(i + 1) % 3]);
        resetReady(s);
        s.notice = "模拟好友已入座；真人需要重新准备。";
        break;
      }
      case "remoteReady":
        if (s.room && !s.round)
          s.room.seats.forEach((x, i) => {
            if (x && i !== s.room.localSeat && x.type === "human")
              x.ready = true;
          });
        break;
      case "remoteStart":
        if (owner(s) || !canStart(s)) break;
        begin(s);
        break;
      case "remoteLeave": {
        if (!s.room || s.round) break;
        const i = s.room.seats.findLastIndex(
          (x, i) =>
            x?.type === "human" && i !== s.room.localSeat && i !== s.room.owner,
        );
        if (i >= 0) {
          s.room.seats[i] = null;
          resetReady(s);
        }
        break;
      }
      case "room":
        if (!s.room) break;
        if (s.round?.status === "playing") {
          s.page = "table";
          break;
        }
        s.round = null;
        s.result = null;
        resetReady(s);
        s.page = "room";
        break;
      case "askLeave":
        s.dialog =
          s.round?.status === "playing"
            ? "leaveRound"
            : owner(s)
              ? "dismissRoom"
              : "leaveRoom";
        break;
      case "cancel":
        s.dialog = null;
        break;
      case "confirmLeave":
        if (s.round?.status === "playing" && combinations(s).humans > 1) {
          s.page = "lobby";
          s.dialog = null;
          s.notice =
            "已暂离牌桌，对局和座位保留，可继续返回；本原型不自动托管。";
          break;
        }
        s.page = "lobby";
        s.room = null;
        s.round = null;
        s.result = null;
        s.dialog = null;
        break;
      case "scene":
        if (s.round?.status === "playing") s.round.scene = payload.scene;
        break;
      case "finish":
        if (!s.room || !s.round) break;
        s.round.status = "finished";
        s.result = {
          kind: payload.kind ?? "zimo",
          roundNumber: s.round.number,
          roundId: s.round.id,
        };
        s.page = "result";
        s.connection = "online";
        break;
      case "disconnect":
        if (s.room) {
          s.connection = "offline";
          s.dialog = "connection";
        }
        break;
      case "reconnect":
        s.connection = "online";
        s.dialog = null;
        s.notice = "连接已恢复，仍是原房间和原牌局。";
        break;
      case "copyInvite":
        if (s.room) s.dialog = "invite";
        break;
    }
    return s;
  }
  const notes = {
    lobby: {
      title: "大厅与访客入口",
      why: "先给出创建与加入两条明确路径，不用登录阻断试用。",
      interaction:
        "创建房间不会发牌；已有房间时优先提供继续入口。昵称是展示信息，不是账号凭证。",
      empty: "没有活动房间时不显示继续；清除本地原型数据后恢复初始大厅。",
      failure: "进入失败保留当前页面和输入，明确原因。",
    },
    join: {
      title: "加入房间",
      why: "使用6位房间号，输入、查找和错误提示在同一处完成。",
      interaction:
        "286319为可加入样例；404404不存在，999999已满，888888已开局。",
      empty: "未输入不能加入；格式错误就地提示，不创建幽灵房间。",
      failure: "错误不清空输入，可修改重试，也可返回大厅。",
    },
    room: {
      title: "房间与开局条件",
      why: "四个座位、身份与准备状态可见；真人与机器人共用座位，不自动替换已入座真人。",
      interaction:
        "房主补齐／移除机器人；每位真人自行准备；机器人就绪。所有人齐备后房主明确开始。",
      empty: "空座显示等待入座。没坐满或有人未准备时说明尚缺条件，不自动开局。",
      failure:
        "成员变化重置真人准备；开始只产生一局。非房主等待房主，不能越权开局。",
    },
    table: {
      title: "对局与返回路径",
      why: "复用已确认的牌桌Block和桌内Flow，保留三口、花牌、牌河与同排手牌设计。",
      interaction:
        "原型通过右侧“模拟事件”推进不同响应，真实按钮仍演示选牌、吃碰杠胡。场景路径不是可重放牌谱。",
      empty: "没有吃碰杠胡选项就不显示响应组；无单独“过”。",
      failure:
        "断线遮罩阻止提交，恢复原局。单人陪打离开可中止；多人暂离保留座位，不擅自设定托管策略。",
    },
    result: {
      title: "结算与下一局",
      why: "结果先核对，再由玩家明确选择继续或离开。胡牌、黄庄、一炮多响分别展示。",
      interaction:
        "再来一局和返回房间均回等待页并重置准备，保留同一房间与座位。",
      empty: "没有真实结算时不能用零分代替；此原型明确展示样例分项。",
      failure: "刷新不重复结算、不自动发下一局。结果和局号关联。",
    },
  };
  const journeys = [
    {
      name: "单人陪打主线",
      case: "solo",
      steps: [
        "访客大厅",
        "创建房间",
        "补齐三个机器人",
        "准备",
        "明确开局",
        "摸打与响应",
        "结算",
        "回房准备下一局",
      ],
    },
    {
      name: "好友加入与混合座位",
      case: "friends",
      steps: [
        "创建房间",
        "邀请信息",
        "好友入座",
        "机器人补空位",
        "所有真人准备",
        "房主开始",
        "对局",
      ],
    },
    {
      name: "作为访客加入好友房",
      case: "join",
      steps: [
        "大厅",
        "输入房间号",
        "格式／存在／满员检查",
        "入座",
        "自己准备",
        "等待房主",
        "开局",
      ],
    },
    {
      name: "加入失败与恢复",
      case: "join-error",
      steps: [
        "输入房间号",
        "不存在／已满／已开局",
        "保留输入",
        "修改重试／返回大厅",
      ],
    },
    {
      name: "断线与刷新恢复",
      case: "reconnect",
      steps: [
        "进行中牌局",
        "断开连接",
        "暂停本人的提交",
        "恢复连接",
        "原房间原局",
        "继续操作",
      ],
    },
    {
      name: "本局结束与下一局",
      case: "result",
      steps: [
        "自摸／接炮／多响／黄庄",
        "核对结算",
        "再来一局",
        "保留座位",
        "重置准备",
        "明确开始新局",
      ],
    },
    {
      name: "主动离开",
      case: "leave",
      steps: [
        "点击返回",
        "按当前阶段解释后果",
        "取消留在原处／确认离开",
        "单人中止／多人暂离",
        "大厅继续入口",
      ],
    },
  ];
  return { blank, transition, canStart, combinations, owner, notes, journeys };
})();
