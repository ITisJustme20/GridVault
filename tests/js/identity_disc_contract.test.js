const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const renderer = fs.readFileSync(path.join(root, "gridvault", "static", "js", "identity_disc.js"), "utf8");
const profile = fs.readFileSync(path.join(root, "gridvault", "templates", "profiles", "view.html"), "utf8");
const liveGrid = fs.readFileSync(path.join(root, "gridvault", "static", "js", "live_grid.js"), "utf8");
const liveGridTemplate = fs.readFileSync(path.join(root, "gridvault", "templates", "live_grid", "index.html"), "utf8");
const css = fs.readFileSync(path.join(root, "gridvault", "static", "css", "style.css"), "utf8");

test("Identity Disc renderer uses bounded SVG DOM construction", () => {
    assert.match(renderer, /createElementNS/);
    assert.match(renderer, /boundedNumber/);
    assert.match(renderer, /replaceChildren/);
    assert.doesNotMatch(renderer, /innerHTML|insertAdjacentHTML|eval\(|canvas|webgl/i);
    assert.doesNotMatch(renderer, /password|invitation|session|auth_version|user_id|secret/i);
});

test("operator profile labels the disc as an identity reference", () => {
    assert.match(profile, />IDENTITY DISC</);
    assert.match(profile, />DISC CODE</);
    assert.match(profile, />IDENTITY REFERENCE ONLY</);
    assert.match(profile, /data-identity-disc/);
    assert.doesNotMatch(profile, /avatar|profile picture|badge|rarity|collectible|verification code/i);
});

test("Live Grid uses the shared compact Identity Disc renderer", () => {
    assert.match(liveGridTemplate, /js\/identity_disc\.js/);
    assert.match(liveGrid, /GridVaultIdentityDisc\?\.render\(disc, item\.disc\)/);
    assert.match(liveGrid, /identity-disc-compact/);
    assert.doesNotMatch(liveGrid, /innerHTML|insertAdjacentHTML/);
});

test("Identity Disc layouts remain compact, responsive, and motion safe", () => {
    assert.match(css, /\.identity-disc-profile/);
    assert.match(css, /\.identity-disc-compact/);
    assert.match(css, /@media \(max-width: 600px\)[\s\S]*\.operator-identity-panel/);
    assert.match(css, /@media \(prefers-reduced-motion: reduce\)[\s\S]*animation: none !important/);
    assert.doesNotMatch(css, /identity-disc[^\n{]*\{[^}]*animation:/i);
});
