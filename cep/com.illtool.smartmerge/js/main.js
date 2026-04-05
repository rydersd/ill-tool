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
var isIsolated = false;

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
    // Clean up orphaned preview paths from previous sessions
    csInterface.evalScript("sm_cleanupOrphans()", function() {});

    // Try loading normal sidecar
    csInterface.evalScript("sm_loadSidecar()", function (result) {
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
                "sm_updateRadius(" + radius + ", " + formAware + ")",
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
        "sm_scanEndpoints(" + radius + ", " + formAware + ")",
        function (result) {
            if (!result || result.indexOf("error") === 0) {
                updateStatus("ready");
                updateReadout(escapeHtml(result || "No selection"));
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

    var html = '<span class="pair-count">' + escapeHtml(pairCount) + '</span> merge pairs from ' +
        escapeHtml(pathCount) + ' paths';

    if (hasSidecar && (sameSurface > 0 || crossSurface > 0)) {
        html += '<br><span class="surface-info">' +
            escapeHtml(String(sameSurface)) + ' same-surface, ' + escapeHtml(String(crossSurface)) + ' cross-surface</span>';
    }

    updateReadout(html);
}

// ── Preview ────────────────────────────────────────────────────────

function doPreview() {
    updateStatus("processing");

    csInterface.evalScript("sm_previewMerge()", function (result) {
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
    var pairCountEl = document.getElementById("mergeReadout").querySelector(".pair-count");
    var count = pairCountEl ? pairCountEl.textContent : "?";
    if (!confirm("Merge " + count + " path pair(s)? Original paths will be replaced.\n\nUse Cmd+Z in Illustrator to undo after merging.")) {
        return;
    }

    updateStatus("processing");

    var chain = document.getElementById("chkChainMerge").checked;
    var preserve = document.getElementById("chkPreserveHandles").checked;

    csInterface.evalScript(
        "sm_executeMerge(" + chain + ", " + preserve + ")",
        function (result) {
            if (result && result.indexOf("merged") === 0) {
                var merged = result.split("|")[1];
                updateReadout("Merged " + merged + " pair(s). Use Cmd+Z to undo.");
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

function doUndoMerge() {
    csInterface.evalScript("sm_doUndoMerge()", function (result) {
        if (result === "undone") {
            hasPreview = false;
            // Keep scan readout and Merge button enabled so user can re-preview or merge
            // Only disable Preview (can re-preview) and Undo
            document.getElementById("btnPreview").disabled = false;
            document.getElementById("btnUndo").disabled = true;
            updateStatus("ready");
        }
    });
}

// ── Isolation Mode ────────────────────────────────────────────────

function toggleIsolation() {
    var cmd = isIsolated ? "exitisolation" : "isolate";
    csInterface.evalScript("app.executeMenuCommand('" + cmd + "')", function() {
        isIsolated = !isIsolated;
        var btn = document.getElementById("btnIsolation");
        btn.style.color = isIsolated ? "#ff8800" : "#666";
        btn.title = isIsolated ? "Exit isolation mode" : "Enter isolation mode";
    });
}

// ── Utilities ─────────────────────────────────────────────────────

function escapeHtml(str) {
    var div = document.createElement("div");
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ── Keyboard Shortcuts ────────────────────────────────────────────

document.addEventListener("keydown", function(e) {
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "Enter" && !document.getElementById("btnMerge").disabled) {
        doMerge();
    } else if (e.key === "Escape") {
        doUndoMerge();
    } else if (e.key === " ") {
        e.preventDefault();
        if (!document.getElementById("btnPreview").disabled) doPreview();
    }
});

// ── Start ──────────────────────────────────────────────────────────

(function () { init(); })();
