(function () {
    function diagrams() {
        const result = [];
        for (let index = 0; index < localStorage.length; index += 1) {
            const id = localStorage.key(index);
            try {
                const value = JSON.parse(localStorage.getItem(id));
                if (value && value.type === "drakon") {
                    result.push({ id, name: value.name || id });
                }
            } catch (_) {
                // В хранилище есть и настройки редактора, это не схемы.
            }
        }
        return result.sort((left, right) => left.name.localeCompare(right.name, "ru"));
    }

    function resolve(value) {
        const query = String(value || "").trim();
        if (!query) return null;
        return diagrams().find((diagram) => diagram.id === query || diagram.name === query) || null;
    }

    window.drakonWorkflowName = function (id) {
        const target = resolve(id);
        return target ? target.name : String(id || "следующая схема");
    };

    window.drakonWorkflowChooseTarget = function (current, onChosen) {
        const list = diagrams();
        if (!list.length) return;
        const currentDiagram = resolve(current);
        const cover = document.createElement("div");
        const box = document.createElement("div");
        const title = document.createElement("div");
        const select = document.createElement("select");
        const cancel = document.createElement("button");
        const save = document.createElement("button");
        cover.style.cssText = "position:fixed;inset:0;z-index:10000;background:rgba(0,0,0,.55);display:flex;align-items:center;justify-content:center";
        box.style.cssText = "width:420px;padding:20px;background:#243645;color:#dce8ed;border:1px solid #66cbe7;font:16px Arial";
        title.textContent = "Следующая схема";
        title.style.cssText = "margin-bottom:12px;font-weight:bold";
        select.style.cssText = "width:100%;padding:9px;margin-bottom:16px;background:#17242f;color:#e8f5f8;border:1px solid #66cbe7";
        for (const item of list) {
            const option = document.createElement("option");
            option.value = item.id;
            option.textContent = item.name;
            option.selected = currentDiagram && item.id === currentDiagram.id;
            select.appendChild(option);
        }
        cancel.textContent = "Отмена";
        save.textContent = "Выбрать";
        for (const button of [cancel, save]) button.style.cssText = "float:right;margin-left:8px;padding:8px 14px";
        cancel.onclick = () => cover.remove();
        save.onclick = () => { const target = resolve(select.value); cover.remove(); onChosen(target && target.id); };
        box.append(title, select, cancel, save);
        cover.appendChild(box);
        document.body.appendChild(cover);
    };

    window.drakonWorkflowFollow = function (targetId) {
        const target = resolve(targetId);
        if (!target) {
            window.alert("Целевая схема перехода не найдена.");
            return false;
        }
        if (!window.drakonTechLogic || typeof window.drakonTechLogic.goToFolder !== "function") {
            window.alert("Редактор ещё не готов к переходу.");
            return false;
        }
        window.drakonTechLogic.goToFolder(target.id, function () {});
        return true;
    };
})();
