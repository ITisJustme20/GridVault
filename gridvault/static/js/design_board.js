(function () {
    "use strict";

    const app = document.getElementById("concept-board-app");
    if (!app) return;

    const editable = app.dataset.editable === "true";
    const viewport = document.getElementById("board-viewport");
    const world = document.getElementById("board-world");
    const status = document.getElementById("board-save-status");
    const zoomLabel = document.getElementById("board-zoom-level");
    let elements = JSON.parse(document.getElementById("board-data").textContent || "[]");
    let selectedId = null;
    let zoom = 1;
    let panX = 0;
    let panY = 0;
    let saveTimer = null;

    const defaults = {
        text: [220, 140, "New text note"], heading: [320, 80, "New heading"],
        rectangle: [240, 150, ""], circle: [160, 160, ""], arrow: [220, 70, "Direction"],
        label: [160, 56, "Label"], swatch: [150, 120, "Color"], reference: [260, 150, "Reference title"]
    };

    function uid() { return "el_" + Math.random().toString(36).slice(2, 11); }
    function highestZ() { return elements.reduce((highest, item) => Math.max(highest, item.z || 0), 0); }
    function applyView() { world.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`; zoomLabel.textContent = `${Math.round(zoom * 100)}%`; }
    function select(id) { selectedId = id; render(); }
    function scheduleSave() {
        if (!editable) return;
        status.textContent = "Unsaved changes";
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(save, 700);
    }
    async function save() {
        status.textContent = "Saving…";
        try {
            const response = await fetch(app.dataset.saveUrl, {method: "POST", headers: {"Content-Type": "application/json", "X-CSRFToken": app.dataset.csrf}, body: JSON.stringify({elements})});
            const payload = await response.json();
            if (!response.ok) throw new Error(payload.error || "Save failed");
            status.textContent = "All changes saved";
        } catch (error) { status.textContent = error.message || "Autosave failed"; }
    }
    function contentNode(item) {
        if (item.type === "image") { const image = document.createElement("img"); image.src = item.url; image.alt = item.content || "Uploaded concept"; return image; }
        const content = document.createElement("div"); content.className = "board-element-content"; content.textContent = item.content;
        if (editable && !["rectangle", "circle"].includes(item.type)) {
            content.contentEditable = "plaintext-only";
            content.addEventListener("input", () => { item.content = content.textContent.slice(0, 1000); scheduleSave(); });
            content.addEventListener("pointerdown", event => event.stopPropagation());
        }
        return content;
    }
    function elementNode(item) {
        const node = document.createElement("article"); node.className = `board-element board-${item.type}${selectedId === item.id ? " selected" : ""}`;
        node.dataset.id = item.id; node.style.left = `${item.x}px`; node.style.top = `${item.y}px`; node.style.width = `${item.width}px`; node.style.height = `${item.height}px`; node.style.zIndex = item.z; node.style.setProperty("--element-color", item.color);
        const grip = document.createElement("button"); grip.type = "button"; grip.className = "element-grip"; grip.textContent = item.type; grip.disabled = !editable; node.append(grip, contentNode(item));
        if (item.type === "reference" && item.url) { const link = document.createElement("a"); link.href = item.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = item.url; node.append(link); }
        if (editable) {
            const resize = document.createElement("span"); resize.className = "element-resize"; node.append(resize);
            grip.addEventListener("pointerdown", event => beginMove(event, item));
            resize.addEventListener("pointerdown", event => beginResize(event, item));
        }
        node.addEventListener("pointerdown", () => select(item.id));
        return node;
    }
    function render() { world.replaceChildren(...elements.slice().sort((a, b) => a.z - b.z).map(elementNode)); }
    function pointerToWorld(event) { const rect = viewport.getBoundingClientRect(); return {x: (event.clientX - rect.left - panX) / zoom, y: (event.clientY - rect.top - panY) / zoom}; }
    function beginMove(event, item) {
        event.preventDefault(); event.stopPropagation(); select(item.id);
        const start = pointerToWorld(event), original = {x: item.x, y: item.y};
        function move(next) { const point = pointerToWorld(next); item.x = Math.round(original.x + point.x - start.x); item.y = Math.round(original.y + point.y - start.y); render(); }
        function end() { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); scheduleSave(); }
        window.addEventListener("pointermove", move); window.addEventListener("pointerup", end);
    }
    function beginResize(event, item) {
        event.preventDefault(); event.stopPropagation(); select(item.id);
        const start = pointerToWorld(event), original = {width: item.width, height: item.height};
        function move(next) { const point = pointerToWorld(next); item.width = Math.max(40, Math.round(original.width + point.x - start.x)); item.height = Math.max(40, Math.round(original.height + point.y - start.y)); render(); }
        function end() { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); scheduleSave(); }
        window.addEventListener("pointermove", move); window.addEventListener("pointerup", end);
    }
    function add(type, options = {}) {
        const [width, height, content] = defaults[type] || [200, 120, "New element"];
        const offset = (elements.length % 8) * 18;
        elements.push({id: uid(), type, x: Math.round((viewport.clientWidth / 2 - panX) / zoom - width / 2 + offset), y: Math.round((viewport.clientHeight / 2 - panY) / zoom - height / 2 + offset), width, height, z: highestZ() + 1, content: options.content || content, color: options.color || "#67d8c4", url: options.url || ""});
        select(elements[elements.length - 1].id); scheduleSave();
    }
    document.querySelectorAll("[data-add]").forEach(button => button.addEventListener("click", () => {
        const type = button.dataset.add;
        if (type === "reference") {
            const url = window.prompt("HTTPS reference URL (optional):", "");
            if (url === null) return;
            if (url) { try { if (new URL(url).protocol !== "https:") return; } catch (_) { return; } }
            add(type, {url});
        }
        else add(type);
    }));
    document.getElementById("delete-element").addEventListener("click", () => { if (!selectedId) return; elements = elements.filter(item => item.id !== selectedId); selectedId = null; render(); scheduleSave(); });
    document.getElementById("layer-up").addEventListener("click", () => { const item = elements.find(value => value.id === selectedId); if (item) { item.z = highestZ() + 1; render(); scheduleSave(); } });
    document.getElementById("layer-down").addEventListener("click", () => { const item = elements.find(value => value.id === selectedId); if (item) { item.z = Math.min(...elements.map(value => value.z)) - 1; render(); scheduleSave(); } });
    document.getElementById("board-color").addEventListener("input", event => { const item = elements.find(value => value.id === selectedId); if (item) { item.color = event.target.value; render(); scheduleSave(); } });
    document.getElementById("board-image-upload").addEventListener("change", async event => {
        if (!event.target.files.length) return;
        status.textContent = "Uploading image…";
        const body = new FormData(); body.append("image", event.target.files[0]); body.append("usage", "board"); body.append("csrf_token", app.dataset.csrf);
        try { const response = await fetch(app.dataset.uploadUrl, {method: "POST", headers: {"X-Requested-With": "fetch", "X-CSRFToken": app.dataset.csrf, "Accept": "application/json"}, body}); const payload = await response.json(); if (!response.ok) throw new Error(payload.error); add("image", {url: payload.url, content: event.target.files[0].name}); }
        catch (error) { status.textContent = error.message || "Upload failed"; }
        event.target.value = "";
    });
    function setZoom(value) { zoom = Math.min(2.5, Math.max(0.25, value)); applyView(); }
    document.getElementById("zoom-in").addEventListener("click", () => setZoom(zoom + 0.15));
    document.getElementById("zoom-out").addEventListener("click", () => setZoom(zoom - 0.15));
    document.getElementById("reset-view").addEventListener("click", () => { zoom = 1; panX = 0; panY = 0; applyView(); });
    viewport.addEventListener("wheel", event => { event.preventDefault(); setZoom(zoom + (event.deltaY < 0 ? 0.1 : -0.1)); }, {passive: false});
    viewport.addEventListener("pointerdown", event => {
        if (event.button !== 1 && !event.shiftKey) return;
        event.preventDefault(); const startX = event.clientX, startY = event.clientY, originalX = panX, originalY = panY;
        function move(next) { panX = originalX + next.clientX - startX; panY = originalY + next.clientY - startY; applyView(); }
        function end() { window.removeEventListener("pointermove", move); window.removeEventListener("pointerup", end); }
        window.addEventListener("pointermove", move); window.addEventListener("pointerup", end);
    });
    render(); applyView();
})();
