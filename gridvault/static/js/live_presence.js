(function () {
    "use strict";

    const sector = document.body.dataset.gridSector;
    if (!sector || typeof window.io !== "function") return;

    const allowedSectors = new Set([
        "GRID", "DIRECT", "GROUPS", "VC BOARD", "FILE VAULT", "ACCESS", "ACTIVE"
    ]);
    const socket = window.gridVaultSocket || window.io();
    window.gridVaultSocket = socket;

    function setSector(nextSector) {
        if (!allowedSectors.has(nextSector)) return false;
        socket.emit("presence_sector", {sector: nextSector});
        return true;
    }

    window.gridVaultPresence = {setSector};
    if (socket.connected) setSector(sector);
    socket.on("connect", () => setSector(sector));
}());
