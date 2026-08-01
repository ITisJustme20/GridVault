(function (root, factory) {
    "use strict";
    const api = factory();
    if (typeof module === "object" && module.exports) module.exports = api;
    else root.GridVaultBoardCore = api;
})(typeof globalThis !== "undefined" ? globalThis : this, function () {
    "use strict";

    const WORLD_WIDTH = 4000;
    const WORLD_HEIGHT = 3000;
    const MIN_SIZE = 40;
    const MIN_ZOOM = 0.25;
    const MAX_ZOOM = 2.5;

    function clamp(value, minimum, maximum) {
        return Math.min(maximum, Math.max(minimum, value));
    }

    function moveGeometry(item, deltaClientX, deltaClientY, zoom) {
        return {
            x: Math.round(clamp(
                item.x + deltaClientX / zoom,
                0,
                WORLD_WIDTH - item.width
            )),
            y: Math.round(clamp(
                item.y + deltaClientY / zoom,
                0,
                WORLD_HEIGHT - item.height
            ))
        };
    }

    function resizeGeometry(item, deltaClientX, deltaClientY, zoom) {
        return {
            width: Math.round(clamp(
                item.width + deltaClientX / zoom,
                MIN_SIZE,
                WORLD_WIDTH - item.x
            )),
            height: Math.round(clamp(
                item.height + deltaClientY / zoom,
                MIN_SIZE,
                WORLD_HEIGHT - item.y
            ))
        };
    }

    function zoomViewAt(view, requestedZoom, clientX, clientY, rect) {
        const zoom = clamp(requestedZoom, MIN_ZOOM, MAX_ZOOM);
        const worldX = (clientX - rect.left - view.panX) / view.zoom;
        const worldY = (clientY - rect.top - view.panY) / view.zoom;
        return {
            zoom,
            panX: clientX - rect.left - worldX * zoom,
            panY: clientY - rect.top - worldY * zoom
        };
    }

    function reorder(elements, selectedId, direction) {
        const ordered = elements.slice().sort((a, b) => a.z - b.z);
        const index = ordered.findIndex(item => item.id === selectedId);
        if (index < 0) return elements;
        const [selected] = ordered.splice(index, 1);
        if (direction === "front") ordered.push(selected);
        else ordered.unshift(selected);
        ordered.forEach((item, position) => { item.z = position; });
        return ordered;
    }

    return {
        WORLD_WIDTH,
        WORLD_HEIGHT,
        MIN_SIZE,
        MIN_ZOOM,
        MAX_ZOOM,
        clamp,
        moveGeometry,
        resizeGeometry,
        zoomViewAt,
        reorder
    };
});
