const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const root = path.resolve(__dirname, "..", "..");
const chat = fs.readFileSync(
    path.join(root, "gridvault", "static", "js", "chat.js"),
    "utf8"
);
const template = fs.readFileSync(
    path.join(root, "gridvault", "templates", "hub", "chat.html"),
    "utf8"
);

test("chat navigation exposes only Grid, Direct, and Groups", () => {
    for (const label of ["GRID", "DIRECT", "GROUPS", "New Chat"]) {
        assert.match(template, new RegExp(`>${label}<`));
    }
    assert.doesNotMatch(template, /channel|thread|reaction|server list|emoji/i);
});

test("socket actions always carry the active conversation identifier", () => {
    for (const event of ["send_message", "typing", "stop_typing", "mark_read"] ) {
        assert.match(
            chat,
            new RegExp(`socket\\.emit\\(\"${event}\"[\\s\\S]{0,220}conversation_id:\\s*activeConversationId`)
        );
    }
    assert.match(chat, /subscribe_conversation/);
});

test("direct messages expose sending, delivered, and read states", () => {
    assert.match(chat, /}, "Sending"\)\)/);
    assert.match(chat, /textContent = "Delivered"/);
    assert.match(chat, /activeConversationType === "direct"[\s\S]*\? "Read"/);
});

test("background messages update unread counts without replacing active history", () => {
    assert.match(chat, /conversationId !== activeConversationId/);
    assert.match(chat, /incrementUnread\(conversationId\)/);
    assert.match(chat, /clearActiveUnread\(\)/);
});

test("new chat search selects only known callsigns", () => {
    assert.match(chat, /const operators = JSON\.parse/);
    assert.match(chat, /operators\.find/);
    assert.match(chat, /selectedCallsigns\.value = selected\.join\(","\)/);
    assert.match(chat, /Select at least one valid callsign/);
});
