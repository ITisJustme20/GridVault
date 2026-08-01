(function () {
    "use strict";

    const app = document.getElementById("concept-board-app");
    const core = window.GridVaultBoardCore;
    if (!app || !core) return;

    const editable = app.dataset.editable === "true";
    const viewport = document.getElementById("board-viewport");
    const world = document.getElementById("board-world");
    const emptyState = document.getElementById("board-empty");
    const status = document.getElementById("board-save-status");
    const retrySave = document.getElementById("board-retry-save");
    const zoomLabel = document.getElementById("board-zoom-level");
    const colorControl = document.getElementById("board-color");
    const layerUp = document.getElementById("layer-up");
    const layerDown = document.getElementById("layer-down");
    const deleteControl = document.getElementById("delete-element");
    let elements = JSON.parse(
        document.getElementById("board-data").textContent || "[]"
    );
    let selectedId = null;
    let view = {zoom: 1, panX: 0, panY: 0};
    let boardVersion = Number(app.dataset.boardVersion || 0);
    let changeGeneration = 0;
    let savedGeneration = 0;
    let saveTimer = null;
    let saveInFlight = false;
    let saveBlocked = false;
    let activeGesture = null;

    const defaults = {
        text: [220, 140, "New text note"],
        heading: [320, 80, "New heading"],
        rectangle: [240, 150, ""],
        circle: [160, 160, ""],
        arrow: [220, 70, "Direction"],
        label: [160, 56, "Label"],
        swatch: [150, 120, "Color"],
        reference: [260, 150, "Reference title"]
    };
    const textTypes = new Set([
        "text", "heading", "arrow", "label", "swatch", "reference"
    ]);

    function uid() {
        return "el_" + Math.random().toString(36).slice(2, 11);
    }

    function highestZ() {
        return elements.reduce(
            (highest, item) => Math.max(highest, item.z || 0),
            0
        );
    }

    function setSaveState(state, message) {
        status.dataset.state = state;
        status.textContent = message;
        retrySave.hidden = state !== "error" && state !== "conflict";
        retrySave.textContent = state === "conflict" ? "Reload board" : "Retry save";
    }

    function applyView() {
        // Transformed children can make an `overflow: hidden` element retain a
        // native scroll offset when a browser scrolls a focused control into
        // view. That offset lives outside our board coordinate model and makes
        // pointer math drift after zooming, so keep it pinned at the origin.
        viewport.scrollLeft = 0;
        viewport.scrollTop = 0;
        world.style.transform = (
            `translate(${view.panX}px, ${view.panY}px) scale(${view.zoom})`
        );
        zoomLabel.textContent = `${Math.round(view.zoom * 100)}%`;
    }

    function updateSelection() {
        world.querySelectorAll(".board-element").forEach(node => {
            node.classList.toggle("selected", node.dataset.id === selectedId);
        });
        const selected = elements.find(item => item.id === selectedId);
        const disabled = !editable || !selected;
        colorControl.disabled = disabled;
        layerUp.disabled = disabled;
        layerDown.disabled = disabled;
        deleteControl.disabled = disabled;
        if (selected) colorControl.value = selected.color;
    }

    function select(id) {
        selectedId = id;
        updateSelection();
    }

    function scheduleSave() {
        if (!editable || saveBlocked) return;
        changeGeneration += 1;
        setSaveState("dirty", "Unsaved changes");
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(flushSave, 500);
    }

    async function flushSave() {
        if (!editable || saveBlocked || changeGeneration === savedGeneration) {
            return;
        }
        if (saveInFlight) return;

        saveInFlight = true;
        const savingGeneration = changeGeneration;
        const snapshot = elements.map(item => ({...item}));
        setSaveState("saving", "Saving…");
        try {
            const response = await fetch(app.dataset.saveUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "Content-Type": "application/json",
                    "X-CSRFToken": app.dataset.csrf,
                    "X-Requested-With": "fetch"
                },
                body: JSON.stringify({
                    elements: snapshot,
                    base_version: boardVersion
                })
            });
            const payload = await response.json();
            if (response.status === 409) {
                saveBlocked = true;
                setSaveState(
                    "conflict",
                    "Newer board changes exist. Refresh to continue safely."
                );
                return;
            }
            if (!response.ok) {
                throw new Error(payload.error || "Board save failed.");
            }
            boardVersion = payload.board_version;
            savedGeneration = savingGeneration;
            if (changeGeneration === savedGeneration) {
                setSaveState("saved", "All changes saved");
            }
        } catch (error) {
            setSaveState("error", error.message || "Autosave failed.");
        } finally {
            saveInFlight = false;
            if (!saveBlocked && changeGeneration !== savedGeneration) {
                window.clearTimeout(saveTimer);
                saveTimer = window.setTimeout(flushSave, 80);
            }
        }
    }

    function contentNode(item) {
        if (item.type === "image") {
            const image = document.createElement("img");
            image.src = item.url;
            image.alt = item.content || "Uploaded concept";
            image.draggable = false;
            return image;
        }
        const content = document.createElement("div");
        content.className = "board-element-content";
        content.textContent = item.content;
        if (editable && textTypes.has(item.type)) {
            content.contentEditable = "plaintext-only";
            content.setAttribute("role", "textbox");
            content.setAttribute("aria-label", `Edit ${item.type} text`);
            content.spellcheck = true;
            content.addEventListener("pointerdown", event => {
                event.stopPropagation();
                select(item.id);
            });
            content.addEventListener("input", () => {
                item.content = content.textContent.slice(0, 1000);
                scheduleSave();
            });
        }
        return content;
    }

    function elementNode(item) {
        const node = document.createElement("article");
        node.className = `board-element board-${item.type}`;
        node.dataset.id = item.id;
        node.style.left = `${item.x}px`;
        node.style.top = `${item.y}px`;
        node.style.width = `${item.width}px`;
        node.style.height = `${item.height}px`;
        node.style.zIndex = item.z;
        node.style.setProperty("--element-color", item.color);
        node.tabIndex = 0;

        const grip = document.createElement("button");
        grip.type = "button";
        grip.className = "element-grip";
        grip.textContent = `Move · ${item.type}`;
        grip.setAttribute("aria-label", `Move ${item.type} element`);
        grip.disabled = !editable;
        node.append(grip, contentNode(item));

        if (item.type === "reference" && item.url) {
            const link = document.createElement("a");
            link.href = item.url;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            link.textContent = item.url;
            link.addEventListener("pointerdown", event => event.stopPropagation());
            node.append(link);
        }

        if (editable) {
            const resize = document.createElement("span");
            resize.className = "element-resize";
            resize.setAttribute("role", "button");
            resize.setAttribute("aria-label", `Resize ${item.type} element`);
            node.append(resize);
            grip.addEventListener("pointerdown", event => {
                beginElementGesture(event, item, node, "move");
            });
            resize.addEventListener("pointerdown", event => {
                beginElementGesture(event, item, node, "resize");
            });
        }

        node.addEventListener("pointerdown", event => {
            if (event.target.closest("a, button, [contenteditable], .element-resize")) {
                return;
            }
            select(item.id);
            if (editable) beginElementGesture(event, item, node, "move");
        });
        node.addEventListener("focus", () => select(item.id));
        if (item.id === selectedId) node.classList.add("selected");
        return node;
    }

    function render() {
        const ordered = elements.slice().sort((a, b) => a.z - b.z);
        world.replaceChildren(...ordered.map(elementNode));
        emptyState.hidden = elements.length !== 0;
        updateSelection();
    }

    function beginPointerGesture(event, gesture) {
        if (event.pointerType === "mouse" && event.button !== 0) return false;
        event.preventDefault();
        event.stopPropagation();
        activeGesture = {...gesture, pointerId: event.pointerId};
        viewport.setPointerCapture(event.pointerId);
        document.body.classList.add("board-is-interacting");
        return true;
    }

    function beginElementGesture(event, item, node, mode) {
        select(item.id);
        beginPointerGesture(event, {
            mode,
            item,
            node,
            startX: event.clientX,
            startY: event.clientY,
            original: {
                x: item.x,
                y: item.y,
                width: item.width,
                height: item.height
            }
        });
    }

    function beginPan(event) {
        const onCanvas = event.target === viewport || event.target === world;
        const allowedButton = event.button === 0 || event.button === 1;
        if (!onCanvas || !allowedButton) return;
        beginPointerGesture(event, {
            mode: "pan",
            startX: event.clientX,
            startY: event.clientY,
            original: {panX: view.panX, panY: view.panY}
        });
    }

    function updateGesture(event) {
        if (!activeGesture || event.pointerId !== activeGesture.pointerId) return;
        event.preventDefault();
        const deltaX = event.clientX - activeGesture.startX;
        const deltaY = event.clientY - activeGesture.startY;
        if (activeGesture.mode === "pan") {
            view.panX = activeGesture.original.panX + deltaX;
            view.panY = activeGesture.original.panY + deltaY;
            applyView();
            return;
        }

        if (activeGesture.mode === "move") {
            const geometry = core.moveGeometry(
                activeGesture.original,
                deltaX,
                deltaY,
                view.zoom
            );
            activeGesture.item.x = geometry.x;
            activeGesture.item.y = geometry.y;
            activeGesture.node.style.left = `${geometry.x}px`;
            activeGesture.node.style.top = `${geometry.y}px`;
        } else {
            const geometry = core.resizeGeometry(
                activeGesture.original,
                deltaX,
                deltaY,
                view.zoom
            );
            activeGesture.item.width = geometry.width;
            activeGesture.item.height = geometry.height;
            activeGesture.node.style.width = `${geometry.width}px`;
            activeGesture.node.style.height = `${geometry.height}px`;
        }
    }

    function endGesture(event) {
        if (!activeGesture || event.pointerId !== activeGesture.pointerId) return;
        const changedBoard = activeGesture.mode !== "pan";
        if (viewport.hasPointerCapture(event.pointerId)) {
            viewport.releasePointerCapture(event.pointerId);
        }
        activeGesture = null;
        document.body.classList.remove("board-is-interacting");
        if (changedBoard) scheduleSave();
    }

    function add(type, options = {}) {
        const [width, height, content] = defaults[type] || [200, 120, "New element"];
        const offset = (elements.length % 8) * 18;
        const centerX = (viewport.clientWidth / 2 - view.panX) / view.zoom;
        const centerY = (viewport.clientHeight / 2 - view.panY) / view.zoom;
        elements.push({
            id: uid(),
            type,
            x: Math.round(core.clamp(
                centerX - width / 2 + offset,
                0,
                core.WORLD_WIDTH - width
            )),
            y: Math.round(core.clamp(
                centerY - height / 2 + offset,
                0,
                core.WORLD_HEIGHT - height
            )),
            width,
            height,
            z: highestZ() + 1,
            content: options.content || content,
            color: options.color || "#67d8c4",
            url: options.url || ""
        });
        selectedId = elements[elements.length - 1].id;
        render();
        scheduleSave();
    }

    function setZoom(value, clientX, clientY) {
        const rect = viewport.getBoundingClientRect();
        view = core.zoomViewAt(
            view,
            value,
            clientX === undefined ? rect.left + rect.width / 2 : clientX,
            clientY === undefined ? rect.top + rect.height / 2 : clientY,
            rect
        );
        applyView();
    }

    document.querySelectorAll("[data-add]").forEach(button => {
        button.addEventListener("click", () => {
            const type = button.dataset.add;
            if (type === "reference") {
                const url = window.prompt("HTTPS reference URL (optional):", "");
                if (url === null) return;
                if (url) {
                    try {
                        if (new URL(url).protocol !== "https:") return;
                    } catch (_) {
                        return;
                    }
                }
                add(type, {url});
            } else add(type);
        });
    });

    deleteControl.addEventListener("click", () => {
        if (!selectedId) return;
        elements = elements.filter(item => item.id !== selectedId);
        selectedId = null;
        render();
        scheduleSave();
    });
    layerUp.addEventListener("click", () => {
        if (!selectedId) return;
        elements = core.reorder(elements, selectedId, "front");
        render();
        scheduleSave();
    });
    layerDown.addEventListener("click", () => {
        if (!selectedId) return;
        elements = core.reorder(elements, selectedId, "back");
        render();
        scheduleSave();
    });
    colorControl.addEventListener("input", event => {
        const item = elements.find(value => value.id === selectedId);
        if (!item) return;
        item.color = event.target.value;
        const node = world.querySelector(`[data-id="${item.id}"]`);
        if (node) node.style.setProperty("--element-color", item.color);
        scheduleSave();
    });

    document.getElementById("board-image-upload").addEventListener(
        "change",
        async event => {
            if (!event.target.files.length) return;
            setSaveState("saving", "Uploading image…");
            const body = new FormData();
            body.append("image", event.target.files[0]);
            body.append("usage", "board");
            body.append("csrf_token", app.dataset.csrf);
            try {
                const response = await fetch(app.dataset.uploadUrl, {
                    method: "POST",
                    credentials: "same-origin",
                    headers: {
                        "X-Requested-With": "fetch",
                        "X-CSRFToken": app.dataset.csrf,
                        "Accept": "application/json"
                    },
                    body
                });
                const payload = await response.json();
                if (!response.ok) throw new Error(payload.error);
                add("image", {
                    url: payload.url,
                    content: event.target.files[0].name
                });
            } catch (error) {
                setSaveState("error", error.message || "Upload failed.");
            }
            event.target.value = "";
        }
    );

    document.getElementById("zoom-in").addEventListener(
        "click",
        () => setZoom(view.zoom + 0.15)
    );
    document.getElementById("zoom-out").addEventListener(
        "click",
        () => setZoom(view.zoom - 0.15)
    );
    document.getElementById("reset-view").addEventListener("click", () => {
        view = {zoom: 1, panX: 0, panY: 0};
        applyView();
    });
    retrySave.addEventListener("click", () => {
        if (status.dataset.state === "conflict") {
            // The server has newer state. Discard this stale local copy instead
            // of offering a retry that could surprise the operator.
            savedGeneration = changeGeneration;
            window.location.reload();
            return;
        }
        saveBlocked = false;
        flushSave();
    });

    viewport.addEventListener("wheel", event => {
        event.preventDefault();
        if (event.ctrlKey || event.metaKey) {
            setZoom(
                view.zoom * Math.exp(-event.deltaY * 0.002),
                event.clientX,
                event.clientY
            );
        } else {
            view.panX -= event.deltaX || (event.shiftKey ? event.deltaY : 0);
            view.panY -= event.shiftKey ? 0 : event.deltaY;
            applyView();
        }
    }, {passive: false});
    viewport.addEventListener("pointerdown", beginPan);
    viewport.addEventListener("pointermove", updateGesture);
    viewport.addEventListener("pointerup", endGesture);
    viewport.addEventListener("pointercancel", endGesture);
    viewport.addEventListener("scroll", () => {
        if (viewport.scrollLeft || viewport.scrollTop) {
            viewport.scrollLeft = 0;
            viewport.scrollTop = 0;
        }
    });
    window.addEventListener("beforeunload", event => {
        if (editable && !saveBlocked && changeGeneration !== savedGeneration) {
            event.preventDefault();
            event.returnValue = "";
        }
    });

    render();
    applyView();
})();
