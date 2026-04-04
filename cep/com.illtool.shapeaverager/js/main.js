/**
 * Shape Averager — Panel logic
 *
 * Fully standalone: all math runs in ExtendScript via shared libraries.
 * No WebSocket dependency. Communicates with Illustrator via
 * CSInterface.evalScript() only.
 */

/* global CSInterface */

// ── State ──────────────────────────────────────────────────────────

var csInterface = new CSInterface();
var activeShape = null;          // currently highlighted shape type
var hasPreview = false;          // tracks whether a preview path exists

// ── Status Display ─────────────────────────────────────────────────

/**
 * Update the status indicator. States:
 *   "ready"      — idle, waiting for user action
 *   "processing" — running ExtendScript operation
 *   "preview"    — preview path is placed and active
 */
function updateStatus(state) {
    var dot = document.getElementById("statusDot");
    var label = document.getElementById("statusLabel");

    // Remove all state classes, apply new one
    dot.className = "status-dot " + state;
    label.className = "status-label " + state;

    var labels = {
        ready: "ready",
        processing: "processing...",
        preview: "preview active"
    };
    label.textContent = labels[state] || state;
}

// ── Shape Buttons ──────────────────────────────────────────────────

function initShapeButtons() {
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        buttons[i].addEventListener("click", function () {
            var shapeType = this.getAttribute("data-shape");
            highlightShape(shapeType);
            reclassify(shapeType);
        });
    }
}

function highlightShape(shapeType) {
    activeShape = shapeType;
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        if (buttons[i].getAttribute("data-shape") === shapeType) {
            buttons[i].classList.add("active");
        } else {
            buttons[i].classList.remove("active");
        }
    }
}

function clearShapeHighlight() {
    activeShape = null;
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        buttons[i].classList.remove("active");
    }
}

// ── Slider Value Display ───────────────────────────────────────────

function initSliders() {
    var sliders = [
        { id: "cornerSlider",  display: "cornerValue" },
        { id: "tensionSlider", display: "tensionValue" }
    ];

    for (var s = 0; s < sliders.length; s++) {
        (function (cfg) {
            var slider = document.getElementById(cfg.id);
            var display = document.getElementById(cfg.display);
            slider.addEventListener("input", function () {
                display.textContent = this.value;
            });
        })(sliders[s]);
    }

    // Simplification slider — calls applyLODLevel in ExtendScript
    var simplifySlider = document.getElementById("simplifySlider");
    var simplifyDisplay = document.getElementById("simplifyValue");
    simplifySlider.addEventListener("input", function () {
        simplifyDisplay.textContent = this.value;
        onSimplifySlider();
    });

    // Tension slider — resmooth on change when preview is active
    var tensionSlider = document.getElementById("tensionSlider");
    tensionSlider.addEventListener("change", function () {
        if (hasPreview) {
            var tension = parseInt(this.value, 10) / 600;  // map 0-100 to 0-0.167
            csInterface.evalScript("resmooth(" + tension + ")", function () {});
        }
    });
}

// ── Core Actions ───────────────────────────────────────────────────

/**
 * Average the currently selected anchors.
 * All classification, sorting, LOD precomputation, and preview placement
 * happen in ExtendScript — no WebSocket needed.
 */
function averageSelection() {
    updateStatus("processing");

    csInterface.evalScript("averageSelectedAnchors()", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus("ready");
            updateDetected(result || "No selection", null);
            return;
        }

        var parts = result.split("|");
        // parts: [shape, confidence, inputCount, outputCount]
        updateDetected(parts[0], parseFloat(parts[1]));
        highlightShape(parts[0]);
        hasPreview = true;
        updateStatus("preview");

        document.getElementById("btnConfirm").disabled = false;
        // LOD is already precomputed in ExtendScript
        document.getElementById("simplifySlider").disabled = false;
    });
}

/**
 * Force reclassify as a specific shape type.
 */
function reclassify(shapeType) {
    updateStatus("processing");

    csInterface.evalScript("reclassifyAs('" + shapeType + "')", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus(hasPreview ? "preview" : "ready");
            return;
        }

        var parts = result.split("|");
        updateDetected(parts[0], parseFloat(parts[1]));
        highlightShape(parts[0]);
        updateStatus("preview");
    });
}

/**
 * Slider handler: apply LOD level from precomputed cache in ExtendScript.
 * Instant — no network round-trip.
 */
function onSimplifySlider() {
    if (!hasPreview) return;
    var val = parseInt(document.getElementById("simplifySlider").value, 10);

    csInterface.evalScript("applyLODLevel(" + val + ")", function (result) {
        if (result && result.indexOf("error") !== 0) {
            document.getElementById("simplifiedCount").textContent = result;
        }
    });
}

/**
 * Update the classification readout display.
 */
function updateDetected(shapeName, confidence) {
    var el = document.getElementById("detected");
    if (confidence !== null && confidence !== undefined) {
        el.innerHTML =
            'Detected: <span class="shape-name">' + escapeHtml(shapeName) +
            '</span> <span class="confidence">(' + confidence.toFixed(2) + ')</span>';
    } else {
        el.textContent = shapeName;
    }
}

/**
 * Confirm the preview path — solidify and clear state.
 */
function confirmPreview() {
    csInterface.evalScript("doConfirm()", function (result) {
        if (result === "confirmed") {
            hasPreview = false;
            document.getElementById("btnConfirm").disabled = true;
            document.getElementById("simplifySlider").disabled = true;
            updateStatus("ready");
        }
    });
}

/**
 * Undo the preview path — remove and clear state.
 */
function undoPreview() {
    csInterface.evalScript("doUndo()", function (result) {
        if (result === "undone") {
            hasPreview = false;
            document.getElementById("btnConfirm").disabled = true;
            document.getElementById("simplifySlider").disabled = true;
            clearShapeHighlight();
            updateDetected("No selection", null);
            updateStatus("ready");
        }
    });
}

// ── Utilities ──────────────────────────────────────────────────────

function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initShapeButtons();
    initSliders();
    updateStatus("ready");
})();
