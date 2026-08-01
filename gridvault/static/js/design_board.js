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
    const objectEditor = document.getElementById("board-object-editor");
    const layerUp = document.getElementById("layer-up");
    const layerDown = document.getElementById("layer-down");
    const deleteControl = document.getElementById("delete-element");
    const toolkitToggle = document.getElementById("toolkit-toggle");
    const toolkitMenu = document.getElementById("toolkit-menu");
    const connectorTool = document.getElementById("connector-tool");
    const connectorHint = document.getElementById("connector-hint");
    let elements = JSON.parse(document.getElementById("board-data").textContent || "[]");
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
    let connectorMode = null;

    const defaults = {
        text: [220, 140, "New text note", {}],
        rectangle: [240, 150, "", {}],
        arrow: [220, 70, "", {}],
        intel: [280, 190, "", {title: "INTEL", body: "New intelligence entry", classification: "", accent: "#67d8c4"}],
        heading: [340, 90, "", {text: "New heading", size: "32", alignment: "left", accent: "#67d8c4"}],
        signal: [280, 190, "", {title: "New signal", body: "Add the important detail.", signal_type: "Question", accent: "#f1c15c"}],
        reference: [280, 190, "Reference title", {title: "Reference title", notes: "Supporting notes", url: "", tag: ""}],
        swatch: [180, 140, "Color", {name: "Project color", note: ""}],
        image: [320, 220, "Uploaded concept", {}],
        circle: [170, 170, "", {}],
        zone: [440, 280, "", {name: "New zone", opacity: "18"}],
        calculator: [300, 250, "", {mode: "General arithmetic", input_a: "0", input_b: "0", operator: "+", result: "0", notes: ""}],
        chart: [350, 260, "", {title: "Data chart", chart_type: "Bar", labels: "Alpha, Beta, Gamma", values: "10, 18, 12", x_label: "", y_label: "", legend: true}],
        graph: [350, 270, "", {title: "Coordinate graph", x_label: "X", y_label: "Y", points: "0:0, 1:2, 2:1, 3:4", connected: true, grid: true}],
        code: [380, 280, "", {code: "// Add code or pseudocode", language: "Plain Text", filename: "", line_numbers: true, wrap: false}],
        architecture: [300, 210, "", {name: "Component", component_type: "Service", description: "System responsibility", technology: "", status: "Planned"}],
        database: [330, 280, "", {name: "table_name", database_type: "SQL", fields: "id | integer | primary key | required\nname | text | | required", notes: ""}],
        api: [340, 270, "", {method: "GET", route: "/api/resource", description: "Endpoint purpose", authentication: "Required", request: "", response: "", status_code: "200"}],
        logic: [290, 210, "", {logic_type: "Process", title: "Logic step", description: "Describe the program logic.", true_label: "True", false_label: "False"}],
        market: [350, 300, "", {symbol: "TICKER", name: "Asset name", asset_type: "Stock", price: "", change: "", status: "Watching", thesis: "Research thesis", risks: "Risk notes", history: ""}],
        minimap: [300, 220, "", {}]
    };
    const textTypes = new Set(["text"]);
    const typeLabels = {
        intel: "Intel", heading: "Heading", signal: "Signal", reference: "Reference",
        swatch: "Color", zone: "Zone", calculator: "Calculator", chart: "Chart",
        graph: "Graph", code: "Code", architecture: "Architecture", database: "Database",
        api: "API", logic: "Logic", market: "Market", minimap: "Mini Map"
    };
    const selectOptions = {
        signal_type: ["Question", "Warning", "Task", "Decision", "Approval", "Reminder"],
        alignment: ["left", "center", "right"],
        mode: ["General arithmetic", "Ohm's Law", "Electrical power", "Force", "Gear ratio"],
        operator: ["+", "-", "×", "÷"],
        chart_type: ["Line", "Bar", "Pie"],
        language: ["Python", "JavaScript", "HTML", "CSS", "SQL", "Java", "C", "C++", "C#", "Rust", "Plain Text"],
        component_type: ["Frontend", "Backend", "Service", "Server", "Storage", "Queue", "Authentication", "External System", "Hardware"],
        method: ["GET", "POST", "PUT", "PATCH", "DELETE"],
        logic_type: ["Start", "Process", "Condition", "Input", "Output", "Loop", "Return", "Error"],
        asset_type: ["Stock", "ETF", "Cryptocurrency", "Commodity", "Index", "Other"],
        status: ["Watching", "Researching", "Interested", "Owned", "Avoiding"]
    };
    const editorSchemas = {
        intel: [["title", "Title"], ["body", "Body", "textarea"], ["classification", "Classification or category"], ["accent", "Accent", "color"]],
        heading: [["text", "Text"], ["size", "Size"], ["alignment", "Alignment", "select"], ["accent", "Accent", "color"]],
        signal: [["signal_type", "Signal type", "select"], ["title", "Title"], ["body", "Body", "textarea"], ["accent", "Accent", "color"]],
        reference: [["title", "Title"], ["notes", "Notes", "textarea"], ["url", "HTTPS URL"], ["tag", "Tag"]],
        swatch: [["name", "Color name"], ["note", "HEX, RGB, or project use", "textarea"]],
        zone: [["name", "Zone name"], ["opacity", "Transparency percent"]],
        calculator: [["mode", "Mode", "select"], ["input_a", "Input A"], ["input_b", "Input B"], ["operator", "Operator", "select"], ["notes", "Notes", "textarea"]],
        chart: [["title", "Title"], ["chart_type", "Chart type", "select"], ["labels", "Labels (comma separated)", "textarea"], ["values", "Values (comma separated)", "textarea"], ["x_label", "X-axis label"], ["y_label", "Y-axis label"], ["legend", "Show legend", "checkbox"]],
        graph: [["title", "Title"], ["x_label", "X-axis label"], ["y_label", "Y-axis label"], ["points", "Points (x:y, x:y)", "textarea"], ["connected", "Connect points", "checkbox"], ["grid", "Show grid", "checkbox"]],
        code: [["filename", "Filename"], ["language", "Language", "select"], ["code", "Code", "textarea"], ["line_numbers", "Line numbers", "checkbox"], ["wrap", "Line wrapping", "checkbox"]],
        architecture: [["name", "Component name"], ["component_type", "Component type", "select"], ["description", "Description", "textarea"], ["technology", "Technology or platform"], ["status", "Status"]],
        database: [["name", "Table or collection"], ["database_type", "Database type"], ["fields", "Fields: name | type | key | nullable", "textarea"], ["notes", "Notes", "textarea"]],
        api: [["method", "HTTP method", "select"], ["route", "Route"], ["description", "Description", "textarea"], ["authentication", "Authentication"], ["request", "Request notes", "textarea"], ["response", "Response notes", "textarea"], ["status_code", "Expected status"]],
        logic: [["logic_type", "Logic type", "select"], ["title", "Title"], ["description", "Description", "textarea"], ["true_label", "True label"], ["false_label", "False label"]],
        market: [["symbol", "Symbol or ticker"], ["name", "Asset name"], ["asset_type", "Asset type", "select"], ["price", "Manual price"], ["change", "Percentage change"], ["status", "Position or watch status", "select"], ["thesis", "Research thesis", "textarea"], ["risks", "Risk notes", "textarea"], ["history", "Historical values", "textarea"]],
        connector: [["label", "Relationship label"]]
    };

    function applyArrowGeometry(item, geometry) { Object.assign(item, geometry); }
    elements.forEach(item => {
        item.data = item.data && typeof item.data === "object" ? item.data : {};
        if (item.type === "arrow") applyArrowGeometry(item, core.normalizeArrow(item));
    });

    function uid() {
        let id;
        do { id = "el_" + Math.random().toString(36).slice(2, 11); }
        while (elements.some(item => item.id === id));
        return id;
    }
    function highestZ() { return elements.reduce((max, item) => Math.max(max, item.z || 0), 0); }
    function lowestZ() { return elements.reduce((min, item) => Math.min(min, item.z || 0), 0); }
    function selectedElement() { return elements.find(item => item.id === selectedId); }
    function setSaveState(state, message) {
        status.dataset.state = state;
        status.textContent = message;
        retrySave.hidden = state !== "error" && state !== "conflict";
        retrySave.textContent = state === "conflict" ? "Reload board" : "Retry save";
    }
    function applyView() {
        viewport.scrollLeft = 0;
        viewport.scrollTop = 0;
        const transform = `translate(${view.panX}px, ${view.panY}px) scale(${view.zoom})`;
        world.style.transform = transform;
        guideLayer.style.transform = transform;
        zoomLabel.textContent = `${Math.round(view.zoom * 100)}%`;
        refreshMiniMaps();
    }
    function clearGuides() { guideLayer.replaceChildren(); }
    function renderGuides(guides) {
        guideLayer.replaceChildren(...guides.map(guide => {
            const node = document.createElement("span");
            node.className = `board-guide ${guide.orientation} ${guide.type}`;
            let start = Math.min(guide.start, guide.end);
            let length = Math.abs(guide.end - guide.start);
            if (length < 24) { start -= (24 - length) / 2; length = 24; }
            if (guide.orientation === "vertical") {
                Object.assign(node.style, {left: `${guide.position}px`, top: `${start}px`, width: `${1 / view.zoom}px`, height: `${length}px`});
            } else {
                Object.assign(node.style, {left: `${start}px`, top: `${guide.position}px`, width: `${length}px`, height: `${1 / view.zoom}px`});
            }
            return node;
        }));
    }
    function scheduleSave() {
        if (!editable || saveBlocked) return;
        changeGeneration += 1;
        setSaveState("dirty", "Unsaved changes");
        window.clearTimeout(saveTimer);
        saveTimer = window.setTimeout(flushSave, 500);
    }
    async function flushSave() {
        if (!editable || saveBlocked || changeGeneration === savedGeneration || saveInFlight) return;
        saveInFlight = true;
        const savingGeneration = changeGeneration;
        const snapshot = JSON.parse(JSON.stringify(elements));
        setSaveState("saving", "Saving…");
        try {
            const response = await fetch(app.dataset.saveUrl, {
                method: "POST", credentials: "same-origin",
                headers: {"Content-Type": "application/json", "X-CSRFToken": app.dataset.csrf, "X-Requested-With": "fetch"},
                body: JSON.stringify({elements: snapshot, base_version: boardVersion})
            });
            const payload = await response.json();
            if (response.status === 409) {
                saveBlocked = true;
                setSaveState("conflict", "Newer board changes exist. Refresh to continue safely.");
                return;
            }
            if (!response.ok) throw new Error(payload.error || "Board save failed.");
            boardVersion = payload.board_version;
            savedGeneration = savingGeneration;
            if (changeGeneration === savedGeneration) setSaveState("saved", "All changes saved");
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

    function addText(parent, className, text) {
        const node = document.createElement("div");
        node.className = className;
        node.textContent = text || "";
        parent.append(node);
        return node;
    }
    function parseNumbers(value) {
        return String(value || "").split(",").map(Number).filter(Number.isFinite);
    }
    function calculate(item) {
        const data = item.data;
        const a = Number(data.input_a);
        const b = Number(data.input_b);
        if (!Number.isFinite(a) || !Number.isFinite(b)) return "Enter numeric inputs";
        let result;
        if (data.mode === "Ohm's Law") result = b === 0 ? NaN : a / b;
        else if (data.mode === "Electrical power") result = a * b;
        else if (data.mode === "Force") result = a * b;
        else if (data.mode === "Gear ratio") result = a === 0 ? NaN : b / a;
        else if (data.operator === "+") result = a + b;
        else if (data.operator === "-") result = a - b;
        else if (data.operator === "×") result = a * b;
        else result = b === 0 ? NaN : a / b;
        data.result = Number.isFinite(result) ? String(Math.round(result * 10000) / 10000) : "Undefined";
        return data.result;
    }
    function svgElement(name, attributes = {}) {
        const node = document.createElementNS("http://www.w3.org/2000/svg", name);
        Object.entries(attributes).forEach(([key, value]) => node.setAttribute(key, value));
        return node;
    }
    function chartVisual(item, graphMode = false) {
        const svg = svgElement("svg", {viewBox: "0 0 300 150", role: "img", "aria-label": item.data.title || "Chart"});
        svg.classList.add("board-data-visual");
        if (graphMode) {
            if (item.data.grid !== false) for (let i = 20; i < 300; i += 30) {
                svg.append(svgElement("line", {x1: i, y1: 10, x2: i, y2: 140, class: "data-grid"}));
                if (i < 150) svg.append(svgElement("line", {x1: 10, y1: i, x2: 290, y2: i, class: "data-grid"}));
            }
            const points = String(item.data.points || "").split(",").map(pair => pair.split(":").map(Number)).filter(pair => pair.length === 2 && pair.every(Number.isFinite));
            if (points.length) {
                const xs = points.map(point => point[0]); const ys = points.map(point => point[1]);
                const minX = Math.min(...xs); const maxX = Math.max(...xs); const minY = Math.min(...ys); const maxY = Math.max(...ys);
                const mapped = points.map(point => [20 + ((point[0] - minX) / (maxX - minX || 1)) * 260, 130 - ((point[1] - minY) / (maxY - minY || 1)) * 110]);
                if (item.data.connected !== false) svg.append(svgElement("polyline", {points: mapped.map(point => point.join(",")).join(" "), class: "data-line"}));
                mapped.forEach(point => svg.append(svgElement("circle", {cx: point[0], cy: point[1], r: 4, class: "data-point"})));
            }
            return svg;
        }
        const values = parseNumbers(item.data.values);
        const max = Math.max(...values.map(Math.abs), 1);
        if (item.data.chart_type === "Pie") {
            const total = values.reduce((sum, value) => sum + Math.max(value, 0), 0) || 1;
            let offset = 0;
            values.forEach((value, index) => {
                const length = Math.max(value, 0) / total * 100;
                const circle = svgElement("circle", {cx: 150, cy: 75, r: 52, class: `pie-segment segment-${index % 5}`, "stroke-dasharray": `${length} ${100 - length}`, "stroke-dashoffset": -offset});
                offset += length; svg.append(circle);
            });
        } else if (item.data.chart_type === "Line") {
            const points = values.map((value, index) => `${20 + index * (260 / Math.max(values.length - 1, 1))},${130 - (value / max) * 105}`).join(" ");
            svg.append(svgElement("polyline", {points, class: "data-line"}));
        } else values.forEach((value, index) => {
            const width = 240 / Math.max(values.length, 1);
            const height = Math.abs(value) / max * 105;
            svg.append(svgElement("rect", {x: 25 + index * width, y: 130 - height, width: Math.max(width - 8, 4), height, class: "data-bar"}));
        });
        return svg;
    }
    function miniMapVisual(item) {
        const svg = svgElement("svg", {viewBox: `0 0 ${core.WORLD_WIDTH} ${core.WORLD_HEIGHT}`, role: "img", "aria-label": "Board overview"});
        svg.classList.add("board-minimap-svg");
        elements.filter(other => other.id !== item.id && other.type !== "connector").forEach(other => {
            const bounds = core.elementBounds(other);
            svg.append(svgElement("rect", {x: bounds.x, y: bounds.y, width: Math.max(bounds.width, 20), height: Math.max(bounds.height, 20), class: "minimap-object"}));
        });
        const visibleX = core.clamp(-view.panX / view.zoom, 0, core.WORLD_WIDTH);
        const visibleY = core.clamp(-view.panY / view.zoom, 0, core.WORLD_HEIGHT);
        svg.append(svgElement("rect", {x: visibleX, y: visibleY, width: viewport.clientWidth / view.zoom, height: viewport.clientHeight / view.zoom, class: "minimap-viewport"}));
        if (editable) svg.addEventListener("pointerdown", event => beginMiniMapGesture(event, item, svg));
        return svg;
    }
    function structuredContent(item) {
        const wrapper = document.createElement("div");
        wrapper.className = "board-structured-content";
        const data = item.data || {};
        addText(wrapper, "board-object-type", typeLabels[item.type] || item.type);
        if (item.type === "intel") { addText(wrapper, "object-title", data.title); addText(wrapper, "object-meta", data.classification); addText(wrapper, "object-body", data.body); }
        else if (item.type === "heading") { const heading = addText(wrapper, "object-heading", data.text || item.content); heading.style.fontSize = `${core.clamp(Number(data.size) || 32, 14, 72)}px`; heading.style.textAlign = ["left", "center", "right"].includes(data.alignment) ? data.alignment : "left"; }
        else if (item.type === "signal") { addText(wrapper, "object-meta", data.signal_type); addText(wrapper, "object-title", data.title); addText(wrapper, "object-body", data.body); }
        else if (item.type === "reference") { addText(wrapper, "object-title", data.title || item.content); addText(wrapper, "object-meta", data.tag); addText(wrapper, "object-body", data.notes); if (data.url || item.url) { const link = document.createElement("a"); link.href = data.url || item.url; link.target = "_blank"; link.rel = "noopener noreferrer"; link.textContent = data.url || item.url; link.addEventListener("pointerdown", event => event.stopPropagation()); wrapper.append(link); } }
        else if (item.type === "swatch") { const chip = document.createElement("div"); chip.className = "color-chip"; chip.style.background = item.color; wrapper.append(chip); addText(wrapper, "object-title", data.name || item.content); addText(wrapper, "object-body", data.note); }
        else if (item.type === "zone") addText(wrapper, "zone-name", data.name);
        else if (item.type === "calculator") { addText(wrapper, "object-meta", data.mode); addText(wrapper, "calculation", `${data.input_a} ${data.mode === "General arithmetic" ? data.operator : "·"} ${data.input_b} = ${calculate(item)}`); addText(wrapper, "object-body", data.notes); }
        else if (item.type === "chart") { addText(wrapper, "object-title", data.title); wrapper.append(chartVisual(item)); addText(wrapper, "axis-copy", [data.x_label, data.y_label].filter(Boolean).join(" / ")); }
        else if (item.type === "graph") { addText(wrapper, "object-title", data.title); wrapper.append(chartVisual(item, true)); addText(wrapper, "axis-copy", `${data.x_label || "X"} / ${data.y_label || "Y"}`); }
        else if (item.type === "code") { addText(wrapper, "object-meta", [data.language, data.filename].filter(Boolean).join(" · ")); const pre = document.createElement("pre"); pre.className = data.wrap ? "code-wrap" : ""; const lines = String(data.code || "").split("\n"); pre.textContent = data.line_numbers ? lines.map((line, index) => `${String(index + 1).padStart(2, "0")}  ${line}`).join("\n") : data.code; wrapper.append(pre); }
        else if (item.type === "architecture") { addText(wrapper, "object-meta", data.component_type); addText(wrapper, "object-title", data.name); addText(wrapper, "object-body", data.description); addText(wrapper, "object-footer", [data.technology, data.status].filter(Boolean).join(" · ")); }
        else if (item.type === "database") { addText(wrapper, "object-meta", data.database_type); addText(wrapper, "object-title", data.name); const fields = document.createElement("pre"); fields.className = "database-fields"; fields.textContent = data.fields; wrapper.append(fields); addText(wrapper, "object-footer", data.notes); }
        else if (item.type === "api") { addText(wrapper, "api-route", `${data.method} ${data.route}`); addText(wrapper, "object-body", data.description); addText(wrapper, "object-meta", `${data.authentication} · ${data.status_code}`); addText(wrapper, "object-footer", [data.request, data.response].filter(Boolean).join(" / ")); }
        else if (item.type === "logic") { addText(wrapper, "object-meta", data.logic_type); addText(wrapper, "object-title", data.title); addText(wrapper, "object-body", data.description); if (data.logic_type === "Condition") addText(wrapper, "object-footer", `${data.true_label} / ${data.false_label}`); }
        else if (item.type === "market") { addText(wrapper, "market-symbol", data.symbol); addText(wrapper, "object-title", data.name); addText(wrapper, "market-price", [data.price, data.change && `${data.change}%`].filter(Boolean).join(" · ")); addText(wrapper, "object-meta", `${data.asset_type} · ${data.status}`); addText(wrapper, "object-body", data.thesis); addText(wrapper, "object-footer", data.risks); const history = parseNumbers(data.history); if (history.length > 1) wrapper.append(chartVisual({data: {title: data.symbol, chart_type: "Line", values: data.history}})); }
        else if (item.type === "minimap") wrapper.append(miniMapVisual(item));
        return wrapper;
    }
    function contentNode(item) {
        if (item.type === "image") { const image = document.createElement("img"); image.src = item.url; image.alt = item.content || "Uploaded concept"; image.draggable = false; return image; }
        if (typeLabels[item.type]) return structuredContent(item);
        const content = document.createElement("div");
        content.className = "board-element-content";
        content.textContent = item.content;
        if (editable && textTypes.has(item.type)) {
            content.contentEditable = "plaintext-only"; content.setAttribute("role", "textbox"); content.setAttribute("aria-label", `Edit ${item.type} text`); content.spellcheck = true;
            content.addEventListener("pointerdown", event => { event.stopPropagation(); select(item.id); });
            content.addEventListener("input", () => { item.content = content.textContent.slice(0, 1000); scheduleSave(); });
        }
        return content;
    }

    function positionLineNode(item, node, geometry) {
        Object.assign(item, geometry);
        Object.assign(node.style, {left: `${geometry.x}px`, top: `${geometry.y}px`, width: `${geometry.width}px`, height: `${geometry.height}px`});
        const startX = geometry.start_x - geometry.x; const startY = geometry.start_y - geometry.y; const endX = geometry.end_x - geometry.x; const endY = geometry.end_y - geometry.y;
        node.querySelectorAll("[data-arrow-line]").forEach(line => { line.setAttribute("x1", startX); line.setAttribute("y1", startY); line.setAttribute("x2", endX); line.setAttribute("y2", endY); });
        const svg = node.querySelector(".board-arrow-svg"); if (svg) svg.setAttribute("viewBox", `0 0 ${geometry.width} ${geometry.height}`);
        [["start", startX, startY], ["end", endX, endY]].forEach(([name, x, y]) => { const handle = node.querySelector(`[data-arrow-handle="${name}"]`); if (handle) Object.assign(handle.style, {left: `${x}px`, top: `${y}px`}); });
        const move = node.querySelector(".arrow-move-handle"); if (move) Object.assign(move.style, {left: `${(startX + endX) / 2}px`, top: `${(startY + endY) / 2}px`});
        const label = node.querySelector(".connector-label"); if (label) Object.assign(label.style, {left: `${(startX + endX) / 2}px`, top: `${(startY + endY) / 2}px`});
    }
    function appendLineVisual(item, node, connector = false) {
        const svg = svgElement("svg", {"aria-hidden": "true"}); svg.classList.add("board-arrow-svg");
        if (!connector) {
            const defs = svgElement("defs"); const marker = svgElement("marker", {id: `arrowhead-${item.id}`, viewBox: "0 0 10 10", refX: "8.5", refY: "5", markerWidth: "8", markerHeight: "8", orient: "auto-start-reverse"}); marker.append(svgElement("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: "currentColor"})); defs.append(marker); svg.append(defs);
        }
        const hit = svgElement("line", {class: "board-arrow-hit", "data-arrow-line": "hit"}); const line = svgElement("line", {class: connector ? "board-connector-line" : "board-arrow-line", "data-arrow-line": "visible"}); if (!connector) line.setAttribute("marker-end", `url(#arrowhead-${item.id})`); svg.append(hit, line); node.append(svg);
        if (connector) { const label = document.createElement("span"); label.className = "connector-label"; label.textContent = item.data.label || ""; node.append(label); const source = elements.find(other => other.id === item.source_id); const target = elements.find(other => other.id === item.target_id); if (source && target) positionLineNode(item, node, core.connectorGeometry(source, target)); return; }
        if (editable) {
            const move = document.createElement("button"); move.type = "button"; move.className = "arrow-move-handle"; move.setAttribute("aria-label", "Move arrow");
            const start = document.createElement("button"); start.type = "button"; start.className = "arrow-endpoint arrow-startpoint"; start.dataset.arrowHandle = "start"; start.setAttribute("aria-label", "Drag arrow start point");
            const end = document.createElement("button"); end.type = "button"; end.className = "arrow-endpoint arrow-endpoint-finish"; end.dataset.arrowHandle = "end"; end.setAttribute("aria-label", "Drag arrow end point"); node.append(move, start, end);
            move.addEventListener("pointerdown", event => beginElementGesture(event, item, node, "move")); start.addEventListener("pointerdown", event => beginArrowEndpointGesture(event, item, node, "start")); end.addEventListener("pointerdown", event => beginArrowEndpointGesture(event, item, node, "end"));
        }
        positionLineNode(item, node, core.normalizeArrow(item));
    }
    function elementNode(item) {
        const node = document.createElement("article"); node.className = `board-element board-${item.type}`; node.dataset.id = item.id;
        Object.assign(node.style, {left: `${item.x}px`, top: `${item.y}px`, width: `${item.width}px`, height: `${item.height}px`, zIndex: item.z}); node.style.setProperty("--element-color", item.color); node.tabIndex = 0;
        if (item.type === "arrow" || item.type === "connector") appendLineVisual(item, node, item.type === "connector");
        else {
            const grip = document.createElement("button"); grip.type = "button"; grip.className = "element-grip"; grip.textContent = `Move · ${typeLabels[item.type] || item.type}`; grip.setAttribute("aria-label", `Move ${item.type} object`); grip.disabled = !editable; node.append(grip, contentNode(item));
            if (item.type === "zone") node.style.setProperty("--zone-opacity", `${core.clamp(Number(item.data.opacity) || 18, 5, 70)}%`);
            if (editable) { const resize = document.createElement("span"); resize.className = "element-resize"; resize.setAttribute("role", "button"); resize.setAttribute("aria-label", `Resize ${item.type} object`); node.append(resize); grip.addEventListener("pointerdown", event => beginElementGesture(event, item, node, "move")); resize.addEventListener("pointerdown", event => beginElementGesture(event, item, node, "resize")); }
        }
        node.addEventListener("pointerdown", event => {
            if (event.target.closest("a, button, input, textarea, select, [contenteditable], .element-resize, .board-minimap-svg")) return;
            if (connectorMode && item.type !== "connector") { event.preventDefault(); event.stopPropagation(); chooseConnectorTarget(item); return; }
            select(item.id); if (editable && item.type !== "connector") beginElementGesture(event, item, node, "move");
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
    function refreshDerived() {
        elements.filter(item => item.type === "connector").forEach(item => {
            const source = elements.find(other => other.id === item.source_id); const target = elements.find(other => other.id === item.target_id); const node = world.querySelector(`[data-id="${item.id}"]`);
            if (source && target && node) positionLineNode(item, node, core.connectorGeometry(source, target));
        });
        refreshMiniMaps();
    }
    function refreshMiniMaps() {
        elements.filter(item => item.type === "minimap").forEach(item => { const node = world.querySelector(`[data-id="${item.id}"] .board-structured-content`); if (node) { const prior = node.querySelector(".board-minimap-svg"); const next = miniMapVisual(item); if (prior) prior.replaceWith(next); else node.append(next); } });
    }
    function updateSelection() {
        world.querySelectorAll(".board-element").forEach(node => node.classList.toggle("selected", node.dataset.id === selectedId));
        const selected = selectedElement(); const disabled = !editable || !selected;
        colorControl.disabled = disabled; layerUp.disabled = disabled; layerDown.disabled = disabled; deleteControl.disabled = disabled;
        if (selected) colorControl.value = selected.color;
        renderObjectEditor(selected);
    }
    function select(id) { selectedId = id; updateSelection(); }
    function renderObjectEditor(item) {
        objectEditor.replaceChildren();
        if (!item) { addText(objectEditor, "editor-empty", "Select an object to edit its details."); return; }
        const schema = editorSchemas[item.type];
        if (!schema) { addText(objectEditor, "editor-empty", item.type === "text" ? "Edit note text directly on the board." : "Use the accent and layer controls below."); return; }
        item.data = item.data || {};
        schema.forEach(([key, label, kind = "input"]) => {
            const field = document.createElement("label"); field.textContent = label;
            let control;
            if (kind === "select") { control = document.createElement("select"); (selectOptions[key] || []).forEach(value => { const option = document.createElement("option"); option.value = value; option.textContent = value; option.selected = item.data[key] === value; control.append(option); }); }
            else if (kind === "textarea") control = document.createElement("textarea");
            else { control = document.createElement("input"); control.type = kind === "checkbox" ? "checkbox" : kind === "color" ? "color" : "text"; }
            control.disabled = !editable; control.dataset.editorKey = key;
            if (kind === "checkbox") control.checked = item.data[key] !== false; else control.value = item.data[key] ?? "";
            control.addEventListener("change", () => {
                item.data[key] = kind === "checkbox" ? control.checked : String(control.value).slice(0, kind === "textarea" ? 4000 : 500);
                if (key === "accent" && /^#[0-9a-f]{6}$/i.test(item.data[key])) { item.color = item.data[key]; colorControl.value = item.color; }
                if (item.type === "reference") item.url = item.data.url || "";
                render(); scheduleSave();
            });
            field.append(control); objectEditor.append(field);
        });
    }

    function beginPointerGesture(event, gesture) {
        if (event.pointerType === "mouse" && event.button !== 0) return false;
        clearGuides(); event.preventDefault(); event.stopPropagation(); activeGesture = {...gesture, pointerId: event.pointerId}; viewport.setPointerCapture(event.pointerId); document.body.classList.add("board-is-interacting"); return true;
    }
    function beginElementGesture(event, item, node, mode) {
        if (connectorMode) { chooseConnectorTarget(item); return; }
        select(item.id); const arrow = item.type === "arrow" ? core.normalizeArrow(item) : {};
        beginPointerGesture(event, {mode, item, node, startX: event.clientX, startY: event.clientY, original: {x: item.x, y: item.y, width: item.width, height: item.height, ...arrow}});
    }
    function beginArrowEndpointGesture(event, item, node, endpoint) { select(item.id); beginPointerGesture(event, {mode: `arrow-${endpoint}`, item, node, startX: event.clientX, startY: event.clientY, original: core.normalizeArrow(item)}); }
    function beginMiniMapGesture(event, item, svg) { select(item.id); beginPointerGesture(event, {mode: "minimap-navigate", item, svg}); navigateFromMiniMap(event, svg); }
    function navigateFromMiniMap(event, svg) { const rect = svg.getBoundingClientRect(); const worldX = core.clamp((event.clientX - rect.left) / rect.width * core.WORLD_WIDTH, 0, core.WORLD_WIDTH); const worldY = core.clamp((event.clientY - rect.top) / rect.height * core.WORLD_HEIGHT, 0, core.WORLD_HEIGHT); view.panX = viewport.clientWidth / 2 - worldX * view.zoom; view.panY = viewport.clientHeight / 2 - worldY * view.zoom; applyView(); }
    function beginPan(event) { const onCanvas = event.target === viewport || event.target === world; const allowedButton = event.button === 0 || event.button === 1; if (!onCanvas || !allowedButton) return; beginPointerGesture(event, {mode: "pan", startX: event.clientX, startY: event.clientY, original: {panX: view.panX, panY: view.panY}}); }
    function updateGesture(event) {
        if (!activeGesture || event.pointerId !== activeGesture.pointerId) return;
        event.preventDefault();
        if (activeGesture.mode === "minimap-navigate") { navigateFromMiniMap(event, activeGesture.svg); return; }
        const deltaX = event.clientX - activeGesture.startX; const deltaY = event.clientY - activeGesture.startY;
        if (activeGesture.mode === "pan") { clearGuides(); view.panX = activeGesture.original.panX + deltaX; view.panY = activeGesture.original.panY + deltaY; applyView(); return; }
        if (activeGesture.mode === "move") {
            if (activeGesture.item.type === "arrow") {
                const proposed = core.moveArrow(activeGesture.original, deltaX, deltaY, view.zoom); const result = event.altKey ? {geometry: proposed, guides: []} : core.snapElementMove(activeGesture.item, proposed, elements, view.zoom); applyArrowGeometry(activeGesture.item, result.geometry); positionLineNode(activeGesture.item, activeGesture.node, result.geometry); renderGuides(result.guides);
            } else {
                const proposed = core.moveGeometry(activeGesture.original, deltaX, deltaY, view.zoom); const result = event.altKey ? {geometry: proposed, guides: []} : core.snapElementMove(activeGesture.item, proposed, elements, view.zoom); activeGesture.item.x = result.geometry.x; activeGesture.item.y = result.geometry.y; Object.assign(activeGesture.node.style, {left: `${result.geometry.x}px`, top: `${result.geometry.y}px`}); renderGuides(result.guides);
            }
            refreshDerived(); return;
        }
        if (activeGesture.mode.startsWith("arrow-")) {
            const endpoint = activeGesture.mode.slice("arrow-".length); const proposed = core.moveArrowEndpoint(activeGesture.original, endpoint, deltaX, deltaY, view.zoom, !event.altKey); const result = event.altKey ? {geometry: proposed, guides: []} : core.snapArrowEndpoint(activeGesture.item, proposed, endpoint, elements, view.zoom); applyArrowGeometry(activeGesture.item, result.geometry); positionLineNode(activeGesture.item, activeGesture.node, result.geometry); renderGuides(result.guides); refreshDerived(); return;
        }
        clearGuides(); const geometry = core.resizeGeometry(activeGesture.original, deltaX, deltaY, view.zoom); activeGesture.item.width = geometry.width; activeGesture.item.height = geometry.height; Object.assign(activeGesture.node.style, {width: `${geometry.width}px`, height: `${geometry.height}px`}); refreshDerived();
    }
    function endGesture(event) {
        if (!activeGesture || event.pointerId !== activeGesture.pointerId) return;
        const changedBoard = !["pan", "minimap-navigate"].includes(activeGesture.mode); if (viewport.hasPointerCapture(event.pointerId)) viewport.releasePointerCapture(event.pointerId); activeGesture = null; document.body.classList.remove("board-is-interacting"); clearGuides(); if (changedBoard) scheduleSave();
    }

    function add(type, options = {}) {
        if (!editable) return null;
        const [width, height, content, initialData] = defaults[type] || [200, 120, "New object", {}]; const offset = (elements.length % 8) * 18; const centerX = (viewport.clientWidth / 2 - view.panX) / view.zoom; const centerY = (viewport.clientHeight / 2 - view.panY) / view.zoom;
        const item = {id: uid(), type, x: Math.round(core.clamp(centerX - width / 2 + offset, 0, core.WORLD_WIDTH - width)), y: Math.round(core.clamp(centerY - height / 2 + offset, 0, core.WORLD_HEIGHT - height)), width, height, z: type === "zone" ? lowestZ() - 1 : highestZ() + 1, content: options.content || content, color: options.color || initialData.accent || "#67d8c4", url: options.url || "", data: {...initialData, ...(options.data || {})}};
        if (type === "arrow") { item.start_x = item.x + 20; item.start_y = item.y + height / 2; item.end_x = item.x + width - 20; item.end_y = item.y + height / 2; applyArrowGeometry(item, core.normalizeArrow(item)); }
        elements.push(item); selectedId = item.id; render(); scheduleSave(); return item;
    }
    function beginConnectorMode() { if (!editable) return; connectorMode = {sourceId: null}; connectorTool.dataset.active = "true"; connectorHint.hidden = false; connectorHint.textContent = "Select a source object."; }
    function stopConnectorMode() { connectorMode = null; connectorTool.dataset.active = "false"; connectorHint.hidden = true; }
    function chooseConnectorTarget(item) {
        if (!connectorMode || item.type === "connector" || item.type === "minimap") return;
        if (!connectorMode.sourceId) { connectorMode.sourceId = item.id; select(item.id); connectorHint.textContent = "Select a destination object."; return; }
        if (connectorMode.sourceId === item.id) { connectorHint.textContent = "Choose a different destination object."; return; }
        const source = elements.find(other => other.id === connectorMode.sourceId); if (!source) { stopConnectorMode(); return; }
        const geometry = core.connectorGeometry(source, item); const connector = {id: uid(), type: "connector", source_id: source.id, target_id: item.id, ...geometry, z: highestZ() + 1, content: "", color: "#67d8c4", url: "", data: {label: ""}}; elements.push(connector); selectedId = connector.id; stopConnectorMode(); render(); scheduleSave();
    }
    function copySelectedElement() { const selected = selectedElement(); if (!selected) return false; copiedElement = JSON.parse(JSON.stringify(selected)); pasteCount = 0; return true; }
    function pasteCopiedElement() { if (!editable || !copiedElement) return false; pasteCount += 1; const duplicate = core.duplicateElement(copiedElement, uid(), highestZ() + 1, 24 * pasteCount); elements.push(duplicate); selectedId = duplicate.id; render(); scheduleSave(); return true; }
    function isTextEntryTarget(target) { return target instanceof Element && Boolean(target.closest("input, textarea, select, [contenteditable]")); }
    function setZoom(value, clientX, clientY) { const rect = viewport.getBoundingClientRect(); view = core.zoomViewAt(view, value, clientX === undefined ? rect.left + rect.width / 2 : clientX, clientY === undefined ? rect.top + rect.height / 2 : clientY, rect); applyView(); }

    document.querySelectorAll("[data-add]").forEach(button => {
        if (!editable) button.disabled = true;
        button.addEventListener("click", () => add(button.dataset.add));
    });
    toolkitToggle.addEventListener("click", () => { const open = toolkitMenu.hidden; toolkitMenu.hidden = !open; toolkitToggle.setAttribute("aria-expanded", String(open)); });
    document.querySelectorAll(".toolkit-group-toggle").forEach(toggle => toggle.addEventListener("click", () => {
        const content = toggle.nextElementSibling; const shouldOpen = content.hidden;
        document.querySelectorAll(".toolkit-group-toggle").forEach(other => { other.setAttribute("aria-expanded", "false"); other.nextElementSibling.hidden = true; });
        if (shouldOpen) { toggle.setAttribute("aria-expanded", "true"); content.hidden = false; }
    }));
    connectorTool.addEventListener("click", () => connectorMode ? stopConnectorMode() : beginConnectorMode());
    deleteControl.addEventListener("click", () => { if (!selectedId) return; const deletedId = selectedId; elements = elements.filter(item => item.id !== deletedId && item.source_id !== deletedId && item.target_id !== deletedId); selectedId = null; render(); scheduleSave(); });
    layerUp.addEventListener("click", () => { if (!selectedId) return; elements = core.reorder(elements, selectedId, "front"); render(); scheduleSave(); });
    layerDown.addEventListener("click", () => { if (!selectedId) return; elements = core.reorder(elements, selectedId, "back"); render(); scheduleSave(); });
    colorControl.addEventListener("input", event => { const item = selectedElement(); if (!item) return; item.color = event.target.value; if (item.data && "accent" in item.data) item.data.accent = item.color; const node = world.querySelector(`[data-id="${item.id}"]`); if (node) node.style.setProperty("--element-color", item.color); scheduleSave(); });
    document.getElementById("board-image-upload").addEventListener("change", async event => {
        if (!event.target.files.length) return; setSaveState("saving", "Uploading image…"); const body = new FormData(); body.append("image", event.target.files[0]); body.append("usage", "board"); body.append("csrf_token", app.dataset.csrf);
        try { const response = await fetch(app.dataset.uploadUrl, {method: "POST", credentials: "same-origin", headers: {"X-Requested-With": "fetch", "X-CSRFToken": app.dataset.csrf, Accept: "application/json"}, body}); const payload = await response.json(); if (!response.ok) throw new Error(payload.error); add("image", {url: payload.url, content: event.target.files[0].name}); } catch (error) { setSaveState("error", error.message || "Upload failed."); }
        event.target.value = "";
    });
    document.getElementById("zoom-in").addEventListener("click", () => setZoom(view.zoom + 0.15)); document.getElementById("zoom-out").addEventListener("click", () => setZoom(view.zoom - 0.15)); document.getElementById("reset-view").addEventListener("click", () => { view = {zoom: 1, panX: 0, panY: 0}; applyView(); });
    retrySave.addEventListener("click", () => { if (status.dataset.state === "conflict") { savedGeneration = changeGeneration; window.location.reload(); return; } saveBlocked = false; flushSave(); });
    window.addEventListener("keydown", event => { if ((!event.ctrlKey && !event.metaKey) || event.altKey || isTextEntryTarget(event.target)) return; const key = event.key.toLowerCase(); if (key === "c" && copySelectedElement()) event.preventDefault(); else if (key === "v" && pasteCopiedElement()) event.preventDefault(); });
    window.addEventListener("copy", event => { if (isTextEntryTarget(event.target) || !copySelectedElement()) return; event.preventDefault(); if (event.clipboardData) event.clipboardData.setData("text/plain", "GridVault board object"); });
    window.addEventListener("paste", event => { if (isTextEntryTarget(event.target) || !pasteCopiedElement()) return; event.preventDefault(); });
    viewport.addEventListener("wheel", event => { event.preventDefault(); if (event.ctrlKey || event.metaKey) setZoom(view.zoom * Math.exp(-event.deltaY * 0.002), event.clientX, event.clientY); else { view.panX -= event.deltaX || (event.shiftKey ? event.deltaY : 0); view.panY -= event.shiftKey ? 0 : event.deltaY; applyView(); } }, {passive: false});
    viewport.addEventListener("pointerdown", beginPan); viewport.addEventListener("pointermove", updateGesture); viewport.addEventListener("pointerup", endGesture); viewport.addEventListener("pointercancel", endGesture);
    viewport.addEventListener("scroll", () => { if (viewport.scrollLeft || viewport.scrollTop) { viewport.scrollLeft = 0; viewport.scrollTop = 0; } });
    window.addEventListener("beforeunload", event => { if (editable && !saveBlocked && changeGeneration !== savedGeneration) { event.preventDefault(); event.returnValue = ""; } });

    render(); applyView();
})();
