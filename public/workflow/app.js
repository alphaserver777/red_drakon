let data; let selected;
const blocks = document.querySelector('#blocks');
const title = document.querySelector('#title');
const human = document.querySelector('#human');
const card = document.querySelector('#card');
const status = document.querySelector('#status');

function api(path, options) { return fetch(`${location.pathname}api/${path}`, options); }
function text(value) { return value === undefined ? '' : Array.isArray(value) ? value.join(', ') : String(value); }
function escapeHtml(value) { return String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char])); }
function render() {
  blocks.replaceChildren();
  Object.entries(data.diagram.items).filter(([, item]) => ['action','question'].includes(item.type)).forEach(([id, item]) => {
    const button = document.createElement('button'); button.className = `block ${id === selected ? 'active' : ''}`;
    button.innerHTML = `<span class="kind">#${id} · ${item.type}</span><br>${escapeHtml(item.content)}`;
    button.onclick = () => { selected = id; render(); }; blocks.append(button);
  });
  if (!selected) return;
  const item = data.diagram.items[selected]; const op = data.contract.operations[selected];
  title.textContent = `#${selected}: ${op.kind}`; human.textContent = item.content;
  card.className = 'card';
  card.innerHTML = `
    <label>Текст блока</label><textarea data-content>${escapeHtml(item.content)}</textarea>
    <label>Исполнитель</label><input data-key="executor" value="${escapeHtml(text(op.executor))}">
    <label>Команда</label><textarea data-key="command">${escapeHtml(text(op.command))}</textarea>
    <label>Входы</label><input data-key="inputs" value="${escapeHtml(text(op.inputs))}">
    <label>Доказательства</label><input data-key="evidence" value="${escapeHtml(text(op.evidence))}">
    <label>Условие</label><textarea data-key="note">${escapeHtml(text(op.note))}</textarea>`;
  card.querySelector('[data-content]').oninput = (event) => { item.content = event.target.value; human.textContent = item.content; };
  card.querySelectorAll('[data-key]').forEach((field) => field.oninput = () => {
    const key = field.dataset.key; op[key] = ['inputs','evidence'].includes(key) ? field.value.split(',').map(v => v.trim()).filter(Boolean) : field.value;
  });
}
async function load() { const response = await api('workflow/08-vpn-discovery'); data = await response.json(); render(); }
document.querySelector('#save').onclick = async () => { const response = await api('workflow/08-vpn-discovery', {method:'PUT',headers:{'content-type':'application/json'},body:JSON.stringify(data)}); status.textContent = response.ok ? 'Черновик сохранён' : `Ошибка: ${(await response.json()).error}`; };
document.querySelector('#export').onclick = () => { const blob = new Blob([JSON.stringify({diagram:data.diagram,contract:data.contract},null,2)],{type:'application/json'}); const link = Object.assign(document.createElement('a'),{href:URL.createObjectURL(blob),download:'08-vpn-discovery.bundle.json'}); link.click(); URL.revokeObjectURL(link.href); status.textContent = 'Набор скачан: закоммитьте и пометьте тегом вручную'; };
load().catch(error => status.textContent = `Ошибка загрузки: ${error.message}`);
