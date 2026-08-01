(function () {
    "use strict";

    const app = document.getElementById("concept-board-app");
    const core = window.GridVaultBoardCore;
    if (!app || !core) return;

    const editable = app.dataset.editable === "true";
    const viewport = document.getElementById("board-viewport");
    const world = document.getElementById("board-world");
    const guideLayer = document.getElementById("board-guides");
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
    let copiedElement = null;
    let pasteCount = 0;

    const defaults = {
        text: [220, 140, "New text note"],
        heading: [320, 80, "New heading"],
        rectangle: [240, 150, ""],
        circle: [160, 160, ""],
        arrow: [220, 70, ""],
        label: [160, 56, "Label"],
        swatch: [150, 120, "Color"],
        reference: [260, 150, "Reference title"]
    };
    const textTypes = new Set([
        "text", "heading", "label", "swatch", "reference"
    ]);

    function applyArrowGeometry(item, geometry) {
        Object.assign(item, geometry);
    }

    elements.forEach(item => {
        if (item.type === "arrow") {
            applyArrowGeometry(item, core.normalizeArrow(item));
        }
    });

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
        const transform = (
            `translate(${view.panX}px, ${view.panY}px) scale(${view.zoom})`
        );
        world.style.transform = transform;
        guideLayer.style.transform = transform;
        zoomLabel.textContent = `${Math.round(view.zoom * 100)}%`;
    }

    function clearGuides() {
        guideLayer.replaceChildren();
    }

    function renderGuides(guides) {
        guideLayer.replaceChildren(...guides.map(guide => {
            const node = document.createElement("span");
            node.className = `board-guide ${guide.orientation} ${guide.type}`;
            let start = Math.min(guide.start, guide.end);
            let length = Math.abs(guide.end - guide.start);
            if (length < 24) {
                start -= (24 - length) / 2;
                length = 24;
            }
            if (guide.orientation === "vertical") {
                node.style.left = `${guide.position}px`;
                node.style.top = `${start}px`;
                node.style.width = `${1 / view.zoom}px`;
                node.style.height = `${length}px`;
            } else {
                node.style.left = `${start}px`;
                node.style.top = `${guide.position}px`;
                node.style.width = `${length}px`;
                node.style.height = `${1 / view.zoom}px`;
            }
            return node;
        }));
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

    function positionArrowNode(item, node) {
        const arrow = core.normalizeArrow(item);
        applyArrowGeometry(item, arrow);
        node.style.left = `${arrow.x}px`;
        node.style.top = `${arrow.y}px`;
        node.style.width = `${arrow.width}px`;
        node.style.height = `${arrow.height}px`;

        const startX = arrow.start_x - arrow.x;
        const startY = arrow.start_y - arrow.y;
        const endX = arrow.end_x - arrow.x;
        const endY = arrow.end_y - arrow.y;
        node.querySelectorAll("[data-arrow-line]").forEach(line => {
            line.setAttribute("x1", startX);
            line.setAttribute("y1", startY);
            line.setAttribute("x2", endX);
            line.setAttribute("y2", endY);
        });
        const svg = node.querySelector(".board-arrow-svg");
        if (svg) svg.setAttribute("viewBox", `0 0 ${arrow.width} ${arrow.height}`);
        const startHandle = node.querySelector('[data-arrow-handle="start"]');
        const endHandle = node.querySelector('[data-arrow-handle="end"]');
        const moveHandle = node.querySelector(".arrow-move-handle");
        if (startHandle) {
            startHandle.style.left = `${startX}px`;
            startHandle.style.top = `${startY}px`;
        }
        if (endHandle) {
            endHandle.style.left = `${endX}px`;
            endHandle.style.top = `${endY}px`;
        }
        if (moveHandle) {
            moveHandle.style.left = `${(startX + endX) / 2}px`;
            moveHandle.style.top = `${(startY + endY) / 2}px`;
        }
    }

    function appendArrowVisual(item, node) {
        const namespace = "http://www.w3.org/2000/svg";
        const svg = document.createElementNS(namespace, "svg");
        svg.classList.add("board-arrow-svg");
        svg.setAttribute("aria-hidden", "true");

        const definitions = document.createElementNS(namespace, "defs");
        const marker = document.createElementNS(namespace, "marker");
        const markerId = `arrowhead-${item.id}`;
        marker.id = markerId;
        marker.setAttribute("viewBox", "0 0 10 10");
        marker.setAttribute("refX", "8.5");
        marker.setAttribute("refY", "5");
        marker.setAttribute("markerWidth", "8");
        marker.setAttribute("markerHeight", "8");
        marker.setAttribute("orient", "auto-start-reverse");
        const arrowhead = document.createElementNS(namespace, "path");
        arrowhead.setAttribute("d", "M 0 0 L 10 5 L 0 10 z");
        arrowhead.setAttribute("fill", "currentColor");
        marker.append(arrowhead);
        definitions.append(marker);

        const hitLine = document.createElementNS(namespace, "line");
        hitLine.classList.add("board-arrow-hit");
        hitLine.dataset.arrowLine = "hit";
        const line = document.createElementNS(namespace, "line");
        line.classList.add("board-arrow-line");
        line.dataset.arrowLine = "visible";
        line.setAttribute("marker-end", `url(#${markerId})`);
        svg.append(definitions, hitLine, line);
        node.append(svg);

        if (editable) {
            const moveHandle = document.createElement("button");
            moveHandle.type = "button";
            moveHandle.className = "arrow-move-handle";
            moveHandle.setAttribute("aria-label", "Move arrow");
            const startHandle = document.createElement("button");
            startHandle.type = "button";
            startHandle.className = "arrow-endpoint arrow-startpoint";
            startHandle.dataset.arrowHandle = "start";
            startHandle.setAttribute("aria-label", "Drag arrow start point");
            const endHandle = document.createElement("button");
            endHandle.type = "button";
            endHandle.className = "arrow-endpoint arrow-endpoint-finish";
            endHandle.dataset.arrowHandle = "end";
            endHandle.setAttribute("aria-label", "Drag arrow end point");
            node.append(moveHandle, startHandle, endHandle);
            moveHandle.addEventListener("pointerdown", event => {
                beginElementGesture(event, item, node, "move");
            });
            startHandle.addEventListener("pointerdown", event => {
                beginArrowEndpointGesture(event, item, node, "start");
            });
            endHandle.addEventListener("pointerdown", event => {
                beginArrowEndpointGesture(event, item, node, "end");
            });
        }
        positionArrowNode(item, node);
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

        if (item.type === "arrow") {
            appendArrowVisual(item, node);
        } else {
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
                link.addEventListener(
                    "pointerdown",
                    event => event.stopPropagation()
                );
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
        clearGuides();
        const ordered = elements.slice().sort((a, b) => a.z - b.z);
        world.replaceChildren(...ordered.map(elementNode));
        emptyState.hidden = elements.length !== 0;
        updateSelection();
    }

    function beginPointerGesture(event, gesture) {
        if (event.pointerType === "mouse" && event.button !== 0) return false;
        clearGuides();
        event.preventDefault();
        event.stopPropagation();
        activeGesture = {...gesture, pointerId: event.pointerId};
        viewport.setPointerCapture(event.pointerId);
        document.body.classList.add("board-is-interacting");
        return true;
    }

    function beginElementGesture(event, item, node, mode) {
        select(item.id);
        const arrow = item.type === "arrow" ? core.normalizeArrow(item) : {};
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
                height: item.height,
                ...arrow
            }
        });
    }

    function beginArrowEndpointGesture(event, item, node, endpoint) {
        select(item.id);
        beginPointerGesture(event, {
            mode: `arrow-${endpoint}`,
            item,
            node,
            startX: event.clientX,
            startY: event.clientY,
            original: core.normalizeArrow(item)
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
            clearGuides();
            view.panX = activeGesture.original.panX + deltaX;
            view.panY = activeGesture.original.panY + deltaY;
            applyView();
            return;
        }

        if (activeGesture.mode === "move") {
            if (activeGesture.item.type === "arrow") {
                const proposed = core.moveArrow(
                    activeGesture.original,
                    deltaX,
                    deltaY,
                    view.zoom
                );
                const result = event.altKey
                    ? {geometry: proposed, guides: []}
                    : core.snapElementMove(
                        activeGesture.item,
                        proposed,
                        elements,
                        view.zoom
                    );
                applyArrowGeometry(activeGesture.item, result.geometry);
                positionArrowNode(activeGesture.item, activeGesture.node);
                renderGuides(result.guides);
                return;
            }
            const proposed = core.moveGeometry(
                activeGesture.original,
                deltaX,
                deltaY,
                view.zoom
            );
            const result = event.altKey
                ? {geometry: proposed, guides: []}
                : core.snapElementMove(
                    activeGesture.item,
                    proposed,
                    elements,
                    view.zoom
                );
            const geometry = result.geometry;
            activeGesture.item.x = geometry.x;
            activeGesture.item.y = geometry.y;
            activeGesture.node.style.left = `${geometry.x}px`;
            activeGesture.node.style.top = `${geometry.y}px`;
            renderGuides(result.guides);
        } else if (activeGesture.mode.startsWith("arrow-")) {
            const endpoint = activeGesture.mode.slice("arrow-".length);
            const proposed = core.moveArrowEndpoint(
                activeGesture.original,
                endpoint,
                deltaX,
                deltaY,
                view.zoom,
                !event.altKey
            );
            const result = event.altKey
                ? {geometry: proposed, guides: []}
                : core.snapArrowEndpoint(
                    activeGesture.item,
                    proposed,
                    endpoint,
                    elements,
                    view.zoom
                );
            applyArrowGeometry(activeGesture.item, result.geometry);
            positionArrowNode(activeGesture.item, activeGesture.node);
            renderGuides(result.guides);
        } else {
            clearGuides();
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
        clearGuides();
        if (changedBoard) scheduleSave();
    }

    function add(type, options = {}) {
        const [width, height, content] = defaults[type] || [200, 120, "New element"];
        const offset = (elements.length % 8) * 18;
        const centerX = (viewport.clientWidth / 2 - view.panX) / view.zoom;
        const centerY = (viewport.clientHeight / 2 - view.panY) / view.zoom;
        const item = {
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
        };
        if (type === "arrow") {
            item.start_x = item.x + 20;
            item.start_y = item.y + height / 2;
            item.end_x = item.x + width - 20;
            item.end_y = item.y + height / 2;
            applyArrowGeometry(item, core.normalizeArrow(item));
        }
        elements.push(item);
        selectedId = item.id;
        render();
        scheduleSave();
    }

    function copySelectedElement() {
        const selected = elements.find(item => item.id === selectedId);
        if (!selected) return false;
        copiedElement = {...selected};
        pasteCount = 0;
        return true;
    }

    function pasteCopiedElement() {
        if (!editable || !copiedElement) return false;
        pasteCount += 1;
        const duplicate = core.duplicateElement(
            copiedElement,
            uid(),
            highestZ() + 1,
            24 * pasteCount
        );
        elements.push(duplicate);
        selectedId = duplicate.id;
        render();
        scheduleSave();
        return true;
    }

    function isTextEntryTarget(target) {
        return target instanceof Element && Boolean(target.closest(
            "input, textarea, select, [contenteditable]"
        ));
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
            add(button.dataset.add);
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

    window.addEventListener("keydown", event => {
        if ((!event.ctrlKey && !event.metaKey) || event.altKey) return;
        if (isTextEntryTarget(event.target)) return;
        const key = event.key.toLowerCase();
        if (key === "c" && copySelectedElement()) {
            event.preventDefault();
        } else if (key === "v" && pasteCopiedElement()) {
            event.preventDefault();
        }
    });
    window.addEventListener("copy", event => {
        if (isTextEntryTarget(event.target) || !copySelectedElement()) return;
        event.preventDefault();
        if (event.clipboardData) {
            event.clipboardData.setData("text/plain", "GridVault board object");
        }
    });
    window.addEventListener("paste", event => {
        if (isTextEntryTarget(event.target) || !pasteCopiedElement()) return;
        event.preventDefault();
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
