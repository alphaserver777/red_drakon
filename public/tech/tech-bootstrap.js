(function () {
    const originalSet = Storage.prototype.setItem;
    const originalRemove = Storage.prototype.removeItem;
    const originalClear = Storage.prototype.clear;
    let active = false;
    let queue = Promise.resolve();

    function send(change) {
        if (!active) return;
        queue = queue.then(() => fetch(`${window.location.pathname}api/tech-storage`, {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(change)
        })).catch((error) => console.error("Не удалось сохранить проект", error));
    }

    Storage.prototype.setItem = function (key, value) {
        originalSet.call(this, key, value);
        send({ op: "set", key, value: String(value) });
    };
    Storage.prototype.removeItem = function (key) {
        originalRemove.call(this, key);
        send({ op: "remove", key });
    };
    Storage.prototype.clear = function () {
        originalClear.call(this);
        send({ op: "clear" });
    };

    window.drakonTechStateReady = fetch(`${window.location.pathname}api/tech-state`, { cache: "no-store" })
        .then((response) => {
            if (!response.ok) throw new Error("Не удалось загрузить проекты");
            return response.json();
        })
        .then((saved) => {
            originalClear.call(localStorage);
            for (const [key, value] of Object.entries(saved)) originalSet.call(localStorage, key, value);
            active = true;
        });
})();
