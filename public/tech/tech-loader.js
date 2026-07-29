(async function () {
    try {
        await window.drakonTechStateReady;
        for (const source of ["static/js/frontendmain.js", "static/js/project.js"]) {
            await new Promise((resolve, reject) => {
                const script = document.createElement("script");
                script.src = source;
                script.onload = resolve;
                script.onerror = reject;
                document.body.appendChild(script);
            });
        }
    } catch (error) {
        document.body.textContent = `Ошибка загрузки DRAKON Tech: ${error.message}`;
    }
})();
