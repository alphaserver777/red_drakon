(function () {
  const workflow = "08-no-creds-siluet";
  let data, selected;
  const text = (value) => value === undefined ? "" : Array.isArray(value) ? value.join(", ") : String(value);
  const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  async function api(options) { return fetch(`api/workflow/${workflow}`, options); }
  function render() {
    const root = document.querySelector("#agent-contract");
    const choices = Object.entries(data.diagram.items).filter(([, item]) => ["action", "question"].includes(item.type));
    if (!selected) selected = choices[0]?.[0];
    const item = data.diagram.items[selected], op = data.contract.operations[selected];
    root.innerHTML = `<h2>Карточка агента</h2><p>Это машинная часть того же блока схемы. Агент исполняет только версию, экспортированную в Git.</p><label>Блок схемы</label><select id="agent-block">${choices.map(([id, value]) => `<option value="${id}" ${id === selected ? "selected" : ""}>#${id} · ${escapeHtml(value.content)}</option>`).join("")}</select><label>Текст блока</label><textarea data-content>${escapeHtml(item.content)}</textarea><label>Исполнитель</label><input data-key="executor" value="${escapeHtml(text(op.executor))}"><label>Команда</label><textarea data-key="command">${escapeHtml(text(op.command))}</textarea><label>Входы</label><input data-key="inputs" value="${escapeHtml(text(op.inputs))}"><label>Доказательства</label><input data-key="evidence" value="${escapeHtml(text(op.evidence))}"><label>Условие / переход</label><textarea data-key="note">${escapeHtml(text(op.note))}</textarea><button id="agent-save">Сохранить общий черновик</button><p id="agent-status" class="notice">Черновик не исполняется, пока не экспортирован, не закоммичен и не помечен тегом.</p>`;
    root.querySelector("#agent-block").onchange = (event) => { selected = event.target.value; render(); };
    root.querySelector("[data-content]").oninput = (event) => { item.content = event.target.value; };
    root.querySelectorAll("[data-key]").forEach((field) => field.oninput = () => { const key = field.dataset.key; op[key] = ["inputs", "evidence"].includes(key) ? field.value.split(",").map((v) => v.trim()).filter(Boolean) : field.value; });
    root.querySelector("#agent-save").onclick = async () => { const response = await api({ method: "PUT", headers: {"content-type":"application/json"}, body: JSON.stringify(data) }); root.querySelector("#agent-status").textContent = response.ok ? "Черновик синхронизирован со схемой." : `Ошибка: ${(await response.json()).error}`; };
  }
  async function init() {
    const response = await api(); data = await response.json();
    const panel = document.createElement("aside"); panel.id = "agent-contract"; document.body.append(panel);
    const toggle = document.createElement("button"); toggle.id = "agent-contract-toggle"; toggle.textContent = "Карточка агента"; toggle.onclick = () => panel.classList.toggle("agent-hidden"); document.body.append(toggle);
    render();
  }
  window.drakonTechStateReady.then(init).catch((error) => console.error("Карточка агента:", error));
})();
