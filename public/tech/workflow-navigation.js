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

    window.drakonWorkflowChooseTarget = function (current) {
        const list = diagrams();
        if (!list.length) return null;
        const currentDiagram = resolve(current);
        const answer = window.prompt(
            "Название следующей схемы. Доступны:\n" + list.map((item) => "• " + item.name).join("\n"),
            currentDiagram ? currentDiagram.name : list[0].name
        );
        if (answer === null) return null;
        const target = resolve(answer);
        if (!target) {
            window.alert("Схема с таким названием не найдена.");
            return null;
        }
        return target.id;
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
