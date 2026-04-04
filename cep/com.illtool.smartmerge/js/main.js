/**
 * Smart Merge — Panel logic
 *
 * Form-edge-aware path endpoint merging. All math runs in ExtendScript
 * via shared libraries. No WebSocket dependency.
 */

/* global CSInterface */

var csInterface = new CSInterface();
var hasPreview = false;
var hasSidecar = false;

// ── Status Display ─────────────────────────────────────────────────

function updateStatus(state) {
    var dot = document.getElementById("statusDot");
    var label = document.getElementById("statusLabel");
    dot.className = "status-dot " + state;
    label.className = "status-label " + state;

    var labels = {
        ready: "ready",
        processing: "scanning...",
        preview: "preview active"
    };
    label.textContent = labels[state] || state;
}

function updateReadout(text) {
    document.getElementById("mergeReadout").innerHTML = text;
}

// ── Initialization ─────────────────────────────────────────────────

function init() {
    // Try loading normal sidecar
    csInterface.evalScript("loadSidecar()", function (result) {
        if (result && result.indexOf("found") === 0) {
            hasSidecar = true;
            var parts = result.split("|");
            document.getElementById("chkFormAware").disabled = false;
            updateReadout("Sidecar loaded (" + parts[1] + " paths). Select paths and Scan.");
        } else {
            hasSidecar = false;
            document.getElementById("chkFormAware").checked = false;
            document.getElementById("chkFormAware").disabled = true;
            updateReadout("No sidecar found. Proximity-only mode. Select paths and Scan.");
        }
    });

    // Radius slider live update
    var slider = document.getElementById("radiusSlider");
    var display = document.getElementById("radiusValue");
    slider.addEventListener("input", function () {
        display.textContent = this.value;
    });
    slider.addEventListener("change", function () {
        if (hasPreview) {
            // Re-scan and update preview on slider change
            var radius = parseFloat(this.value);
            var formAware = document.getElementById("chkFormAware").checked;
            csInterface.evalScript(
                "updateRadius(" + radius + ", " + formAware + ")",
                function (result) {
                    if (result && result.indexOf("error") !== 0) {
                        displayScanResult(result);
                        doPreview();
                    }
                }
            );
        }
    });

    updateStatus("ready");
}

// ── Scan ───────────────────────────────────────────────────────────

function doScan() {
    updateStatus("processing");

    var radius = parseFloat(document.getElementById("radiusSlider").value);
    var formAware = document.getElementById("chkFormAware").checked;

    csInterface.evalScript(
        "scanEndpoints(" + radius + ", " + formAware + ")",
        function (result) {
            if (!result || result.indexOf("error") === 0) {
                updateStatus("ready");
                updateReadout(result || "No selection");
                return;
            }

            displayScanResult(result);
            updateStatus("ready");

            var parts = result.split("|");
            var pairCount = parseInt(parts[0], 10);
            document.getElementById("btnPreview").disabled = (pairCount === 0);
            document.getElementById("btnMerge").disabled = (pairCount === 0);
        }
    );
}

function displayScanResult(result) {
    var parts = result.split("|");
    var pairCount = parts[0];
    var pathCount = parts[1];
    var sameSurface = parseInt(parts[2] || "0", 10);
    var crossSurface = parseInt(parts[3] || "0", 10);

    var html = '<span class="pair-count">' + pairCount + '</span> merge pairs from ' +
        pathCount + ' paths';

    if (hasSidecar && (sameSurface > 0 || crossSurface > 0)) {
        html += '<br><span class="surface-info">' +
            sameSurface + ' same-surface, ' + crossSurface + ' cross-surface</span>';
    }

    updateReadout(html);
}

// ── Preview ────────────────────────────────────────────────────────

function doPreview() {
    updateStatus("processing");

    csInterface.evalScript("previewMerge()", function (result) {
        if (result && result.indexOf("ok") === 0) {
            hasPreview = true;
            updateStatus("preview");
            document.getElementById("btnUndo").disabled = false;
        } else {
            updateStatus("ready");
        }
    });
}

// ── Merge ──────────────────────────────────────────────────────────

function doMerge() {
    updateStatus("processing");

    var chain = document.getElementById("chkChainMerge").checked;
    var preserve = document.getElementById("chkPreserveHandles").checked;

    csInterface.evalScript(
        "executeMerge(" + chain + ", " + preserve + ")",
        function (result) {
            if (result && result.indexOf("merged") === 0) {
                var count = result.split("|")[1];
                updateReadout("Merged " + count + " pair(s)");
                hasPreview = false;
                document.getElementById("btnPreview").disabled = true;
                document.getElementById("btnMerge").disabled = true;
                document.getElementById("btnUndo").disabled = true;
            }
            updateStatus("ready");
        }
    );
}

// ── Undo ───────────────────────────────────────────────────────────

function doUndo() {
    csInterface.evalScript("doUndo()", function (result) {
        if (result === "undone") {
            hasPreview = false;
            document.getElementById("btnPreview").disabled = true;
            document.getElementById("btnMerge").disabled = true;
            document.getElementById("btnUndo").disabled = true;
            updateReadout("Select paths and click Scan");
            updateStatus("ready");
        }
    });
}

// ── Start ──────────────────────────────────────────────────────────

(function () { init(); })();
