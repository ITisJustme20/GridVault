(function () {
    "use strict";

    const countNode = document.getElementById("signal-nav-count");
    const queuePage = document.getElementById("signal-queue");
    const socket = window.gridVaultSocket ||
        (typeof window.io === "function" ? window.io() : null);
    if (!countNode || !socket) return;
    window.gridVaultSocket = socket;

    function updateCount(value) {
        const count = Number.isInteger(Number(value))
            ? Math.max(0, Math.min(999, Number(value)))
            : 0;
        countNode.textContent = String(count);
        countNode.hidden = count === 0;
        countNode.setAttribute("aria-label", `${count} active signals`);
    }

    function subscribe() {
        socket.emit("signals_subscribe");
    }

    socket.on("signal_count", data => updateCount(data?.count));
    socket.on("signal_queue_updated", data => {
        updateCount(data?.count);
        if (queuePage && !document.hidden) window.location.reload();
    });
    if (socket.connected) subscribe();
    socket.on("connect", subscribe);
}());
