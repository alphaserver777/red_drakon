"use strict";

const http = require("node:http");
const fs = require("node:fs/promises");
const path = require("node:path");

const root = __dirname;
const publicDir = path.join(root, "public");
const seedDir = path.join(root, "seed");
const dataDir = process.env.DRAKON_DATA_DIR || path.join(root, "data");
const statePath = path.join(dataDir, "state.json");
const techStatePath = path.join(dataDir, "tech-state.json");
const port = Number(process.env.PORT || 13339);
const workflowDiagrams = {
  "08-no-creds-siluet": "d09",
};
const mime = { ".css": "text/css; charset=utf-8", ".html": "text/html; charset=utf-8", ".ico": "image/x-icon", ".js": "application/javascript; charset=utf-8", ".json": "application/json; charset=utf-8", ".png": "image/png" };
let state;
let techState;
let writeQueue = Promise.resolve();

async function makeInitialState() {
  const names = (await fs.readdir(seedDir)).filter((name) => name.endsWith(".drakon")).sort();
  const ids = [];
  const initial = { "drakon-widget-version": "1.5.7" };
  for (const name of names) {
    const id = `reglament-${name.slice(0, -7)}`;
    const diagram = JSON.parse(await fs.readFile(path.join(seedDir, name), "utf8"));
    diagram.id = id;
    diagram.name ||= name.slice(0, -7);
    ids.push(id);
    initial[id] = JSON.stringify(diagram);
  }
  initial["diagram-list"] = JSON.stringify(ids);
  initial["current-diagram"] = ids[0];
  return initial;
}

async function loadState() {
  await fs.mkdir(dataDir, { recursive: true });
  try { state = JSON.parse(await fs.readFile(statePath, "utf8")); }
  catch (error) {
    if (error.code !== "ENOENT") throw error;
    state = await makeInitialState();
    await saveState();
  }
  try { techState = JSON.parse(await fs.readFile(techStatePath, "utf8")); }
  catch (error) {
    if (error.code !== "ENOENT") throw error;
    techState = {};
    await saveTechState();
  }
}

function saveState() {
  writeQueue = writeQueue.then(async () => {
    const temporary = `${statePath}.new`;
    await fs.writeFile(temporary, JSON.stringify(state, null, 2) + "\n", { mode: 0o640 });
    await fs.rename(temporary, statePath);
  });
  return writeQueue;
}

function saveTechState() {
  writeQueue = writeQueue.then(async () => {
    const temporary = `${techStatePath}.new`;
    await fs.writeFile(temporary, JSON.stringify(techState, null, 2) + "\n", { mode: 0o640 });
    await fs.rename(temporary, techStatePath);
  });
  return writeQueue;
}

async function approvedWorkflow(name) {
  if (!(name in workflowDiagrams)) throw Object.assign(new Error("Неизвестная схема"), { code: "ENOENT" });
  const diagram = JSON.parse(await fs.readFile(path.join(root, "workflows", `${name}.drakon`), "utf8"));
  return { diagram, source: "approved" };
}

async function syncTechDiagram(diagram) {
  let found = false;
  for (const [key, value] of Object.entries(techState)) {
    try {
      const candidate = JSON.parse(value);
      if (candidate?.name === diagram.name) {
        // DRAKON Tech может при сохранении убрать parent. Без него схема
        // остаётся в «Недавнее», но исчезает из дерева проекта.
        techState[key] = JSON.stringify({ ...diagram, parent: "reglament 1" });
        found = true;
      }
    } catch { /* не схема */ }
  }
  if (!found) {
    const folderKey = "reglament-folders";
    const folders = JSON.parse(techState[folderKey] || "{}");
    const diagramKey = `reglament ${workflowDiagrams[diagram.name]}`;
    folders[diagramKey] = true;
    techState[folderKey] = JSON.stringify(folders);
    techState[diagramKey] = JSON.stringify({ ...diagram, parent: "reglament 1" });
  }
  await saveTechState();
}

async function applyChange(target, change, save) {
  if (change.op === "clear") {
    for (const key of Object.keys(target)) delete target[key];
  } else if (change.op === "set" && typeof change.key === "string" && typeof change.value === "string") {
    target[change.key] = change.value;
  } else if (change.op === "remove" && typeof change.key === "string") {
    delete target[change.key];
  } else {
    throw new Error("Некорректное изменение");
  }
  await save();
}

async function readBody(request) {
  let body = "";
  for await (const chunk of request) {
    body += chunk;
    if (body.length > 1_000_000) throw new Error("Слишком большой запрос");
  }
  return JSON.parse(body);
}

function reply(response, status, body, type = "application/json; charset=utf-8") {
  response.writeHead(status, { "content-type": type, "cache-control": "no-store" });
  response.end(body);
}

