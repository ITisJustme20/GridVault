const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const chat = fs.readFileSync(path.join(root, "gridvault", "static", "js", "chat.js"), "utf8");
const template = fs.readFileSync(path.join(root, "gridvault", "templates", "hub", "chat.html"), "utf8");

test("Direct and Group chats expose simple attachment and Files controls", () => {
    assert.match(template, />Attach File</);
    assert.match(template, />Files</);
    assert.match(template, /active\.type in \('direct', 'group'\)/);
    assert.match(template, /Files cannot be shared in GRID|attachment-enabled/);
});

test("pending files expose Ready, Uploading, Sent, Failed, and Remove states", () => {
    for (const state of ["Ready", "Uploading", "Sent", "Failed", "Remove"]) {
        assert.match(`${template}\n${chat}`, new RegExp(state));
    }
    assert.match(chat, /if \(selectedFile\)/);
    assert.match(chat, /if \(!selectedFile \|\| uploading\) return/);
});

test("attachment uploads use CSRF-protected HTTP and real-time message rendering", () => {
    assert.match(chat, /fetch\(workspace\.dataset\.uploadUrl/);
    assert.match(chat, /"X-CSRFToken": workspace\.dataset\.csrf/);
    assert.match(chat, /socket\.on\("receive_message", handleIncomingMessage\)/);
    assert.match(chat, /messages\.querySelector\(`\[data-message-id=/);
    assert.match(chat, /data\.attachment/);
});

test("file content is rendered with safe DOM text and private server URLs", () => {
    assert.match(chat, /filename\.textContent = attachment\.filename/);
    assert.match(chat, /actionLink\("Preview", attachment\.preview_url/);
    assert.match(chat, /actionLink\("Download", attachment\.download_url/);
    assert.doesNotMatch(chat, /innerHTML|insertAdjacentHTML|eval\(/);
});

test("drag and drop uses the same single-file validation path", () => {
    assert.match(chat, /addEventListener\("dragover"/);
    assert.match(chat, /addEventListener\("drop"/);
    assert.match(chat, /selectAttachment\(event\.dataTransfer\.files\[0\]\)/);
    assert.match(chat, /Disguised JavaScript files are blocked/);
});
