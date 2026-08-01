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
    const ARROW_PADDING = 18;
    const ARROW_SNAP_DEGREES = 10;
    const ALIGNMENT_SNAP_PX = 7;

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

    function arrowBounds(points) {
        const minimumX = Math.min(points.start_x, points.end_x);
        const maximumX = Math.max(points.start_x, points.end_x);
        const minimumY = Math.min(points.start_y, points.end_y);
        const maximumY = Math.max(points.start_y, points.end_y);
        const x = clamp(
            minimumX - ARROW_PADDING,
            0,
            WORLD_WIDTH - MIN_SIZE
        );
        const y = clamp(
            minimumY - ARROW_PADDING,
            0,
            WORLD_HEIGHT - MIN_SIZE
        );
        const right = clamp(
            maximumX + ARROW_PADDING,
            x + MIN_SIZE,
            WORLD_WIDTH
        );
        const bottom = clamp(
            maximumY + ARROW_PADDING,
            y + MIN_SIZE,
            WORLD_HEIGHT
        );
        return {
            x: Math.round(x),
            y: Math.round(y),
            width: Math.round(right - x),
            height: Math.round(bottom - y)
        };
    }

    function normalizeArrow(item) {
        const x = Number(item.x) || 0;
        const y = Number(item.y) || 0;
        const width = Math.max(Number(item.width) || 220, MIN_SIZE);
        const height = Math.max(Number(item.height) || 70, MIN_SIZE);
        const points = {
            start_x: Number.isFinite(Number(item.start_x))
                ? Number(item.start_x)
                : x + Math.min(20, width / 4),
            start_y: Number.isFinite(Number(item.start_y))
                ? Number(item.start_y)
                : y + height / 2,
            end_x: Number.isFinite(Number(item.end_x))
                ? Number(item.end_x)
                : x + width - Math.min(20, width / 4),
            end_y: Number.isFinite(Number(item.end_y))
                ? Number(item.end_y)
                : y + height / 2
        };
        Object.keys(points).forEach(key => {
            const limit = key.endsWith("_x") ? WORLD_WIDTH : WORLD_HEIGHT;
            points[key] = Math.round(clamp(points[key], 0, limit));
        });
        return {...points, ...arrowBounds(points)};
    }

    function moveArrow(item, deltaClientX, deltaClientY, zoom) {
        const arrow = normalizeArrow(item);
        const deltaX = clamp(
            deltaClientX / zoom,
            -Math.min(arrow.start_x, arrow.end_x),
            WORLD_WIDTH - Math.max(arrow.start_x, arrow.end_x)
        );
        const deltaY = clamp(
            deltaClientY / zoom,
            -Math.min(arrow.start_y, arrow.end_y),
            WORLD_HEIGHT - Math.max(arrow.start_y, arrow.end_y)
        );
        return normalizeArrow({
            ...arrow,
            start_x: arrow.start_x + deltaX,
            start_y: arrow.start_y + deltaY,
            end_x: arrow.end_x + deltaX,
            end_y: arrow.end_y + deltaY
        });
    }

    function snapArrowPoint(anchor, point, thresholdDegrees = ARROW_SNAP_DEGREES) {
        const deltaX = point.x - anchor.x;
        const deltaY = point.y - anchor.y;
        const horizontalDistance = Math.abs(deltaX);
        const verticalDistance = Math.abs(deltaY);
        const threshold = Math.tan(thresholdDegrees * Math.PI / 180);
        if (verticalDistance <= horizontalDistance * threshold) {
            return {x: point.x, y: anchor.y};
        }
        if (horizontalDistance <= verticalDistance * threshold) {
            return {x: anchor.x, y: point.y};
        }
        return point;
    }

    function moveArrowEndpoint(
        item,
        endpoint,
        deltaClientX,
        deltaClientY,
        zoom,
        snap = true
    ) {
        const arrow = normalizeArrow(item);
        const prefix = endpoint === "start" ? "start" : "end";
        const anchorPrefix = prefix === "start" ? "end" : "start";
        let point = {
            x: clamp(
                arrow[`${prefix}_x`] + deltaClientX / zoom,
                0,
                WORLD_WIDTH
            ),
            y: clamp(
                arrow[`${prefix}_y`] + deltaClientY / zoom,
                0,
                WORLD_HEIGHT
            )
        };
        if (snap) {
            point = snapArrowPoint({
                x: arrow[`${anchorPrefix}_x`],
                y: arrow[`${anchorPrefix}_y`]
            }, point);
        }
        arrow[`${prefix}_x`] = point.x;
        arrow[`${prefix}_y`] = point.y;
        return normalizeArrow(arrow);
    }

    function duplicateElement(item, id, z, offset = 24) {
        const duplicate = {...item, id, z};
        if (item.type === "arrow") {
            return {...duplicate, ...moveArrow(item, offset, offset, 1)};
        }
        return {...duplicate, ...moveGeometry(item, offset, offset, 1)};
    }

    function elementBounds(item) {
        const geometry = item.type === "arrow" ? normalizeArrow(item) : item;
        const x = Number(geometry.x) || 0;
        const y = Number(geometry.y) || 0;
        const width = Math.max(Number(geometry.width) || MIN_SIZE, MIN_SIZE);
        const height = Math.max(Number(geometry.height) || MIN_SIZE, MIN_SIZE);
        return {
            x,
            y,
            width,
            height,
            right: x + width,
            bottom: y + height,
            centerX: x + width / 2,
            centerY: y + height / 2
        };
    }

    function uniqueAnchors(anchors) {
        const seen = new Set();
        return anchors.filter(anchor => {
            const key = `${Math.round(anchor.value * 100)}/${Math.round(anchor.cross * 100)}`;
            if (seen.has(key)) return false;
            seen.add(key);
            return true;
        });
    }

    function alignmentAnchors(item, axis) {
        const bounds = elementBounds(item);
        if (item.type === "arrow") {
            const arrow = normalizeArrow(item);
            return uniqueAnchors(axis === "x" ? [
                {value: arrow.start_x, cross: arrow.start_y},
                {value: arrow.end_x, cross: arrow.end_y},
                {
                    value: (arrow.start_x + arrow.end_x) / 2,
                    cross: (arrow.start_y + arrow.end_y) / 2
                }
            ] : [
                {value: arrow.start_y, cross: arrow.start_x},
                {value: arrow.end_y, cross: arrow.end_x},
                {
                    value: (arrow.start_y + arrow.end_y) / 2,
                    cross: (arrow.start_x + arrow.end_x) / 2
                }
            ]);
        }
        return axis === "x" ? [
            {value: bounds.x, cross: bounds.centerY},
            {value: bounds.centerX, cross: bounds.centerY},
            {value: bounds.right, cross: bounds.centerY}
        ] : [
            {value: bounds.y, cross: bounds.centerX},
            {value: bounds.centerY, cross: bounds.centerX},
            {value: bounds.bottom, cross: bounds.centerX}
        ];
    }

    function bestAlignmentCandidate(moving, others, axis, threshold) {
        const movingAnchors = alignmentAnchors(moving, axis);
        let best = null;
        for (const target of others) {
            for (const movingAnchor of movingAnchors) {
                for (const targetAnchor of alignmentAnchors(target, axis)) {
                    const delta = targetAnchor.value - movingAnchor.value;
                    if (Math.abs(delta) > threshold) continue;
                    if (!best || Math.abs(delta) < Math.abs(best.delta)) {
                        best = {
                            kind: "alignment",
                            axis,
                            delta,
                            position: targetAnchor.value,
                            movingCross: movingAnchor.cross,
                            targetCross: targetAnchor.cross
                        };
                    }
                }
            }
        }
        return best;
    }

    function rangesOverlap(startA, endA, startB, endB) {
        return Math.max(startA, startB) <= Math.min(endA, endB);
    }

    function spacingCandidate(moving, others, axis, threshold) {
        const bounds = elementBounds(moving);
        const targets = others.map(elementBounds);
        if (axis === "x") {
            const aligned = targets.filter(target => rangesOverlap(
                bounds.y,
                bounds.bottom,
                target.y,
                target.bottom
            ));
            const before = aligned
                .filter(target => target.right <= bounds.x)
                .sort((a, b) => b.right - a.right)[0];
            const after = aligned
                .filter(target => target.x >= bounds.right)
                .sort((a, b) => a.x - b.x)[0];
            if (!before || !after) return null;
            const ideal = (before.right + after.x - bounds.width) / 2;
            const delta = ideal - bounds.x;
            if (Math.abs(delta) > threshold) return null;
            return {kind: "spacing", axis, delta, before, after};
        }
        const aligned = targets.filter(target => rangesOverlap(
            bounds.x,
            bounds.right,
            target.x,
            target.right
        ));
        const before = aligned
            .filter(target => target.bottom <= bounds.y)
            .sort((a, b) => b.bottom - a.bottom)[0];
        const after = aligned
            .filter(target => target.y >= bounds.bottom)
            .sort((a, b) => a.y - b.y)[0];
        if (!before || !after) return null;
        const ideal = (before.bottom + after.y - bounds.height) / 2;
        const delta = ideal - bounds.y;
        if (Math.abs(delta) > threshold) return null;
        return {kind: "spacing", axis, delta, before, after};
    }

    function chooseSnapCandidate(alignment, spacing) {
        if (!alignment) return spacing;
        if (!spacing) return alignment;
        return Math.abs(alignment.delta) <= Math.abs(spacing.delta)
            ? alignment
            : spacing;
    }

    function translateArrow(item, deltaX, deltaY) {
        const arrow = normalizeArrow(item);
        return normalizeArrow({
            ...arrow,
            start_x: arrow.start_x + deltaX,
            start_y: arrow.start_y + deltaY,
            end_x: arrow.end_x + deltaX,
            end_y: arrow.end_y + deltaY
        });
    }

    function candidateGuides(candidate, finalBounds, crossDelta) {
        if (!candidate) return [];
        if (candidate.kind === "alignment") {
            return [{
                type: "alignment",
                orientation: candidate.axis === "x" ? "vertical" : "horizontal",
                position: candidate.position,
                start: Math.min(
                    candidate.movingCross + crossDelta,
                    candidate.targetCross
                ),
                end: Math.max(
                    candidate.movingCross + crossDelta,
                    candidate.targetCross
                )
            }];
        }
        if (candidate.axis === "x") {
            return [
                {
                    type: "spacing",
                    orientation: "horizontal",
                    position: finalBounds.centerY,
                    start: candidate.before.right,
                    end: finalBounds.x
                },
                {
                    type: "spacing",
                    orientation: "horizontal",
                    position: finalBounds.centerY,
                    start: finalBounds.right,
                    end: candidate.after.x
                }
            ];
        }
        return [
            {
                type: "spacing",
                orientation: "vertical",
                position: finalBounds.centerX,
                start: candidate.before.bottom,
                end: finalBounds.y
            },
            {
                type: "spacing",
                orientation: "vertical",
                position: finalBounds.centerX,
                start: finalBounds.bottom,
                end: candidate.after.y
            }
        ];
    }

    function snapElementMove(item, proposed, elements, zoom) {
        const moving = {...item, ...proposed};
        const others = elements.filter(element => element.id !== item.id);
        const threshold = ALIGNMENT_SNAP_PX / zoom;
        const snapX = chooseSnapCandidate(
            bestAlignmentCandidate(moving, others, "x", threshold),
            spacingCandidate(moving, others, "x", threshold)
        );
        const snapY = chooseSnapCandidate(
            bestAlignmentCandidate(moving, others, "y", threshold),
            spacingCandidate(moving, others, "y", threshold)
        );
        const deltaX = snapX ? snapX.delta : 0;
        const deltaY = snapY ? snapY.delta : 0;
        const geometry = item.type === "arrow"
            ? translateArrow(moving, deltaX, deltaY)
            : {...proposed, x: proposed.x + deltaX, y: proposed.y + deltaY};
        const finalBounds = elementBounds({...item, ...geometry});
        return {
            geometry,
            guides: [
                ...candidateGuides(snapX, finalBounds, deltaY),
                ...candidateGuides(snapY, finalBounds, deltaX)
            ]
        };
    }

    function snapArrowEndpoint(item, proposed, endpoint, elements, zoom) {
        const moving = {...item, ...proposed};
        const arrow = normalizeArrow(moving);
        const prefix = endpoint === "start" ? "start" : "end";
        const point = {
            x: arrow[`${prefix}_x`],
            y: arrow[`${prefix}_y`]
        };
        const others = elements.filter(element => element.id !== item.id);
        const threshold = ALIGNMENT_SNAP_PX / zoom;
        let bestX = null;
        let bestY = null;
        for (const target of others) {
            for (const anchor of alignmentAnchors(target, "x")) {
                const delta = anchor.value - point.x;
                if (
                    Math.abs(delta) <= threshold
                    && (!bestX || Math.abs(delta) < Math.abs(bestX.delta))
                ) {
                    bestX = {delta, position: anchor.value, cross: anchor.cross};
                }
            }
            for (const anchor of alignmentAnchors(target, "y")) {
                const delta = anchor.value - point.y;
                if (
                    Math.abs(delta) <= threshold
                    && (!bestY || Math.abs(delta) < Math.abs(bestY.delta))
                ) {
                    bestY = {delta, position: anchor.value, cross: anchor.cross};
                }
            }
        }
        if (bestX) arrow[`${prefix}_x`] = bestX.position;
        if (bestY) arrow[`${prefix}_y`] = bestY.position;
        const geometry = normalizeArrow(arrow);
        const finalX = geometry[`${prefix}_x`];
        const finalY = geometry[`${prefix}_y`];
        const guides = [];
        if (bestX) guides.push({
            type: "alignment",
            orientation: "vertical",
            position: bestX.position,
            start: Math.min(finalY, bestX.cross),
            end: Math.max(finalY, bestX.cross)
        });
        if (bestY) guides.push({
            type: "alignment",
            orientation: "horizontal",
            position: bestY.position,
            start: Math.min(finalX, bestY.cross),
            end: Math.max(finalX, bestY.cross)
        });
        return {geometry, guides};
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
        ARROW_PADDING,
        ARROW_SNAP_DEGREES,
        ALIGNMENT_SNAP_PX,
        clamp,
        moveGeometry,
        resizeGeometry,
        zoomViewAt,
        arrowBounds,
        normalizeArrow,
        moveArrow,
        snapArrowPoint,
        moveArrowEndpoint,
        duplicateElement,
        elementBounds,
        alignmentAnchors,
        snapElementMove,
        snapArrowEndpoint,
        reorder
    };
});
