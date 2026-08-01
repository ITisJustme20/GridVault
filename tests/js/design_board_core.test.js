"use strict";

const test = require("node:test");
const assert = require("node:assert/strict");
const core = require("../../gridvault/static/js/design_board_core.js");

test("dragging converts pointer movement through the active zoom", () => {
    const item = {x: 100, y: 200, width: 220, height: 140};
    assert.deepEqual(core.moveGeometry(item, 150, 90, 1.5), {x: 200, y: 260});
});

test("dragging remains inside the board coordinate system", () => {
    const item = {x: 10, y: 15, width: 220, height: 140};
    assert.deepEqual(core.moveGeometry(item, -1000, -1000, 1), {x: 0, y: 0});
    assert.deepEqual(
        core.moveGeometry(item, 10000, 10000, 1),
        {x: core.WORLD_WIDTH - 220, y: core.WORLD_HEIGHT - 140}
    );
});

test("resizing accounts for zoom and respects board bounds", () => {
    const item = {x: 3900, y: 2900, width: 80, height: 80};
    assert.deepEqual(core.resizeGeometry(item, 80, 80, 2), {width: 100, height: 100});
    assert.deepEqual(core.resizeGeometry(item, -500, -500, 1), {width: 40, height: 40});
});

test("zoom keeps the pointer anchored to the same board coordinate", () => {
    const rect = {left: 100, top: 50};
    const before = {zoom: 1, panX: -80, panY: 40};
    const after = core.zoomViewAt(before, 2, 500, 350, rect);
    const beforeX = (500 - rect.left - before.panX) / before.zoom;
    const beforeY = (350 - rect.top - before.panY) / before.zoom;
    const afterX = (500 - rect.left - after.panX) / after.zoom;
    const afterY = (350 - rect.top - after.panY) / after.zoom;
    assert.equal(afterX, beforeX);
    assert.equal(afterY, beforeY);
});

test("layer ordering is stable and normalized", () => {
    const elements = [
        {id: "a", z: 10},
        {id: "b", z: -8},
        {id: "c", z: 4},
    ];
    const front = core.reorder(elements, "b", "front");
    assert.deepEqual(front.map(item => item.id), ["c", "a", "b"]);
    assert.deepEqual(front.map(item => item.z), [0, 1, 2]);
    const back = core.reorder(front, "a", "back");
    assert.deepEqual(back.map(item => item.id), ["a", "c", "b"]);
});

test("arrows normalize into a literal line with persistent endpoints", () => {
    const arrow = core.normalizeArrow({x: 100, y: 200, width: 220, height: 70});
    assert.deepEqual(arrow, {
        start_x: 120,
        start_y: 235,
        end_x: 300,
        end_y: 235,
        x: 102,
        y: 217,
        width: 216,
        height: 40,
    });
});

test("arrows move through zoom and either endpoint changes direction", () => {
    const arrow = core.normalizeArrow({x: 100, y: 200, width: 220, height: 70});
    const moved = core.moveArrow(arrow, 90, -30, 1.5);
    assert.equal(moved.start_x, 180);
    assert.equal(moved.start_y, 215);
    assert.equal(moved.end_x, 360);
    assert.equal(moved.end_y, 215);

    const redirected = core.moveArrowEndpoint(arrow, "end", 75, -150, 1.5);
    assert.equal(redirected.start_x, 120);
    assert.equal(redirected.start_y, 235);
    assert.equal(redirected.end_x, 350);
    assert.equal(redirected.end_y, 135);
});

test("arrow endpoints snap to four directions but retain free angles", () => {
    const arrow = core.normalizeArrow({x: 100, y: 200, width: 220, height: 70});
    const right = core.moveArrowEndpoint(arrow, "end", 50, 15, 1);
    assert.deepEqual([right.end_x, right.end_y], [350, 235]);

    const left = core.moveArrowEndpoint(arrow, "end", -260, 10, 1);
    assert.deepEqual([left.end_x, left.end_y], [40, 235]);

    const down = core.moveArrowEndpoint(arrow, "end", -175, 100, 1);
    assert.deepEqual([down.end_x, down.end_y], [120, 335]);

    const up = core.moveArrowEndpoint(arrow, "end", -175, -200, 1);
    assert.deepEqual([up.end_x, up.end_y], [120, 35]);

    const free = core.moveArrowEndpoint(arrow, "end", 30, 80, 1);
    assert.deepEqual([free.end_x, free.end_y], [330, 315]);

    const bypassed = core.moveArrowEndpoint(arrow, "end", 50, 15, 1, false);
    assert.deepEqual([bypassed.end_x, bypassed.end_y], [350, 250]);
});

test("duplicating preserves every object field and offsets arrow endpoints", () => {
    const reference = {
        id: "reference-1", type: "reference", x: 100, y: 120,
        width: 260, height: 150, z: 2, content: "Source",
        color: "#67d8c4", url: "https://example.com/reference"
    };
    const referenceCopy = core.duplicateElement(reference, "reference-2", 3);
    assert.deepEqual(referenceCopy, {
        ...reference,
        id: "reference-2",
        z: 3,
        x: 124,
        y: 144
    });

    const arrow = {
        id: "arrow-1", type: "arrow", z: 4, color: "#67d8c4",
        content: "", url: "", start_x: 120, start_y: 235,
        end_x: 300, end_y: 235, x: 102, y: 217, width: 216, height: 40
    };
    const arrowCopy = core.duplicateElement(arrow, "arrow-2", 5);
    assert.equal(arrowCopy.id, "arrow-2");
    assert.equal(arrowCopy.z, 5);
    assert.deepEqual(
        [arrowCopy.start_x, arrowCopy.start_y, arrowCopy.end_x, arrowCopy.end_y],
        [144, 259, 324, 259]
    );
});

