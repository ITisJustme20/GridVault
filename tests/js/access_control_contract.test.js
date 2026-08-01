const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const assert = require("node:assert/strict");

const root = path.resolve(__dirname, "..", "..");
const script = fs.readFileSync(path.join(root, "gridvault", "static", "js", "access_control.js"), "utf8");
const template = fs.readFileSync(path.join(root, "gridvault", "templates", "access_control", "index.html"), "utf8");

test("Access Control copies the one-time code without putting it in a URL", () => {
    assert.match(script, /navigator\.clipboard\.writeText/);
    assert.match(template, /data-copy-target="new-invite-code"/);
    assert.doesNotMatch(template, /new_invite_code.*url_for|url_for.*new_invite_code/);
});

test("Access Control actions remain CSRF-protected text controls", () => {
    assert.match(template, /name="csrf_token"/);
    assert.match(template, />Generate one-time code</);
    assert.match(template, />Revoke</);
    assert.doesNotMatch(template, /<svg|emoji|icon-/i);
});
