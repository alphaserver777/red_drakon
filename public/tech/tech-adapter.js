(function () {
    const metaKey = "drakon-tech-projects";
    const currentKey = "drakon-tech-current-project";

    function projects() {
        return JSON.parse(localStorage.getItem(metaKey) || "{}");
    }

    function saveProjects(value) {
        localStorage.setItem(metaKey, JSON.stringify(value));
    }

    function normalise(project) {
        return {
            name: project.name,
            language: project.language || "JS2604",
            outputFile: project.outputFile || project.output || `../${project.name}.js`,
            dependencies: project.dependencies || "",
            mainFun: project.mainFun || "",
            format: project.format || "unit"
        };
    }

    window.backend.getDocumentsPath = async () => "web://projects";
    window.backend.createProject = async (project) => {
        const path = `web://projects/${project.name}`;
        const all = projects();
        if (all[path]) throw new Error("Проект с таким именем уже существует");
        all[path] = normalise(project);
        saveProjects(all);
        return path;
    };
    window.backend.openProject = async (path) => {
        const all = projects();
        if (!all[path]) throw new Error("Проект не найден");
        localStorage.setItem(currentKey, path);
        return window.backend.openFolder(path);
    };
    window.backend.openProjectFile = async () => {
        const all = projects();
        const values = Object.keys(all);
        if (values.length === 0) return undefined;
        const answer = window.prompt("Имя проекта", all[values[0]].name);
        if (answer === null) return undefined;
        return values.find((path) => all[path].name === answer) || undefined;
    };
    window.backend.getProject = async () => {
        const current = localStorage.getItem(currentKey);
        return projects()[current] || {};
    };
    window.backend.updateProject = async (project) => {
        const current = localStorage.getItem(currentKey);
        if (!current) throw new Error("Проект не открыт");
        const all = projects();
        all[current] = normalise({ ...all[current], ...project });
        saveProjects(all);
    };
})();
