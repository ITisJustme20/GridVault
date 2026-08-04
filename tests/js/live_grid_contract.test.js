const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const template = fs.readFileSync(path.join(root, "gridvault", "templates", "live_grid", "index.html"), "utf8");
const liveGrid = fs.readFileSync(path.join(root, "gridvault", "static", "js", "live_grid.js"), "utf8");
const presence = fs.readFileSync(path.join(root, "gridvault", "static", "js", "live_presence.js"), "utf8");
const css = fs.readFileSync(path.join(root, "gridvault", "static", "css", "style.css"), "utf8");
const hub = fs.readFileSync(path.join(root, "gridvault", "blueprints", "hub.py"), "utf8");
const designLab = fs.readFileSync(path.join(root, "gridvault", "blueprints", "design_lab.py"), "utf8");
const liveGridRoute = fs.readFileSync(path.join(root, "gridvault", "blueprints", "live_grid.py"), "utf8");

test("Live Grid uses text sectors and existing destinations", () => {
    for (const label of ["GRID", "DIRECT", "GROUPS", "VC BOARD", "FILE VAULT", "ACCESS"]) {
        assert.match(`${template}\n${liveGridRoute}`, new RegExp(label));
    }
    assert.match(template, /live_grid\.update_presence_visibility/);
    assert.match(template, /name="csrf_token"/);
    assert.doesNotMatch(template, /<img|emoji|icon-|canvas|webgl/i);
});

test("presence uses one shared socket and only broad validated sectors", () => {
    assert.match(presence, /window\.gridVaultSocket \|\| window\.io\(\)/);
    assert.match(presence, /allowedSectors\.has\(nextSector\)/);
    assert.match(presence, /presence_sector/);
    assert.doesNotMatch(presence, /callsign|user_id|conversation_id|filename/);
});

test("Live Grid rendering uses safe text and abstract pulse contracts", () => {
    assert.match(liveGrid, /textContent = item\.callsign/);
    assert.match(liveGrid, /textContent = item\.sector/);
    assert.match(liveGrid, /allowedPulseTypes\.has\(item\.type\)/);
    assert.doesNotMatch(liveGrid, /innerHTML|insertAdjacentHTML|eval\(/);
    assert.match(hub, /record_grid_activity\("FILE TRANSFER", "FILE VAULT"\)/);
    assert.match(designLab, /record_grid_activity\("BOARD UPDATE", "VC BOARD"\)/);
});

test("Live Grid has mobile and reduced-motion fallbacks", () => {
    assert.match(css, /@media \(max-width: 600px\)[\s\S]*\.live-grid-sectors/);
    assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none !important/);
});
