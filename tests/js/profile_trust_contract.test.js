const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..", "..");
const chatScript = fs.readFileSync(path.join(root, "gridvault", "static", "js", "chat.js"), "utf8");
const chatTemplate = fs.readFileSync(path.join(root, "gridvault", "templates", "hub", "chat.html"), "utf8");
const profileTemplate = fs.readFileSync(path.join(root, "gridvault", "templates", "profiles", "view.html"), "utf8");

test("chat callsigns link to compact operator profiles", () => {
    assert.match(chatScript, /\/operators\/\$\{encodeURIComponent\(data\.callsign\)\}/);
    assert.match(chatTemplate, /profiles\.view_profile/);
    assert.match(profileTemplate, />Shared Groups</);
});

test("profile trust controls are text based and CSRF protected", () => {
    assert.match(profileTemplate, />Block</);
    assert.match(profileTemplate, />Unblock</);
    assert.match(profileTemplate, />Report</);
    assert.match(profileTemplate, /name="csrf_token"/);
    assert.doesNotMatch(profileTemplate, /<img|<svg|emoji|icon-/i);
});