test("structured objects copy deeply and connectors follow object centers", () => {
    const source = {id: "a", type: "architecture", x: 100, y: 100, width: 200, height: 100};
    const target = {id: "b", type: "database", x: 500, y: 140, width: 180, height: 140};
    const geometry = core.connectorGeometry(source, target);
    assert.equal(geometry.start_x, 300);
    assert.equal(geometry.end_x, 500);

    const moved = {...target, x: 620, y: 400};
    assert.notDeepEqual(core.connectorGeometry(source, moved), geometry);

    const original = {...source, data: {name: "Gateway", nested: {state: "planned"}}};
    const copy = core.duplicateElement(original, "copy", 4);
    copy.data.nested.state = "active";
    assert.equal(original.data.nested.state, "planned");
    assert.equal(copy.id, "copy");
});

test("object movement snaps left, center, right, top, middle, and bottom", () => {
    const moving = {
        id: "moving", type: "rectangle", x: 0, y: 100,
        width: 100, height: 80
    };
    const horizontalTarget = {
        id: "horizontal", type: "rectangle", x: 300, y: 500,
        width: 200, height: 200
    };
    for (const [proposedX, expectedX] of [[303, 300], [347, 350], [397, 400]]) {
        const result = core.snapElementMove(
            moving,
            {x: proposedX, y: 100},
            [moving, horizontalTarget],
            1
        );
        assert.equal(result.geometry.x, expectedX);
        assert.equal(result.guides[0].orientation, "vertical");
    }

    const verticalTarget = {
        id: "vertical", type: "rectangle", x: 500, y: 200,
        width: 200, height: 200
    };
    for (const [proposedY, expectedY] of [[203, 200], [257, 260], [317, 320]]) {
        const result = core.snapElementMove(
            moving,
            {x: 100, y: proposedY},
            [moving, verticalTarget],
            1
        );
        assert.equal(result.geometry.y, expectedY);
        assert.equal(result.guides[0].orientation, "horizontal");
    }
});

test("alignment threshold stays subtle at different zoom levels", () => {
    const moving = {
        id: "moving", type: "rectangle", x: 0, y: 0,
        width: 100, height: 100
    };
    const target = {
        id: "target", type: "rectangle", x: 300, y: 500,
        width: 100, height: 100
    };
    const snapped = core.snapElementMove(
        moving,
        {x: 194, y: 0},
        [moving, target],
        1
    );
    const unsnappedAtZoom = core.snapElementMove(
        moving,
        {x: 196, y: 0},
        [moving, target],
        2
    );
    assert.equal(snapped.geometry.x, 200);
    assert.equal(unsnappedAtZoom.geometry.x, 196);
});

test("equal spacing snaps between neighboring objects and emits gap guides", () => {
    const left = {
        id: "left", type: "rectangle", x: 0, y: 0,
        width: 100, height: 100
    };
    const moving = {
        id: "moving", type: "rectangle", x: 140, y: 0,
        width: 100, height: 100
    };
    const right = {
        id: "right", type: "rectangle", x: 300, y: 0,
        width: 100, height: 100
    };
    const result = core.snapElementMove(
        moving,
        {x: 153, y: 0},
        [left, moving, right],
        1
    );
    assert.equal(result.geometry.x, 150);
    assert.equal(result.guides.filter(guide => guide.type === "spacing").length, 2);

    const top = {...left, id: "top"};
    const verticalMoving = {...moving, id: "vertical-moving", x: 0, y: 140};
    const bottom = {...right, id: "bottom", x: 0, y: 300};
    const verticalResult = core.snapElementMove(
        verticalMoving,
        {x: 0, y: 153},
        [top, verticalMoving, bottom],
        1
    );
    assert.equal(verticalResult.geometry.y, 150);
    assert.equal(
        verticalResult.guides.filter(guide => guide.type === "spacing").length,
        2
    );
});

test("arrow shafts and endpoints align with arrows and object centers", () => {
    const moving = {
        id: "arrow-moving", type: "arrow", start_x: 100, start_y: 237,
        end_x: 347, end_y: 237, x: 82, y: 219, width: 283, height: 40
    };
    const target = {
        id: "target", type: "rectangle", x: 300, y: 200,
        width: 100, height: 80
    };
    const moved = core.snapElementMove(moving, moving, [moving, target], 1);
    assert.deepEqual(
        [moved.geometry.start_x, moved.geometry.start_y,
            moved.geometry.end_x, moved.geometry.end_y],
        [103, 240, 350, 240]
    );

    const otherArrow = {
        id: "arrow-target", type: "arrow", start_x: 900, start_y: 500,
        end_x: 1100, end_y: 500, x: 882, y: 482, width: 236, height: 40
    };
    const nearArrow = {
        ...moving,
        start_y: 496,
        end_y: 496
    };
    const aligned = core.snapElementMove(
        nearArrow,
        nearArrow,
        [nearArrow, otherArrow],
        1
    );
    assert.equal(aligned.geometry.start_y, 500);
    assert.equal(aligned.geometry.end_y, 500);

    const endpoint = core.snapArrowEndpoint(
        moving,
        {...moving, end_x: 347, end_y: 238},
        "end",
        [moving, target],
        1
    );
    assert.deepEqual(
        [endpoint.geometry.end_x, endpoint.geometry.end_y],
        [350, 240]
    );
});
