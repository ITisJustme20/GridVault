const socket = io({
    transports: ["websocket"]
});

const messageForm = document.getElementById("message-form");
const messageInput = document.getElementById("message-input");
const messages = document.getElementById("messages");

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
    messageInput.focus();
});

socket.on("receive_message", (data) => {
    const messageElement = document.createElement("article");
    messageElement.className = "message";

    const usernameElement = document.createElement("strong");
    usernameElement.textContent = data.username;

    const textElement = document.createElement("p");
    textElement.textContent = data.message;

    messageElement.appendChild(usernameElement);
    messageElement.appendChild(textElement);

    messages.appendChild(messageElement);
    messages.scrollTop = messages.scrollHeight;
});

socket.on("message_error", (data) => {
    alert(data.error);
});

socket.on("connect", () => {
    console.log("Connected to GridVault.");
});

socket.on("connect_error", (error) => {
    console.error("GridVault connection failed:", error.message);
});

messages.scrollTop = messages.scrollHeight;
messageInput.focus();