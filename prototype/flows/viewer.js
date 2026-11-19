"use strict";
let activeFlow =
  PROTOTYPE_FLOWS.find(
    (f) => f.id === new URLSearchParams(location.search).get("flow"),
  ) ??
  PROTOTYPE_FLOWS.find((f) => f.steps.includes(location.hash.slice(1))) ??
  PROTOTYPE_FLOWS[0];
window.prototypeVisibleScene = (id) =>
  [...activeFlow.steps, ...activeFlow.branches].includes(id);
window.updateFlowReview = function (s) {
  const f = activeFlow;
  document.querySelector(".studio>p").innerHTML =
    '<a href="../blocks/index.html">Block</a> · <a href="product.html">产品Flow</a> · <a href="../app/index.html">App</a>';
  $("flow-review").innerHTML =
    '<div class="flow-toolbar"><div><span class="eyebrow">FLOW / 完整流程</span><h2>' +
    f.name +
    "</h2><p>" +
    f.why +
    '</p></div><label>选择流程 <select id="flow-select">' +
    PROTOTYPE_FLOWS.map(
      (x) =>
        `<option value="${x.id}" ${x.id === f.id ? "selected" : ""}>${x.name}</option>`,
    ).join("") +
    '</select></label></div><div class="flow-track">' +
    f.steps
      .map(
        (id, i) =>
          `<button data-step="${id}" class="${id === s[0] ? "active" : ""}"><small>${i + 1}</small>${SCENARIOS.find((x) => x[0] === id)?.[2] ?? id}</button>`,
      )
      .join("<span>→</span>") +
    '</div><div class="flow-branches"><span>取消／分支／异常：</span>' +
    f.branches
      .map(
        (id) =>
          `<button data-step="${id}" class="${id === s[0] ? "active" : ""}">${SCENARIOS.find((x) => x[0] === id)?.[2] ?? id}</button>`,
      )
      .join("") +
    "</div>";
  $("flow-select").onchange = (e) => {
    activeFlow = PROTOTYPE_FLOWS.find((x) => x.id === e.target.value);
    const u = new URL(location);
    u.searchParams.set("flow", activeFlow.id);
    history.replaceState(null, "", u);
    goto(activeFlow.steps[0]);
  };
  $("flow-review")
    .querySelectorAll("[data-step]")
    .forEach((b) => (b.onclick = () => goto(b.dataset.step)));
  const ids = [...f.steps, ...f.branches];
  $("scenarios")
    .querySelectorAll("[data-scene]")
    .forEach((b) => {
      b.hidden = !ids.includes(SCENARIOS[Number(b.dataset.scene)][0]);
    });
  $("scenarios")
    .querySelectorAll("h3")
    .forEach((h) => (h.hidden = true));
};
if (!location.hash) history.replaceState(null, "", "#" + activeFlow.steps[0]);
