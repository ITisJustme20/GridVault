(function () {
    "use strict";

    const app = document.getElementById("live-grid-app");
    if (!app || !window.gridVaultSocket) return;

    const socket = window.gridVaultSocket;
    const operators = document.getElementById("live-grid-operators");
    const operatorCount = document.getElementById("live-grid-operator-count");
    const pulses = document.getElementById("live-grid-pulses");
    const knownPulseIds = new Set();
    const allowedSectors = new Set([
        "GRID", "DIRECT", "GROUPS", "VC BOARD", "FILE VAULT", "ACCESS", "ACTIVE"
    ]);
    const allowedPulseTypes = new Set([
        "TRANSMISSION", "FILE TRANSFER", "BOARD UPDATE", "OPERATOR ONLINE", "OPERATOR OFFLINE"
    ]);

    function profileUrl(callsign) {
        return app.dataset.profileBase.replace("__CALLSIGN__", encodeURIComponent(callsign));
    }

    function renderOperators(items) {
        operators.replaceChildren();
        const safeItems = Array.isArray(items) ? items.filter(item => (
            item && typeof item.callsign === "string" && allowedSectors.has(item.sector)
        )) : [];
        operatorCount.textContent = String(safeItems.length);
        if (!safeItems.length) {
            const empty = document.createElement("p");
            empty.className = "live-grid-empty";
            empty.textContent = "No operators are online.";
            operators.append(empty);
            return;
        }
        safeItems.forEach(item => {
            const link = document.createElement("a");
            link.className = "live-grid-operator";
            link.href = profileUrl(item.callsign);
            link.setAttribute("aria-label", `Open operator profile for ${item.callsign}`);
            const label = document.createElement("small");
            label.textContent = "OPERATOR";
            const callsign = document.createElement("strong");
            callsign.textContent = item.callsign;
            const presence = document.createElement("span");
            presence.textContent = item.sector;
            link.append(label, callsign, presence);
            operators.append(link);
        });
    }

    function pulseSector(sector) {
        const node = document.querySelector(`[data-sector="${sector}"]`);
        if (!node) return;
        node.classList.remove("grid-sector-pulse");
        window.requestAnimationFrame(() => node.classList.add("grid-sector-pulse"));
        window.setTimeout(() => node.classList.remove("grid-sector-pulse"), 1600);
    }

    function addPulse(item, prepend = true) {
        if (!item || knownPulseIds.has(item.id) || !allowedPulseTypes.has(item.type) || !allowedSectors.has(item.sector)) return;
        knownPulseIds.add(item.id);
        pulses.querySelector(".live-grid-empty")?.remove();
        const row = document.createElement("li");
        row.dataset.pulseId = item.id;
        const type = document.createElement("strong");
        type.textContent = item.type;
        const sector = document.createElement("span");
        sector.textContent = item.sector;
        row.append(type, sector);
        if (prepend) pulses.prepend(row); else pulses.append(row);
        while (pulses.children.length > 8) pulses.lastElementChild.remove();
        pulseSector(item.sector);
    }

    function subscribe() {
        socket.emit("live_grid_subscribe");
        window.gridVaultPresence?.setSector("ACTIVE");
    }

    socket.on("live_grid_state", state => {
        renderOperators(state?.operators);
        if (Array.isArray(state?.pulses)) state.pulses.forEach(item => addPulse(item, false));
    });
    socket.on("live_grid_presence", state => renderOperators(state?.operators));
    socket.on("live_grid_pulse", item => addPulse(item));
    if (socket.connected) subscribe();
    socket.on("connect", subscribe);
}());
