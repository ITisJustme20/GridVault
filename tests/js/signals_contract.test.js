const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const base = fs.readFileSync(path.join(root, "gridvault", "templates", "base.html"), "utf8");
const page = fs.readFileSync(path.join(root, "gridvault", "templates", "signals", "index.html"), "utf8");
const script = fs.readFileSync(path.join(root, "gridvault", "static", "js", "signals.js"), "utf8");
const style = fs.readFileSync(path.join(root, "gridvault", "static", "css", "style.css"), "utf8");
const service = fs.readFileSync(path.join(root, "gridvault", "signal_service.py"), "utf8");

test("Signal Queue navigation and page remain text based and actionable", () => {
    assert.match(base, />SIGNALS</);
    assert.match(base, /signal-nav-count/);
    for (const label of ["SIGNAL QUEUE", "DIRECT", "GROUP", "FILE TRANSFER", "GROUP ACCESS", "SYSTEM"]) {
        assert.match(`${page}${script}${service}`, new RegExp(label));
    }
    assert.match(page, /csrf_token/);
    assert.doesNotMatch(page, /<img|<svg|emoji|icon/i);
});

test("Signal count subscribes through the shared authenticated socket", () => {
    assert.match(script, /window\.gridVaultSocket\s*\|\|/);
    assert.match(script, /typeof window\.io === "function"/);
    assert.match(script, /window\.gridVaultSocket = socket/);
    assert.match(script, /socket\.emit\("signals_subscribe"\)/);
    assert.match(script, /signal_queue_updated/);
    assert.doesNotMatch(script, /innerHTML|new WebSocket/);
});

test("Signal Queue has a compact responsive layout", () => {
    assert.match(style, /\.signal-queue-page/);
    assert.match(style, /\.signal-item/);
    assert.match(style, /@media \(max-width: 600px\)[\s\S]*\.signal-queue-header/);
});
