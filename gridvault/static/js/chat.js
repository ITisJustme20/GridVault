const workspace = document.getElementById("hub-workspace");

if (workspace) {
    const socket = io({ transports: ["websocket"] });
    const currentCallsign = workspace.dataset.callsign;
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");
    const messages = document.getElementById("messages");
    const onlineUsers = document.getElementById("online-users");
    const onlineCount = document.getElementById("online-count");
    const typingIndicator = document.getElementById("typing-indicator");
    const newMessagesButton = document.getElementById("new-messages-button");
    const typingUsers = new Set();

    let typingTimer = null;
    let typingActive = false;

    function isNearBottom() {
        const distance = messages.scrollHeight - messages.scrollTop - messages.clientHeight;
        return distance < 120;
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
        return new Date(dateValue).toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit"
        });
    }

    function getLatestMessage() {
        const allMessages = messages.querySelectorAll(".message");
        return allMessages.length ? allMessages[allMessages.length - 1] : null;
    }

    function markLatestMessageRead() {
        if (document.hidden || !isNearBottom()) return;
        const latestMessage = getLatestMessage();
        if (!latestMessage) return;
        const messageId = Number(latestMessage.dataset.messageId);
        if (messageId) socket.emit("mark_read", { message_id: messageId });
    }

    function updateTypingIndicator() {
        const callsigns = Array.from(typingUsers);
        if (callsigns.length === 0) typingIndicator.textContent = "";
        else if (callsigns.length === 1) typingIndicator.textContent = `${callsigns[0]} is composing a transmission…`;
        else if (callsigns.length === 2) typingIndicator.textContent = `${callsigns[0]} and ${callsigns[1]} are composing…`;
        else typingIndicator.textContent = `${callsigns.length} operators are composing…`;
    }

    function stopTyping() {
        if (!typingActive) return;
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
        typingTimer = window.setTimeout(stopTyping, 1200);
        if (!hasText) stopTyping();
    });

    messageForm.addEventListener("submit", (event) => {
        event.preventDefault();
        const message = messageInput.value.trim();
        if (!message) return;
        socket.emit("send_message", { message });
        messageInput.value = "";
        window.clearTimeout(typingTimer);
        stopTyping();
        messageInput.focus();
    });

    socket.on("receive_message", (data) => {
        const shouldAutoScroll = isNearBottom() || data.callsign === currentCallsign;
        document.getElementById("chat-empty")?.remove();

        const messageElement = document.createElement("article");
        messageElement.className = `message${data.callsign === currentCallsign ? " message-own" : ""}`;
        messageElement.dataset.messageId = data.id;
        messageElement.dataset.callsign = data.callsign;

        const avatarElement = document.createElement("span");
        avatarElement.className = "message-avatar";
        avatarElement.textContent = data.callsign.slice(0, 2).toUpperCase();

        const bodyElement = document.createElement("div");
        bodyElement.className = "message-body";
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

        headingElement.append(callsignElement, timeElement);
        bodyElement.append(headingElement, textElement, receiptElement);
        messageElement.append(avatarElement, bodyElement);
        messages.appendChild(messageElement);

        typingUsers.delete(data.callsign);
        updateTypingIndicator();
        if (shouldAutoScroll) scrollToBottom(true);
        else newMessagesButton.hidden = false;
    });

    socket.on("online_users", (data) => {
        onlineUsers.replaceChildren();
        const users = Array.isArray(data.users) ? data.users : [];
        onlineCount.textContent = users.length;
        users.forEach((callsign) => {
            const listItem = document.createElement("li");
            const avatar = document.createElement("span");
            avatar.className = "online-avatar";
            avatar.textContent = callsign.slice(0, 2).toUpperCase();
            const copy = document.createElement("span");
            const name = document.createElement("strong");
            name.textContent = callsign;
            const status = document.createElement("small");
            status.textContent = "Online now";
            copy.append(name, status);
            const dot = document.createElement("span");
            dot.className = "online-dot";
            listItem.append(avatar, copy, dot);
            onlineUsers.appendChild(listItem);
        });
    });

    socket.on("user_typing", (data) => {
        if (data.callsign) typingUsers.add(data.callsign);
        updateTypingIndicator();
    });

    socket.on("user_stopped_typing", (data) => {
        typingUsers.delete(data.callsign);
        updateTypingIndicator();
    });

    socket.on("read_receipt_update", (data) => {
        const messageElement = messages.querySelector(`[data-message-id="${data.message_id}"]`);
        if (!messageElement) return;
        const receiptElement = messageElement.querySelector(".read-receipt");
        const receiptCallsigns = Array.isArray(data.callsigns)
            ? data.callsigns.filter((callsign) => callsign !== currentCallsign)
            : [];
        receiptElement.textContent = messageElement.dataset.callsign === currentCallsign && receiptCallsigns.length
            ? `Seen by ${receiptCallsigns.join(", ")}`
            : "";
    });

    socket.on("message_error", (data) => window.alert(data.error));
    socket.on("connect", () => scrollToBottom(false));
    socket.on("connect_error", (error) => console.error("GridVault connection failed:", error.message));

    messages.addEventListener("scroll", () => {
        if (isNearBottom()) {
            newMessagesButton.hidden = true;
            markLatestMessageRead();
        }
    });
    newMessagesButton.addEventListener("click", () => scrollToBottom(true));
    document.addEventListener("visibilitychange", () => {
        if (!document.hidden) markLatestMessageRead();
    });
    window.addEventListener("beforeunload", stopTyping);

    scrollToBottom(false);
    messageInput.focus();
}
