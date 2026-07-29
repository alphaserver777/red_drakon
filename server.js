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

const server = http.createServer(async (request, response) => {
  try {
    const url = new URL(request.url, "http://localhost");
    const route = url.pathname.startsWith("/tech/api/") ? url.pathname.slice(5) : url.pathname.startsWith("/workflow/api/") ? url.pathname.slice(9) : url.pathname;
    if (request.method === "GET" && route === "/api/state") return reply(response, 200, JSON.stringify(state));
    if (request.method === "GET" && route === "/api/tech-state") return reply(response, 200, JSON.stringify(techState));
    if (request.method === "GET" && route === "/api/workflow-runs") return reply(response, 200, await workflowRuns(url));
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