async function workflowRuns(requestUrl) {
  const base = (process.env.OPS_PANEL_URL || "").replace(/\/$/, "");
  const token = process.env.DRAKON_VIEW_TOKEN || "";
  if (!/^https:\/\//.test(base) || !token) throw new Error("Наблюдение DRAKON не настроено");
  const query = requestUrl.searchParams.toString();
  const response = await fetch(`${base}/api/workflow-runs${query ? `?${query}` : ""}`, {
    headers: { authorization: `Bearer ${token}` }, cache: "no-store",
  });
  if (!response.ok) throw new Error(`Панель не выдала журнал: HTTP ${response.status}`);
  return await response.text();
}


function exportReglamentP04() {
  const raw = techState["reglament p04"];
  if (typeof raw !== "string") throw Object.assign(new Error("Схема reglament p04 не найдена"), { code: "ENOENT" });
  const diagram = JSON.parse(raw);
  const items = diagram.items && typeof diagram.items === "object" ? diagram.items : {};
  const errors = [], roles = {}, methods = [];
  for (const item of Object.values(items)) {
    const workflow = item.workflow && typeof item.workflow === "object" ? item.workflow : {};
    if (workflow.role) roles[workflow.role] = { item, workflow };
    const command = typeof workflow.command === "string" ? workflow.command.trim() : item.type === "shelf" && typeof item.text2 === "string" ? item.text2.trim() : "";
    if (!command) continue;
    const sourceId = typeof workflow.blockId === "string" ? workflow.blockId.trim() : "";
    if (!/^reglament\.p04\.[a-z][a-z0-9.-]{2,90}$/.test(sourceId)) {
      errors.push("У команды нет корректного идентификатора блока: " + String(item.content || item.text || "действие").slice(0, 120));
      continue;
    }
    methods.push({ id: "method." + sourceId.slice("reglament.p04.".length), title: String(item.content || item.text || "Действие").trim(), blockId: "reglament.p04.coverage", command, requires: Array.isArray(workflow.inputs) ? workflow.inputs : [], parameters: Array.isArray(workflow.outputs) ? workflow.outputs : [], executor: "local", commandIds: (workflow.commandIds || []).map(Number).filter(Number.isInteger) });
  }
  for (const role of ["entry", "load-network-data", "classify-candidates", "candidates-decision"]) {
    if (!roles[role]?.workflow?.blockId) errors.push("Не назначена роль p04: " + role);
  }
  if (!methods.length) errors.push("В p04 нет действий с командами.");
  if (errors.length) return { errors };
  const block = (role, kind, transitions, decisionMode) => ({ id: roles[role].workflow.blockId, kind, title: String(roles[role].item.content || roles[role].item.text || role).trim(), transitions, ...(decisionMode ? { decisionMode } : {}) });
  const terminal = "reglament.p04.end";
  const entry = block("entry", "decision", { yes: roles["load-network-data"].workflow.blockId, no: terminal }, "approval");
  const load = block("load-network-data", "action", { next: roles["classify-candidates"].workflow.blockId });
  const classify = block("classify-candidates", "action", { next: roles["candidates-decision"].workflow.blockId });
  const candidates = block("candidates-decision", "decision", { yes: "reglament.p04.coverage", no: terminal }, "approval");
  const coverage = { id: "reglament.p04.coverage", kind: "action", title: "Веер применимых проверок без учётных данных", transitions: { empty: terminal }, methods, decisionMode: "rule" };
  return { contract: { workflow: "reglament.p04", version: 1, startBlockId: entry.id, blocks: [entry, load, classify, candidates, coverage, { id: terminal, kind: "terminal", title: "Завершение p04", transitions: {} }], forbidden: ["network.scan_outside_scope"] } };
}

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    const route = url.pathname.startsWith("/tech/api/") ? url.pathname.slice(5) : url.pathname.startsWith("/workflow/api/") ? url.pathname.slice(9) : url.pathname;
    if (request.method === "GET" && route === "/api/state") return reply(response, 200, JSON.stringify(state));
    if (request.method === "GET" && route === "/api/tech-state") return reply(response, 200, JSON.stringify(techState));
    if (request.method === "GET" && route === "/api/workflow-runs") return reply(response, 200, await workflowRuns(url));
    if (request.method === "GET" && route === "/api/export/reglament-p04") {
      const exported = exportReglamentP04();
      return exported.errors ? reply(response, 422, JSON.stringify(exported)) : reply(response, 200, JSON.stringify(exported.contract));
    }
    if (request.method === "POST" && route === "/api/storage") {
      const change = await readBody(request);
      await applyChange(state, change, saveState);
      return reply(response, 204, "");
    }
    if (request.method === "POST" && route === "/api/tech-storage") {
      const change = await readBody(request);
      await applyChange(techState, change, saveTechState);
      return reply(response, 204, "");
    }
    if (request.method !== "GET" && request.method !== "HEAD") return reply(response, 405, "Метод не поддерживается", "text/plain; charset=utf-8");
    const relative = url.pathname.endsWith("/") ? `${url.pathname.slice(1)}index.html` : url.pathname.slice(1);
    const file = path.resolve(publicDir, relative);
    if (!file.startsWith(`${publicDir}${path.sep}`)) return reply(response, 403, "Запрещено", "text/plain; charset=utf-8");
    const content = await fs.readFile(file);
    response.writeHead(200, { "content-type": mime[path.extname(file)] || "application/octet-stream" });
    response.end(request.method === "HEAD" ? undefined : content);
  } catch (error) {
    reply(response, error.code === "ENOENT" ? 404 : 500, JSON.stringify({ error: error.message }));
  }
});

loadState().then(async () => {
  for (const name of Object.keys(workflowDiagrams)) {
    const approved = await approvedWorkflow(name);
    await syncTechDiagram(approved.diagram);
  }
  server.listen(port, "127.0.0.1", () => console.log(`DRAKON: http://127.0.0.1:${port}`));
}).catch((error) => { console.error(error); process.exitCode = 1; });
