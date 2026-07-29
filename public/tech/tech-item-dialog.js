(function () {
  let pending;
  const fields = [
    ["op", "Операция агента"], ["executor", "Исполнитель"], ["inputs", "Входы"],
    ["evidence", "Доказательства"], ["next", "Следующий блок / выход"]
  ];
  function item(id) {
    for (let index = 0; index < localStorage.length; index += 1) {
      try {
        const diagram = JSON.parse(localStorage.getItem(localStorage.key(index)) || "");
        if (diagram?.name === "08-no-creds-siluet" && diagram.items?.[id]) return diagram.items[id];
      } catch { /* не схема */ }
    }
  }
  window.drakonAgentDialog = (title, main) => {
    const match = String(title).match(/:\s*(\d+)\s*$/);
    if (!match) return;
    const id = match[1], source = item(id);
    if (!source?.agent) return;
    const panel = document.createElement("section");
    panel.style.cssText = "padding:10px;border-top:1px solid #607d8b;background:#18252d;color:#e7eef2;font:14px Arial";
    panel.innerHTML = `<strong>Исполнение этого же блока</strong><div style="font-size:12px;margin:4px 0 8px;color:#b8c9d2">Эти поля сохраняются внутри элемента схемы и читаются воркером.</div>`;
    const inputs = {};
    for (const [key, label] of fields) {
      const caption = document.createElement("label"); caption.textContent = label; caption.style.cssText = "display:block;margin-top:7px;color:#9fd5eb";
      const input = document.createElement(key === "next" ? "input" : "textarea");
      input.value = Array.isArray(source.agent[key]) ? source.agent[key].join(", ") : source.agent[key] || "";
      input.style.cssText = "box-sizing:border-box;width:100%;margin-top:3px;padding:5px;background:#0d151c;color:#f4f7f8;border:1px solid #607d8b;font:13px monospace";
      panel.append(caption, input); inputs[key] = input;
    }
    main.insertBefore(panel, main.lastElementChild);
    pending = { id, agent: Object.fromEntries(fields.map(([key]) => [key, ["inputs", "evidence"].includes(key) ? inputs[key].value.split(",").map((v) => v.trim()).filter(Boolean) : inputs[key].value.trim()])) };
    Object.values(inputs).forEach((input) => input.oninput = () => { pending.agent = Object.fromEntries(fields.map(([key]) => [key, ["inputs", "evidence"].includes(key) ? inputs[key].value.split(",").map((v) => v.trim()).filter(Boolean) : inputs[key].value.trim()])); });
  };
  window.drakonAgentSave = () => {};
  window.drakonAgentTake = (id) => pending?.id === String(id) ? pending.agent : undefined;
})();
