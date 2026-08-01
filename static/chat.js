const socket = io({
    transports: ["websocket"]
});

const currentCallsign = window.GRIDVAULT_CALLSIGN;

const messageForm = document.getElementById("message-form");
const messageInput = document.getElementById("message-input");
const messages = document.getElementById("messages");

const onlineUsers = document.getElementById("online-users");
const onlineCount = document.getElementById("online-count");

const typingIndicator = document.getElementById("typing-indicator");
const newMessagesButton = document.getElementById(
    "new-messages-button"
);

const typingUsers = new Set();

let typingTimer = null;
let typingActive = false;


function isNearBottom() {
    const distanceFromBottom =
        messages.scrollHeight -
        messages.scrollTop -
        messages.clientHeight;

    return distanceFromBottom < 120;
}


function scrollToBottom(smooth = false) {
    messages.scrollTo({
        top: messages.scrollHeight,
        behavior: smooth ? "smooth" : "auto"
    });

    newMessagesButton.hidden = true;

    window.setTimeout(markLatestMessageRead, 150);
}


function formatTime(dateValue) {
    const date = new Date(dateValue);

    return date.toLocaleTimeString([], {
        hour: "numeric",
        minute: "2-digit"
    });
}


function getLatestMessage() {
    const allMessages = messages.querySelectorAll(".message");

    if (!allMessages.length) {
        return null;
    }

    return allMessages[allMessages.length - 1];
}


function markLatestMessageRead() {
    if (document.hidden || !isNearBottom()) {
        return;
    }

    const latestMessage = getLatestMessage();

    if (!latestMessage) {
        return;
    }

    const messageId = Number(latestMessage.dataset.messageId);

    if (!messageId) {
        return;
    }

    socket.emit("mark_read", {
        message_id: messageId
    });
}


function updateTypingIndicator() {
    const callsigns = Array.from(typingUsers);

    if (callsigns.length === 0) {
        typingIndicator.textContent = "";
        return;
    }

    if (callsigns.length === 1) {
        typingIndicator.textContent =
            `${callsigns[0]} is typing...`;

        return;
    }

    if (callsigns.length === 2) {
        typingIndicator.textContent =
            `${callsigns[0]} and ${callsigns[1]} are typing...`;

        return;
    }

    typingIndicator.textContent =
        `${callsigns.length} users are typing...`;
}


function stopTyping() {
    if (!typingActive) {
        return;
    }

    typingActive = false;
    socket.emit("stop_typing");
}


messageInput.addEventListener("input", () => {
    const hasText = messageInput.value.trim().length > 0;

    if (hasText && !typingActive) {
        typingActive = true;
        socket.emit("typing");
    }

    window.clearTimeout(typingTimer);

    typingTimer = window.setTimeout(() => {
        stopTyping();
    }, 1200);

    if (!hasText) {
        stopTyping();
    }
});


messageForm.addEventListener("submit", (event) => {
    event.preventDefault();

    const message = messageInput.value.trim();

    if (!message) {
        return;
    }

    socket.emit("send_message", {
        message: message
    });

    messageInput.value = "";

    window.clearTimeout(typingTimer);
    stopTyping();

    messageInput.focus();
});


socket.on("receive_message", (data) => {
    const shouldAutoScroll =
        isNearBottom() || data.callsign === currentCallsign;

    const messageElement = document.createElement("article");

    messageElement.className = "message";
    messageElement.dataset.messageId = data.id;
    messageElement.dataset.callsign = data.callsign;

    const headingElement = document.createElement("div");
    headingElement.className = "message-heading";

    const callsignElement = document.createElement("strong");
    callsignElement.textContent = data.callsign;

    const timeElement = document.createElement("time");
    timeElement.textContent = formatTime(data.created_at);

    const textElement = document.createElement("p");
    textElement.textContent = data.message;

    const receiptElement = document.createElement("small");
    receiptElement.className = "read-receipt";

    headingElement.appendChild(callsignElement);
    headingElement.appendChild(timeElement);

    messageElement.appendChild(headingElement);
    messageElement.appendChild(textElement);
    messageElement.appendChild(receiptElement);

    messages.appendChild(messageElement);

    typingUsers.delete(data.callsign);
    updateTypingIndicator();

    if (shouldAutoScroll) {
        scrollToBottom(true);
    } else {
        newMessagesButton.hidden = false;
    }
});


socket.on("online_users", (data) => {
    onlineUsers.replaceChildren();

    const users = Array.isArray(data.users)
        ? data.users
        : [];

    onlineCount.textContent = users.length;

    users.forEach((callsign) => {
        const listItem = document.createElement("li");

        const statusDot = document.createElement("span");
        statusDot.className = "online-dot";

        const callsignText = document.createElement("span");
        callsignText.textContent = callsign;

        listItem.appendChild(statusDot);
        listItem.appendChild(callsignText);

        onlineUsers.appendChild(listItem);
    });
});


socket.on("user_typing", (data) => {
    if (!data.callsign) {
        return;
    }

    typingUsers.add(data.callsign);
    updateTypingIndicator();
});


socket.on("user_stopped_typing", (data) => {
    typingUsers.delete(data.callsign);
    updateTypingIndicator();
});


socket.on("read_receipt_update", (data) => {
    const messageElement = messages.querySelector(
        `[data-message-id="${data.message_id}"]`
    );

    if (!messageElement) {
        return;
    }

    const receiptElement = messageElement.querySelector(
        ".read-receipt"
    );

    const receiptCallsigns = Array.isArray(data.callsigns)
        ? data.callsigns.filter(
            (callsign) => callsign !== currentCallsign
        )
        : [];

    if (messageElement.dataset.callsign !== currentCallsign) {
        receiptElement.textContent = "";
        return;
    }

    if (receiptCallsigns.length === 0) {
        receiptElement.textContent = "";
        return;
    }

    receiptElement.textContent =
        `Seen by ${receiptCallsigns.join(", ")}`;
});


socket.on("message_error", (data) => {
    alert(data.error);
});


socket.on("connect", () => {
    console.log("Connected to GridVault.");

    scrollToBottom(false);
});


socket.on("connect_error", (error) => {
    console.error(
        "GridVault connection failed:",
        error.message
    );
});


messages.addEventListener("scroll", () => {
    if (isNearBottom()) {
        newMessagesButton.hidden = true;
        markLatestMessageRead();
    }
});


newMessagesButton.addEventListener("click", () => {
    scrollToBottom(true);
});


document.addEventListener("visibilitychange", () => {
    if (!document.hidden) {
        markLatestMessageRead();
    }
});


window.addEventListener("beforeunload", () => {
    stopTyping();
});


scrollToBottom(false);
messageInput.focus();