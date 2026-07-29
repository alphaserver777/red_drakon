(async function () {
    const response = await fetch("api/state", { cache: "no-store" });
    if (!response.ok) throw new Error("Не удалось загрузить схемы");
    const state = await response.json();

    localStorage.clear();
    for (const [key, value] of Object.entries(state)) localStorage.setItem(key, value);

    const setItem = Storage.prototype.setItem;
    const removeItem = Storage.prototype.removeItem;
    const clear = Storage.prototype.clear;
    let queue = Promise.resolve();

    function send(change) {
        queue = queue.then(() => fetch("api/storage", {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(change)
        })).catch((error) => console.error("Сохранение схемы не выполнено", error));
    }

    Storage.prototype.setItem = function (key, value) {
        setItem.call(this, key, value);
        send({ op: "set", key, value: String(value) });
    };
    Storage.prototype.removeItem = function (key) {
        removeItem.call(this, key);
        send({ op: "remove", key });
    };
    Storage.prototype.clear = function () {
        clear.call(this);
        send({ op: "clear" });
    };

    const script = document.createElement("script");
    script.src = "js/main.js";
    document.body.appendChild(script);
})().catch((error) => {
    document.body.textContent = `Ошибка загрузки DRAKON: ${error.message}`;
});
