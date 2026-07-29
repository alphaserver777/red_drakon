"use strict";

const fs = require("node:fs/promises");
const path = require("node:path");

const baseUrl = process.env.DRAKON_WEB_URL || "http://127.0.0.1:13339/tech";
const seedDir = path.join(__dirname, "seed");
const projectPath = "web://projects/reglament";
const spaceId = "reglament";

async function request(url, options) {
  const response = await fetch(url, options);
  if (!response.ok) throw new Error(`${response.status} ${await response.text()}`);
  return response;
}

async function set(key, value) {
  await request(`${baseUrl}/api/tech-storage`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ op: "set", key, value: JSON.stringify(value) })
  });
}

async function main() {
  const current = await (await request(`${baseUrl}/api/tech-state`)).json();
  if (Object.keys(current).length > 0) throw new Error("Хранилище проектов не пусто; импорт остановлен.");

  const files = (await fs.readdir(seedDir)).filter((file) => file.endsWith(".drakon")).sort();
  const allFolders = { [`${spaceId} 1`]: true };
  const items = [];
  for (let index = 0; index < files.length; index += 1) {
    const file = files[index];
    const folderId = `d${String(index + 1).padStart(2, "0")}`;
    const fullId = `${spaceId} ${folderId}`;
    const diagram = JSON.parse(await fs.readFile(path.join(seedDir, file), "utf8"));
    diagram.name = file.slice(0, -7);
    diagram.parent = `${spaceId} 1`;
    allFolders[fullId] = true;
    items.push([fullId, diagram]);
  }

  await set("drakon-tech-projects", {
    [projectPath]: { name: "reglament", language: "JS2604", outputFile: "../reglament.js", dependencies: "", mainFun: "", format: "unit" }
  });
  await set("drakon-tech-current-project", projectPath);
  await set("projects", { [projectPath]: spaceId });
  await set("recent", [projectPath]);
  await set("dt-project-path", "web://projects");
  await set(`${spaceId}-folders`, allFolders);
  await set(`${spaceId} 1`, { type: "folder" });
  for (const [key, diagram] of items) await set(key, diagram);
  console.log(`Импортировано схем: ${items.length}`);
}

main().catch((error) => {
  console.error(error.message);
  process.exitCode = 1;
});
