const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const board = fs.readFileSync(
    path.join(root, "gridvault", "static", "js", "design_board.js"),
    "utf8"
);
const boardCss = fs.readFileSync(
    path.join(root, "gridvault", "static", "css", "style.css"),
    "utf8"
);
const boardTemplate = fs.readFileSync(
    path.join(root, "gridvault", "templates", "design_lab", "board.html"),
    "utf8"
);
const designFormTemplate = fs.readFileSync(
    path.join(root, "gridvault", "templates", "design_lab", "form.html"),
    "utf8"
);
const chat = fs.readFileSync(
    path.join(root, "gridvault", "static", "js", "chat.js"),
    "utf8"
);

test("board uses one pointer event model for mouse, touchpad, and touch", () => {
    for (const event of ["pointerdown", "pointermove", "pointerup", "pointercancel"]) {
        assert.match(board, new RegExp(`addEventListener\\(\\\"${event}\\\"`));
    }
    assert.match(board, /setPointerCapture/);
    assert.match(board, /event\.pointerType === "mouse"/);
    assert.doesNotMatch(board, /addEventListener\("mousedown"/);
    assert.doesNotMatch(board, /addEventListener\("touchstart"/);
    assert.match(boardCss, /\.board-viewport[^}]*touch-action:\s*none/);
    assert.match(boardCss, /\.board-is-interacting[^}]*user-select:\s*none/);
});

test("zoomed board coordinates cannot drift into native scrolling", () => {
    assert.match(board, /viewport\.scrollLeft = 0/);
    assert.match(board, /viewport\.scrollTop = 0/);
    assert.match(board, /viewport\.addEventListener\("scroll"/);
    assert.match(boardCss, /\.board-viewport[^}]*overflow:\s*clip/);
    assert.match(board, /core\.moveGeometry\([\s\S]*view\.zoom/);
    assert.match(board, /core\.resizeGeometry\([\s\S]*view\.zoom/);
});

test("autosave exposes progress, serializes writes, and recovers from conflict", () => {
    for (const state of ["dirty", "saving", "saved", "error"]) {
        assert.match(board, new RegExp(`setSaveState\\(\\\"${state}\\\"`));
    }
    assert.match(board, /setSaveState\([\s\S]{0,80}"conflict"/);
    assert.match(board, /saveInFlight/);
    assert.match(board, /base_version:\s*boardVersion/);
    assert.match(board, /response\.status === 409/);
    assert.match(board, /retrySave\.textContent = state === "conflict" \? "Reload board"/);
    assert.match(board, /savedGeneration = changeGeneration;\s*window\.location\.reload\(\)/);
});

test("rendered board advertises persistence and read-only controls", () => {
    assert.match(boardTemplate, /data-board-version=/);
    assert.match(boardTemplate, /data-editable=/);
    assert.match(boardTemplate, /role="status"/);
    assert.match(boardTemplate, /Archived designs cannot be modified/);
    assert.match(boardTemplate, /design_board\.js', v='3\.0'/);
});

test("Hub allows Socket.IO transport fallback for forwarded proxies", () => {
    assert.match(chat, /const socket = io\(\);/);
    assert.doesNotMatch(chat, /transports\s*:/);
});

test("reference cards add directly and arrows expose endpoint handles", () => {
    assert.doesNotMatch(board, /prompt\("HTTPS reference URL/);
    assert.match(board, /add\(button\.dataset\.add\)/);
    assert.match(board, /className = "arrow-endpoint arrow-startpoint"/);
    assert.match(board, /className = "arrow-endpoint arrow-endpoint-finish"/);
    assert.match(board, /core\.moveArrowEndpoint/);
    assert.match(boardCss, /\.board-arrow-line[^}]*stroke:\s*currentColor/);
});

test("Create Design uses a wide heading column and responsive stack", () => {
    assert.match(designFormTemplate, /project-form design-form panel/);
    assert.match(
        boardCss,
        /\.design-form \.form-section[^}]*minmax\(190px, 240px\)/
    );
    assert.match(
        boardCss,
        /@media \(max-width: 820px\)[\s\S]*\.design-form \.form-section[^}]*grid-template-columns:\s*1fr/
    );
});

test("arrows snap by default and Alt preserves free-angle dragging", () => {
    assert.match(board, /core\.moveArrowEndpoint\([\s\S]*!event\.altKey/);
});

test("board objects copy and paste without intercepting text editing", () => {
    assert.match(board, /function copySelectedElement\(\)/);
    assert.match(board, /function pasteCopiedElement\(\)/);
    assert.match(board, /core\.duplicateElement/);
    assert.match(board, /window\.addEventListener\("keydown"/);
    assert.match(board, /window\.addEventListener\("copy"/);
    assert.match(board, /window\.addEventListener\("paste"/);
    assert.match(board, /key === "c"/);
    assert.match(board, /key === "v"/);
    assert.match(board, /input, textarea, select, \[contenteditable\]/);
});

test("movement renders transient alignment and equal-spacing guides", () => {
    assert.match(boardTemplate, /id="board-guides"/);
    assert.match(board, /function renderGuides\(guides\)/);
    assert.match(board, /core\.snapElementMove/);
    assert.match(board, /core\.snapArrowEndpoint/);
    assert.match(board, /event\.altKey[\s\S]*guides: \[\]/);
    assert.match(board, /guideLayer\.style\.transform = transform/);
    assert.match(board, /function endGesture[\s\S]*clearGuides\(\)/);
    assert.match(boardCss, /\.board-guide\.spacing\.horizontal/);
    assert.match(boardCss, /\.board-guide\.spacing\.vertical/);
});

test("Toolkit is text based, grouped, and keeps one accordion group open", () => {
    for (const label of [
        "Add Object", "Text Note", "Rectangle", "Arrow", "Connector", "Intel",
        "Toolkit", "General", "Engineering", "Software", "Markets", "Board Tools"
    ]) assert.match(boardTemplate, new RegExp(`>${label}<|>${label}\\s*<`));
    for (const type of ["heading", "zone", "code", "market", "minimap"]) {
        assert.match(boardTemplate, new RegExp(`data-add=\"${type}\"`));
    }
    assert.match(board, /document\.querySelectorAll\("\.toolkit-group-toggle"\)[\s\S]*nextElementSibling\.hidden = true/);
    assert.doesNotMatch(boardTemplate, /emoji|data-icon|tool-icon/i);
});

test("new objects share creation, clipboard, connector, and Mini Map behavior", () => {
    assert.match(board, /function add\(type, options = \{\}\)/);
    assert.match(board, /const item = \{id: uid\(\), type/);
    assert.match(board, /data: \{\.\.\.initialData/);
    assert.match(board, /core\.duplicateElement/);
    assert.match(board, /source_id: source\.id, target_id: item\.id/);
    assert.match(board, /core\.connectorGeometry\(source, target\)/);
    assert.match(board, /function miniMapVisual\(item\)/);
    assert.match(board, /beginMiniMapGesture/);
    assert.match(board, /function add\(type, options = \{\}\) \{\s*if \(!editable\) return null/);
});
