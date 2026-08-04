(function () {
    "use strict";

    const svgNamespace = "http://www.w3.org/2000/svg";
    const accents = Object.freeze({
        cyan: "#67d8c4",
        teal: "#3da59b",
        lime: "#d8ff63"
    });

    function boundedNumber(value, minimum, maximum, fallback = minimum) {
        const parsed = Number(value);
        return Number.isFinite(parsed)
            ? Math.min(maximum, Math.max(minimum, parsed))
            : fallback;
    }

    function svgElement(name, attributes = {}) {
        const element = document.createElementNS(svgNamespace, name);
        Object.entries(attributes).forEach(([key, value]) => {
            element.setAttribute(key, String(value));
        });
        return element;
    }

    function safeDash(value, fallback) {
        if (!Array.isArray(value) || value.length !== 2) return fallback;
        return value.map((part, index) => (
            boundedNumber(part, 3, 30, fallback[index])
        ));
    }

    function addRing(svg, radius, rotation, dash, stroke, width, opacity) {
        const group = svgElement("g", {
            transform: `rotate(${rotation} 50 50)`
        });
        group.append(svgElement("circle", {
            cx: 50,
            cy: 50,
            r: radius,
            fill: "none",
            stroke,
            "stroke-width": width,
            "stroke-dasharray": dash.join(" "),
            "stroke-linecap": "square",
            opacity,
            "vector-effect": "non-scaling-stroke"
        }));
        svg.append(group);
    }

    function render(container, rawParameters) {
        if (!(container instanceof Element) || !rawParameters || rawParameters.version !== 1) {
            return false;
        }
        const accent = accents[rawParameters.accent] || accents.cyan;
        const outerRotation = boundedNumber(rawParameters.outer_rotation, 0, 359);
        const middleRotation = boundedNumber(rawParameters.middle_rotation, 0, 359);
        const innerRotation = boundedNumber(rawParameters.inner_rotation, 0, 359);
        const coreRotation = boundedNumber(rawParameters.core_rotation, 0, 359);
        const circuitRotation = boundedNumber(rawParameters.circuit_rotation, 0, 359);
        const spokes = Array.isArray(rawParameters.spokes)
            ? rawParameters.spokes.slice(0, 6).map(value => boundedNumber(value, 0, 359))
            : [];

        const svg = svgElement("svg", {
            viewBox: "0 0 100 100",
            focusable: "false",
            "aria-hidden": "true",
            class: "identity-disc-svg"
        });
        svg.append(svgElement("circle", {
            cx: 50, cy: 50, r: 48, fill: "#080d0f", stroke: "#223238", "stroke-width": 1
        }));
        addRing(svg, 43, outerRotation, safeDash(rawParameters.outer_dash, [18, 8]), accent, 2.4, 0.95);
        addRing(svg, 34, middleRotation, safeDash(rawParameters.middle_dash, [13, 7]), "#8bbab4", 1.5, 0.78);
        addRing(svg, 25, innerRotation, safeDash(rawParameters.inner_dash, [10, 6]), accent, 1.8, 0.72);

        const spokeGroup = svgElement("g", { stroke: accent, "stroke-width": 1.15, opacity: 0.7 });
        spokes.forEach(angle => {
            const radians = angle * Math.PI / 180;
            spokeGroup.append(svgElement("line", {
                x1: 50 + Math.cos(radians) * 15,
                y1: 50 + Math.sin(radians) * 15,
                x2: 50 + Math.cos(radians) * 22,
                y2: 50 + Math.sin(radians) * 22,
                "vector-effect": "non-scaling-stroke"
            }));
        });
        svg.append(spokeGroup);

        const circuit = svgElement("g", {
            transform: `rotate(${circuitRotation} 50 50)`,
            fill: "none",
            stroke: "#67d8c4",
            "stroke-width": 1,
            opacity: 0.56
        });
        circuit.append(svgElement("path", {
            d: "M50 7 L50 13 L57 20 M93 50 L87 50 L80 57 M50 93 L50 87 L43 80 M7 50 L13 50 L20 43",
            "vector-effect": "non-scaling-stroke"
        }));
        svg.append(circuit);

        const core = svgElement("g", { transform: `rotate(${coreRotation} 50 50)` });
        core.append(svgElement("polygon", {
            points: "50,38 60,44 60,56 50,62 40,56 40,44",
            fill: "#0d1719",
            stroke: accent,
            "stroke-width": 1.5,
            "vector-effect": "non-scaling-stroke"
        }));
        core.append(svgElement("circle", {
            cx: 50, cy: 50, r: 4.5, fill: accent, opacity: 0.9
        }));
        svg.append(core);
        container.replaceChildren(svg);
        return true;
    }

    function renderAll(root = document) {
        root.querySelectorAll("[data-identity-disc]").forEach(container => {
            try {
                render(container, JSON.parse(container.dataset.identityDisc));
            } catch (_error) {
                container.classList.add("identity-disc-unavailable");
            }
        });
    }

    window.GridVaultIdentityDisc = Object.freeze({ render, renderAll });
    renderAll();
}());
