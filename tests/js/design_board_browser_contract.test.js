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
    assert.match(boardTemplate, /design_board\.js', v='2\.3'/);
});

test("Hub allows Socket.IO transport fallback for forwarded proxies", () => {
    assert.match(chat, /const socket = io\(\);/);
    assert.doesNotMatch(chat, /transports\s*:/);
});
