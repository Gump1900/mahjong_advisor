"use strict";
// 原型用的已成功取得副露事件；from为取得者，source为弃牌来源，二者不能倒置。
window.CallFixtures = (() => {
  const make = (source, kinds = ["peng", "peng", "peng"], from = "bottom") =>
    kinds.map((kind, i) => ({
      from,
      source,
      kind,
      tiles:
        kind === "chi"
          ? ["1万", "2万", "3万"]
          : Array(kind === "ming" ? 4 : 3).fill((from==="bottom"?["2饼", "4条", "6万"]:["7饼", "8条", "9万"])[i]),
      claimed: kind === "chi" ? "3万" : undefined,
    }));
  const rightThree = make("right"),
    topThree = make("top"),
    mixed = make("left", ["chi", "peng", "ming"]);
  return {
    rightTwo: rightThree.slice(0, 2),
    rightThree,
    topTwo: topThree.slice(0, 2),
    topThree,
    mixed,
    twoWay: [...rightThree.slice(0, 2), ...make("bottom", ["peng"], "right")],
    twoLocks: [
      ...rightThree,
      ...make("bottom", ["peng", "peng", "peng"], "top"),
    ],
    rejected: [
      ...rightThree.slice(0, 2),
      { ...rightThree[2], successful: false },
    ],
  };
})();
