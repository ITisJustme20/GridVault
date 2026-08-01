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
