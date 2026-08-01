(function () {
    "use strict";

    const workspace = document.getElementById("hub-workspace");
    if (!workspace) return;

    // Polling may upgrade to WebSocket, which keeps HTTPS/WSS proxy deployments
    // compatible without forcing a transport that a forwarded URL may block.
    const socket = io();
    const currentCallsign = workspace.dataset.callsign;
    const activeConversationId = Number(workspace.dataset.conversationId);
    const activeConversationType = workspace.dataset.conversationType;
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");
    const messages = document.getElementById("messages");
    const typingIndicator = document.getElementById("typing-indicator");
    const errorState = document.getElementById("chat-error");
    const newMessagesButton = document.getElementById("new-messages-button");
    const directPresence = document.getElementById("direct-presence");
    const liveStatus = document.querySelector(".live-status");
    const typingUsers = new Set();
    let typingTimer = null;
    let typingActive = false;

    function isNearBottom() {
        return messages.scrollHeight - messages.scrollTop - messages.clientHeight < 120;
    }

    function scrollToBottom(smooth = false) {
        messages.scrollTo({
            top: messages.scrollHeight,
            behavior: smooth ? "smooth" : "auto"
        });
        newMessagesButton.hidden = true;
        window.setTimeout(markLatestMessageRead, 120);
    }

    function formatTime(dateValue) {
        return new Date(dateValue).toLocaleTimeString([], {
            hour: "numeric",
            minute: "2-digit"
        });
    }

    function latestMessage() {
        const allMessages = messages.querySelectorAll(".message[data-message-id]");
        return allMessages.length ? allMessages[allMessages.length - 1] : null;
    }

    function activeUnreadBadge() {
        return document.querySelector(
            `[data-conversation-link="${activeConversationId}"] .unread-count`
        );
    }

    function clearActiveUnread() {
        activeUnreadBadge()?.remove();
    }

    function markLatestMessageRead() {
        if (document.hidden || !isNearBottom()) return;
        const latest = latestMessage();
        if (!latest) return;
        const messageId = Number(latest.dataset.messageId);
        if (!messageId) return;
        socket.emit("mark_read", {
            conversation_id: activeConversationId,
            message_id: messageId
        });
        clearActiveUnread();
    }

    function incrementUnread(conversationId) {
        const link = document.querySelector(
            `[data-conversation-link="${conversationId}"]`
        );
        if (!link) return;
        let badge = link.querySelector(".unread-count");
        if (!badge) {
            badge = document.createElement("strong");
            badge.className = "unread-count";
            badge.textContent = "0";
            link.append(badge);
        }
        badge.textContent = String(Number(badge.textContent || 0) + 1);
    }

    function setError(message) {
        errorState.textContent = message || "";
    }

    function updateTypingIndicator() {
        const callsigns = Array.from(typingUsers);
        if (!callsigns.length) typingIndicator.textContent = "";
        else if (callsigns.length === 1) typingIndicator.textContent = `${callsigns[0]} is typing…`;
        else typingIndicator.textContent = `${callsigns.join(", ")} are typing…`;
    }

    function stopTyping() {
        if (!typingActive) return;
        typingActive = false;
        socket.emit("stop_typing", {conversation_id: activeConversationId});
    }

    function pendingId() {
        if (globalThis.crypto && typeof globalThis.crypto.randomUUID === "function") {
            return `pending_${globalThis.crypto.randomUUID().replaceAll("-", "")}`;
        }
        return `pending_${Date.now()}_${Math.random().toString(36).slice(2)}`;
    }

    function messageElement(data, statusText = "") {
        const own = data.callsign === currentCallsign;
        const article = document.createElement("article");
        article.className = `message${own ? " message-own" : ""}${data.pending ? " message-pending" : ""}`;
        if (data.id) article.dataset.messageId = data.id;
        if (data.client_id) article.dataset.clientId = data.client_id;
        article.dataset.callsign = data.callsign;

        const avatar = document.createElement("span");
        avatar.className = "message-avatar";
        avatar.textContent = data.callsign.slice(0, 2).toUpperCase();
        const body = document.createElement("div");
        body.className = "message-body";
        const heading = document.createElement("div");
        heading.className = "message-heading";
        const callsign = document.createElement("strong");
        callsign.textContent = data.callsign;
        const time = document.createElement("time");
        time.textContent = formatTime(data.created_at);
        const text = document.createElement("p");
        text.textContent = data.message;
        const receipt = document.createElement("small");
        receipt.className = "read-receipt";
        receipt.textContent = own ? statusText : "";
        heading.append(callsign, time);
        body.append(heading, text, receipt);
        article.append(avatar, body);
        return article;
    }

    function pendingMessage(clientId) {
        return Array.from(messages.querySelectorAll(".message[data-client-id]")).find(
            element => element.dataset.clientId === clientId
        );
    }

    function receiptText(callsigns) {
        const readers = Array.isArray(callsigns)
            ? callsigns.filter(callsign => callsign !== currentCallsign)
            : [];
        if (!readers.length) return "Delivered";
        return activeConversationType === "direct"
            ? "Read"
            : `Read by ${readers.join(", ")}`;
    }

    messageInput.addEventListener("input", () => {
        const hasText = messageInput.value.trim().length > 0;
        if (hasText && !typingActive) {
            typingActive = true;
            socket.emit("typing", {conversation_id: activeConversationId});
        }
        window.clearTimeout(typingTimer);
        typingTimer = window.setTimeout(stopTyping, 1200);
        if (!hasText) stopTyping();
    });

    messageForm.addEventListener("submit", event => {
        event.preventDefault();
        const message = messageInput.value.trim();
        if (!message) return;
        const clientId = pendingId();
        document.getElementById("chat-empty")?.remove();
        messages.append(messageElement({
            callsign: currentCallsign,
            message,
            created_at: new Date().toISOString(),
            client_id: clientId,
            pending: true
        }, "Sending"));
        scrollToBottom(false);
        socket.emit("send_message", {
            conversation_id: activeConversationId,
            message,
            client_id: clientId
        });
        messageInput.value = "";
        window.clearTimeout(typingTimer);
        stopTyping();
        setError("");
        messageInput.focus();
    });

    socket.on("receive_message", data => {
        const conversationId = Number(data.conversation_id);
        if (conversationId !== activeConversationId) {
            if (data.callsign !== currentCallsign) incrementUnread(conversationId);
            return;
        }
        const shouldAutoScroll = isNearBottom() || data.callsign === currentCallsign;
        document.getElementById("chat-empty")?.remove();
        const existing = data.client_id ? pendingMessage(data.client_id) : null;
        if (existing) {
            existing.dataset.messageId = data.id;
            existing.classList.remove("message-pending");
            existing.querySelector("time").textContent = formatTime(data.created_at);
            existing.querySelector(".read-receipt").textContent = receiptText(data.read_by);
        } else if (!messages.querySelector(`[data-message-id="${data.id}"]`)) {
            messages.append(messageElement(
                data,
                data.callsign === currentCallsign ? receiptText(data.read_by) : ""
            ));
        }
        typingUsers.delete(data.callsign);
        updateTypingIndicator();
        if (shouldAutoScroll) scrollToBottom(true);
        else newMessagesButton.hidden = false;
    });

    socket.on("message_ack", data => {
        if (Number(data.conversation_id) !== activeConversationId) return;
        const pending = pendingMessage(data.client_id);
        if (!pending) return;
        pending.dataset.messageId = data.message_id;
        pending.classList.remove("message-pending");
        pending.querySelector(".read-receipt").textContent = "Delivered";
    });

    socket.on("user_typing", data => {
        if (Number(data.conversation_id) !== activeConversationId) return;
        if (data.callsign) typingUsers.add(data.callsign);
        updateTypingIndicator();
    });
    socket.on("user_stopped_typing", data => {
        if (Number(data.conversation_id) !== activeConversationId) return;
        typingUsers.delete(data.callsign);
        updateTypingIndicator();
    });

    socket.on("read_receipt_update", data => {
        if (Number(data.conversation_id) !== activeConversationId) return;
        const message = messages.querySelector(`[data-message-id="${data.message_id}"]`);
        if (!message || message.dataset.callsign !== currentCallsign) return;
        message.querySelector(".read-receipt").textContent = receiptText(data.callsigns);
    });

    socket.on("online_users", data => {
        if (!directPresence) return;
        const online = Array.isArray(data.users) && data.users.some(
            callsign => callsign.toLowerCase() === directPresence.dataset.peer.toLowerCase()
        );
        directPresence.textContent = `${directPresence.dataset.peer} · ${online ? "Online" : "Offline"}`;
    });
    socket.on("conversation_error", data => setError(data.error));
    socket.on("message_error", data => {
        setError(data.error);
        const pending = messages.querySelector(".message-pending:last-of-type .read-receipt");
        if (pending) pending.textContent = "Not sent";
    });
    socket.on("conversation_list_changed", () => window.location.reload());
    socket.on("connect", () => {
        liveStatus.textContent = "Live";
        socket.emit("subscribe_conversation", {conversation_id: activeConversationId});
        scrollToBottom(false);
    });
    socket.on("disconnect", () => { liveStatus.textContent = "Reconnecting"; });
    socket.on("connect_error", error => {
        liveStatus.textContent = "Offline";
        setError(`Connection unavailable: ${error.message}`);
    });

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

    const newChatToggle = document.getElementById("new-chat-toggle");
    const newChatPanel = document.getElementById("new-chat-panel");
    const participantSearch = document.getElementById("participant-search");
    const participantSuggestions = document.getElementById("participant-suggestions");
    const participantSelection = document.getElementById("participant-selection");
    const selectedCallsigns = document.getElementById("selected-callsigns");
    const operators = JSON.parse(
        document.getElementById("chat-operator-data").textContent || "[]"
    );
    const selected = [];

    function renderParticipantSelection() {
        selectedCallsigns.value = selected.join(",");
        participantSelection.replaceChildren(...selected.map(callsign => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = `${callsign} Remove`;
            button.addEventListener("click", () => {
                selected.splice(selected.indexOf(callsign), 1);
                renderParticipantSelection();
                renderSuggestions();
            });
            return button;
        }));
    }

    function addParticipant(callsign) {
        const valid = operators.find(
            operator => operator.toLowerCase() === callsign.trim().toLowerCase()
        );
        if (!valid || selected.includes(valid)) return false;
        selected.push(valid);
        participantSearch.value = "";
        renderParticipantSelection();
        renderSuggestions();
        return true;
    }

    function renderSuggestions() {
        const query = participantSearch.value.trim().toLowerCase();
        const matches = operators.filter(operator => (
            !selected.includes(operator)
            && (!query || operator.toLowerCase().includes(query))
        )).slice(0, 6);
        participantSuggestions.replaceChildren(...matches.map(callsign => {
            const button = document.createElement("button");
            button.type = "button";
            button.textContent = callsign;
            button.addEventListener("click", () => addParticipant(callsign));
            return button;
        }));
    }

    newChatToggle.addEventListener("click", () => {
        const open = newChatPanel.hidden;
        newChatPanel.hidden = !open;
        newChatToggle.setAttribute("aria-expanded", String(open));
        if (open) {
            renderSuggestions();
            participantSearch.focus();
        }
    });
    participantSearch.addEventListener("input", renderSuggestions);
    participantSearch.addEventListener("keydown", event => {
        if (event.key === "Enter" && addParticipant(participantSearch.value)) {
            event.preventDefault();
        }
    });
    newChatPanel.addEventListener("submit", event => {
        if (!selected.length && !addParticipant(participantSearch.value)) {
            event.preventDefault();
            setError("Select at least one valid callsign.");
        }
    });

    clearActiveUnread();
    scrollToBottom(false);
})();
