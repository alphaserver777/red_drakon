(function () {
  "use strict";
  const base = `${window.location.pathname}api/workflow-runs`;
  const colors = {
    pending: { fill: "#303030", line: "#777777" }, running: { fill: "#115e9c", line: "#5bd4ff", active: true },
    checkpoint: { fill: "#176b83", line: "#7cecff", active: true }, completed: { fill: "#176b3a", line: "#63e6a5" },
    blocked: { fill: "#7b5c00", line: "#ffd54f" }, failed: { fill: "#8d2633", line: "#ff8392" },
  };
  let selectedTarget = "", selectedRun = "", timer = null, lastUpdated = "";

  function el(tag, props = {}, text = "") { const node = document.createElement(tag); Object.assign(node, props); node.textContent = text; return node; }
  function api(query = "") { return fetch(`${base}${query}`, { cache: "no-store" }).then(async r => { if (!r.ok) throw new Error((await r.json().catch(() => ({}))).error || `HTTP ${r.status}`); return r.json(); }); }
  function statusOf(event) {
    const result = event.result || {};
    if (event.phase === "started") return "running";
    if (result.status === "checkpoint") return "checkpoint";
    if (["blocked", "dead"].includes(result.status)) return "blocked";
    if (event.phase === "failed" || result.status === "error") return "failed";
    return "completed";
  }
  function draw(run) {
    const events = run.events || [];
    const state = {};
    const details = {};
    for (const event of events) {
      if (!/^\d+$/.test(event.block_id || event.block || "")) continue;
      const id = String(event.block_id || event.block);
      const kind = statusOf(event);
      state[id] = { ...colors[kind], active: kind === "running" || kind === "checkpoint" };
      details[id] = { kind, at: event.occurred_at || event.at, result: event.result || {} };
    }
    window.drakonWorkflowStatus = state;
    if (window.drakonRuntimeRedraw) window.drakonRuntimeRedraw();
    return details;
  }
  function render() {
    const root = document.getElementById("workflow-monitor");
    root.replaceChildren();
    const title = el("strong", {}, "Выполнение схемы");
    const target = el("select", { title: "VPN-цель" });
    const run = el("select", { title: "Запуск" });
    const refresh = el("button", { type: "button" }, "Обновить");
    const state = el("span", { className: "workflow-monitor-state" }, "Загрузка…");
    const steps = el("div", { className: "workflow-monitor-steps" });
    root.append(title, target, run, refresh, state, steps);
    refresh.onclick = load;
    target.onchange = () => { selectedTarget = target.value; selectedRun = ""; load(); };
    run.onchange = () => { selectedRun = run.value; loadRun(steps, state); };
    window.workflowMonitor = { target, run, state, steps };
  }
  async function loadRun(steps, state) {
    if (!selectedRun) return;
    try {
      const response = await api(`?runId=${encodeURIComponent(selectedRun)}`);
      const data = response.run;
      const details = draw(data);
      lastUpdated = data.run.updated_at;
      state.textContent = `Задача #${data.run.task_id} · блок ${data.run.last_block || "—"} · ${data.run.terminal_status || data.run.last_phase || "выполняется"}`;
      steps.replaceChildren(...Object.entries(details).map(([id, item]) => {
        const button = el("button", { type: "button", className: `workflow-step ${item.kind}` }, `#${id}: ${item.kind}`);
        button.onclick = () => alert(`Блок #${id}\n${new Date(item.at * 1000).toLocaleString()}\n${JSON.stringify(item.result, null, 2)}`);
        return button;
      }));
    } catch (error) { state.textContent = `Данные могут быть неактуальны: ${error.message}`; }
  }
  async function load() {
    const ui = window.workflowMonitor;
    try {
      const all = await api();
      const targets = all.targets || [];
      if (!selectedTarget) selectedTarget = targets[0] && targets[0].targetIp;
      ui.target.replaceChildren(...targets.map(item => el("option", { value: item.targetIp, selected: item.targetIp === selectedTarget }, item.targetIp)));
      if (!selectedTarget) { ui.state.textContent = "Для этой схемы ещё нет запусков"; return; }
      const runs = (await api(`?targetIp=${encodeURIComponent(selectedTarget)}`)).runs || [];
      if (!selectedRun) selectedRun = runs[0] && runs[0].runId;
      ui.run.replaceChildren(...runs.map(item => el("option", { value: item.runId, selected: item.runId === selectedRun }, `${item.updatedAt} · задача #${item.taskId} · ${item.terminalStatus || item.lastBlock}`)));
      await loadRun(ui.steps, ui.state);
    } catch (error) { ui.state.textContent = `Данные могут быть неактуальны: ${error.message}`; }
  }
  function init() { render(); load(); timer = window.setInterval(load, 5000); window.addEventListener("beforeunload", () => clearInterval(timer)); }
  window.addEventListener("load", () => setTimeout(init, 400));
})();
