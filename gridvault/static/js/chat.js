(function () {
    "use strict";

    const workspace = document.getElementById("hub-workspace");
    if (!workspace) return;

    // Polling may upgrade to WebSocket, preserving HTTPS/WSS proxy compatibility.
    const socket = window.gridVaultSocket || io();
    window.gridVaultSocket = socket;
    const currentCallsign = workspace.dataset.callsign;
    const activeConversationId = Number(workspace.dataset.conversationId);
    const activeConversationType = workspace.dataset.conversationType;
    const attachmentEnabled = workspace.dataset.attachmentEnabled === "true";
    const openFilesInitially = workspace.dataset.openFiles === "true";
    const maximumUploadBytes = Number(workspace.dataset.maxUploadBytes || 0);
    const messageForm = document.getElementById("message-form");
    const messageInput = document.getElementById("message-input");
    const messages = document.getElementById("messages");
    const chatContainer = document.getElementById("chat-container");
    const typingIndicator = document.getElementById("typing-indicator");
    const errorState = document.getElementById("chat-error");
    const newMessagesButton = document.getElementById("new-messages-button");
    const directPresence = document.getElementById("direct-presence");
    const liveStatus = document.querySelector(".live-status");
    const attachmentInput = document.getElementById("attachment-input");
    const pendingAttachment = document.getElementById("pending-attachment");
    const pendingAttachmentName = document.getElementById("pending-attachment-name");
    const pendingAttachmentDetail = document.getElementById("pending-attachment-detail");
    const pendingAttachmentState = document.getElementById("pending-attachment-state");
    const removeAttachment = document.getElementById("remove-attachment");
    const filesToggle = document.getElementById("files-toggle");
    const filesClose = document.getElementById("files-close");
    const filesPanel = document.getElementById("conversation-files");
    const filesList = document.getElementById("conversation-files-list");
    const typingUsers = new Set();
    let typingTimer = null;
    let typingActive = false;
    let selectedFile = null;
    let uploading = false;
    let dragDepth = 0;

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

    function formatDate(dateValue) {
        return new Date(dateValue).toLocaleDateString([], {
            month: "short",
            day: "numeric",
            year: "numeric"
        });
    }

    function formatFileSize(byteSize) {
        if (byteSize < 1024) return `${byteSize} B`;
        if (byteSize < 1024 * 1024) return `${(byteSize / 1024).toFixed(1)} KB`;
        return `${(byteSize / (1024 * 1024)).toFixed(1)} MB`;
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

    function actionLink(label, url, preview = false) {
        const link = document.createElement("a");
        link.textContent = label;
        link.href = url;
        if (preview) {
            link.target = "_blank";
            link.rel = "noopener";
        }
        return link;
    }

    function attachmentElement(attachment) {
        const section = document.createElement("section");
        section.className = "message-attachment";
        section.dataset.attachmentId = attachment.id;
        const meta = document.createElement("div");
        meta.className = "message-attachment-meta";
        const filename = document.createElement("strong");
        filename.textContent = attachment.filename;
        const detail = document.createElement("span");
        detail.textContent = `${attachment.size} · ${attachment.category}`;
        meta.append(filename, detail);
        const actions = document.createElement("div");
        actions.className = "message-attachment-actions";
        if (attachment.preview_url) {
            actions.append(actionLink("Preview", attachment.preview_url, true));
        }
        actions.append(actionLink("Download", attachment.download_url));
        section.append(meta, actions);
        if (attachment.category === "Image" && attachment.preview_url) {
            const preview = actionLink("", attachment.preview_url, true);
            preview.className = "attachment-thumbnail";
            const image = document.createElement("img");
            image.src = attachment.preview_url;
            image.alt = `Preview of ${attachment.filename}`;
            image.loading = "lazy";
            preview.append(image);
            section.append(preview);
        }
        return section;
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
        const callsign = document.createElement("a");
        callsign.className = "message-callsign";
        callsign.href = `/operators/${encodeURIComponent(data.callsign)}`;
        callsign.textContent = data.callsign;
        const time = document.createElement("time");
        time.textContent = formatTime(data.created_at);
        const receipt = document.createElement("small");
        receipt.className = "read-receipt";
        receipt.textContent = own ? statusText : "";
        heading.append(callsign, time);
        body.append(heading);
        if (data.message) {
            const text = document.createElement("p");
            text.textContent = data.message;
            body.append(text);
        }
        if (data.attachment) body.append(attachmentElement(data.attachment));
        body.append(receipt);
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

    function appendFileListItem(attachment, prepend = true) {
        if (!filesList || filesList.querySelector(`[data-attachment-id="${attachment.id}"]`)) return;
        document.getElementById("conversation-files-empty")?.remove();
        const article = document.createElement("article");
        article.className = "conversation-file";
        article.dataset.attachmentId = attachment.id;
        const meta = document.createElement("div");
        const filename = document.createElement("strong");
        filename.textContent = attachment.filename;
        const detail = document.createElement("span");
        detail.textContent = `${attachment.uploader} · ${attachment.size} · ${formatDate(attachment.uploaded_at)}`;
        meta.append(filename, detail);
        const actions = document.createElement("div");
        if (attachment.preview_url) actions.append(actionLink("Preview", attachment.preview_url, true));
        actions.append(actionLink("Download", attachment.download_url));
        article.append(meta, actions);
        if (prepend) filesList.prepend(article);
        else filesList.append(article);
    }

    function handleIncomingMessage(data) {
        const conversationId = Number(data.conversation_id);
        if (conversationId !== activeConversationId) {
            if (data.callsign !== currentCallsign) incrementUnread(conversationId);
            return;
        }
        const existingById = messages.querySelector(`[data-message-id="${data.id}"]`);
        if (existingById) return;
        const shouldAutoScroll = isNearBottom() || data.callsign === currentCallsign;
        document.getElementById("chat-empty")?.remove();
        const pending = data.client_id ? pendingMessage(data.client_id) : null;
        const rendered = messageElement(
            data,
            data.callsign === currentCallsign ? receiptText(data.read_by) : ""
        );
        if (pending) pending.replaceWith(rendered);
        else messages.append(rendered);
        if (data.attachment) appendFileListItem(data.attachment);
        typingUsers.delete(data.callsign);
        updateTypingIndicator();
        if (shouldAutoScroll) scrollToBottom(true);
        else newMessagesButton.hidden = false;
    }

    function updatePendingAttachment(state) {
        if (pendingAttachmentState) pendingAttachmentState.textContent = state;
    }

    function clearAttachment(delay = 0) {
        window.setTimeout(() => {
            selectedFile = null;
            if (attachmentInput) attachmentInput.value = "";
            if (pendingAttachment) pendingAttachment.hidden = true;
            if (pendingAttachmentName) pendingAttachmentName.textContent = "";
            if (pendingAttachmentDetail) pendingAttachmentDetail.textContent = "";
            updatePendingAttachment("Ready");
        }, delay);
    }

    function allowedClientFile(file) {
        if (!file || !file.name) return "Choose a file with a valid filename.";
        const parts = file.name.toLowerCase().split(".");
        const extension = parts.pop();
        const allowed = new Set((attachmentInput?.accept || "").split(",").map(item => item.replace(".", "")));
        const dangerous = new Set(["exe", "msi", "bat", "cmd", "com", "scr", "ps1", "sh", "dll", "jar", "apk", "dmg", "iso"]);
        if (parts.some(part => dangerous.has(part)) || dangerous.has(extension)) {
            return "Executable and dangerous file types are blocked.";
        }
        if (parts.includes("js")) return "Disguised JavaScript files are blocked.";
        if (!allowed.has(extension)) return "This file type is not supported.";
        if (maximumUploadBytes && file.size > maximumUploadBytes) {
            return `The file is larger than the ${formatFileSize(maximumUploadBytes)} limit.`;
        }
        if (!file.size) return "The selected file is empty.";
        return "";
    }

    function selectAttachment(file) {
        if (!attachmentEnabled || uploading) return;
        const error = allowedClientFile(file);
        if (error) {
            clearAttachment();
            setError(error);
            return;
        }
        selectedFile = file;
        pendingAttachment.hidden = false;
        pendingAttachmentName.textContent = file.name;
        pendingAttachmentDetail.textContent = formatFileSize(file.size);
        updatePendingAttachment("Ready");
        setError("");
    }

    async function sendAttachment(message) {
        if (!selectedFile || uploading) return;
        uploading = true;
        const clientId = pendingId();
        updatePendingAttachment("Uploading");
        messageForm.querySelector("button[type='submit']").disabled = true;
        removeAttachment.disabled = true;
        const formData = new FormData();
        formData.append("file", selectedFile, selectedFile.name);
        formData.append("message", message);
        formData.append("client_id", clientId);
        try {
            const response = await fetch(workspace.dataset.uploadUrl, {
                method: "POST",
                credentials: "same-origin",
                headers: {
                    "X-CSRFToken": workspace.dataset.csrf,
                    "X-Requested-With": "fetch",
                    "Accept": "application/json"
                },
                body: formData
            });
            const contentType = response.headers.get("content-type") || "";
            const payload = contentType.includes("application/json")
                ? await response.json()
                : {ok: false, error: response.status === 413 ? "The file is too large." : "Your session may have expired. Refresh and try again."};
            if (!response.ok || !payload.ok) throw new Error(payload.error || "Upload failed.");
            handleIncomingMessage(payload.message);
            updatePendingAttachment("Sent");
            messageInput.value = "";
            window.clearTimeout(typingTimer);
            stopTyping();
            setError("");
            clearAttachment(700);
        } catch (error) {
            updatePendingAttachment("Failed");
            setError(error.message || "Upload failed. Try again.");
        } finally {
            uploading = false;
            messageForm.querySelector("button[type='submit']").disabled = false;
            removeAttachment.disabled = false;
        }
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
        if (selectedFile) {
            sendAttachment(message);
            return;
        }
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

    if (attachmentInput) attachmentInput.addEventListener("change", () => {
        selectAttachment(attachmentInput.files?.[0]);
    });
    if (removeAttachment) removeAttachment.addEventListener("click", () => {
        if (!uploading) clearAttachment();
    });

    if (attachmentEnabled) {
        chatContainer.addEventListener("dragenter", event => {
            if (!event.dataTransfer?.types.includes("Files")) return;
            event.preventDefault();
            dragDepth += 1;
            chatContainer.classList.add("file-dragover");
        });
        chatContainer.addEventListener("dragover", event => {
            if (!event.dataTransfer?.types.includes("Files")) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "copy";
        });
        chatContainer.addEventListener("dragleave", event => {
            if (!event.dataTransfer?.types.includes("Files")) return;
            dragDepth = Math.max(0, dragDepth - 1);
            if (!dragDepth) chatContainer.classList.remove("file-dragover");
        });
        chatContainer.addEventListener("drop", event => {
            if (!event.dataTransfer?.files.length) return;
            event.preventDefault();
            dragDepth = 0;
            chatContainer.classList.remove("file-dragover");
            selectAttachment(event.dataTransfer.files[0]);
        });
    }

    function setFilesPanel(open) {
        if (!filesPanel) return;
        filesPanel.hidden = !open;
        filesToggle?.setAttribute("aria-expanded", String(open));
        window.gridVaultPresence?.setSector(
            open ? "FILE VAULT" : activeConversationType === "group"
                ? "GROUPS"
                : activeConversationType.toUpperCase()
        );
    }
    filesToggle?.addEventListener("click", () => setFilesPanel(filesPanel.hidden));
    filesClose?.addEventListener("click", () => setFilesPanel(false));
    if (openFilesInitially) setFilesPanel(true);

    socket.on("receive_message", handleIncomingMessage);

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
