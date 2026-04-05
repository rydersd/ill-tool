/**
 * Shape Cleanup — Panel logic
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
var selectionPollId = null;      // timer for polling selection state
var lastSelectionState = "";     // last polled selection for change detection
var activeTab = "Simplify";      // current tab: "Simplify" or "Cluster"
var isIsolated = false;          // isolation mode state
var reAverageTimer = null;       // debounce timer for live re-average

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

// ── Tab Switching ──────────────────────────────────────────────────

function switchTab(tabName) {
    activeTab = tabName;
    var tabs = document.querySelectorAll(".tab-btn");
    for (var i = 0; i < tabs.length; i++) {
        if (tabs[i].getAttribute("data-tab") === tabName) {
            tabs[i].classList.add("active");
        } else {
            tabs[i].classList.remove("active");
        }
    }
    document.getElementById("tabSimplify").style.display = (tabName === "Simplify") ? "block" : "none";
    document.getElementById("tabCluster").style.display = (tabName === "Cluster") ? "block" : "none";
}

// ── Isolation Mode Toggle ─────────────────────────────────────────

function toggleIsolation() {
    if (isIsolated) {
        csInterface.evalScript("app.executeMenuCommand('exitisolation')", function() {
            isIsolated = false;
            updateIsolationButton();
        });
    } else {
        csInterface.evalScript("app.executeMenuCommand('isolate')", function() {
            isIsolated = true;
            updateIsolationButton();
        });
    }
}

function updateIsolationButton() {
    var btn = document.getElementById("btnIsolation");
    if (!btn) return;
    if (isIsolated) {
        btn.classList.add("active");
        btn.title = "Exit Isolation Mode";
    } else {
        btn.classList.remove("active");
        btn.title = "Toggle Isolation Mode";
    }
}

// ── Shape Buttons ──────────────────────────────────────────────────

function initShapeButtons() {
    var buttons = document.querySelectorAll(".shape-btn");
    for (var i = 0; i < buttons.length; i++) {
        // Disabled until a preview exists
        buttons[i].disabled = true;
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
            csInterface.evalScript("sa_resmooth(" + tension + ")", function () {});
        }
    });

    // Distance slider — update value display
    var distanceSlider = document.getElementById("distanceSlider");
    var distanceDisplay = document.getElementById("distanceValue");
    if (distanceSlider && distanceDisplay) {
        distanceSlider.addEventListener("input", function () {
            distanceDisplay.textContent = this.value;
        });
    }
}

// ── Core Actions ───────────────────────────────────────────────────

/**
 * Average the currently selected anchors.
 * All classification, sorting, LOD precomputation, and preview placement
 * happen in ExtendScript — no WebSocket needed.
 */
function averageSelection() {
    updateStatus("processing");

    csInterface.evalScript("sa_averageSelectedAnchors()", function (result) {
        if (!result || result.indexOf("error") === 0) {
            updateStatus("ready");
            var errMsg = result ? result.replace(/^error\|/, "") : "No selection";
            updateDetected(errMsg, null);
            return;
        }

        var parts = result.split("|");
        // parts: [shape, confidence, inputCount, outputCount]
        updateDetected(parts[0], parseFloat(parts[1]));
        highlightShape(parts[0]);
        hasPreview = true;
        lastSelectionState = "";  // reset so polling can detect changes
        updateStatus("preview");

        document.getElementById("btnConfirm").disabled = false;
        // LOD is already precomputed in ExtendScript
        document.getElementById("simplifySlider").disabled = false;

        // Enable shape override buttons
        var shapeBtns = document.querySelectorAll(".shape-btn");
        for (var sb = 0; sb < shapeBtns.length; sb++) shapeBtns[sb].disabled = false;

        // Hide first-use guidance
        var help = document.getElementById("helpText");
        if (help) help.style.display = "none";
    });
}

/**
 * Force reclassify as a specific shape type.
 */
var VALID_SHAPES = ["line","arc","lshape","rectangle","scurve","ellipse","freeform"];

function reclassify(shapeType) {
    if (VALID_SHAPES.indexOf(shapeType) === -1) return;
    updateStatus("processing");

    csInterface.evalScript("sa_reclassifyAs('" + shapeType + "')", function (result) {
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

    csInterface.evalScript("sa_applyLODLevel(" + val + ")", function (result) {
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
 * Confirm the preview path — solidify, enter isolation mode, clear state.
 */
function confirmPreview() {
    var layerName = document.getElementById("cleanupLayerName").value.replace(/'/g, "\\'") || "";
    csInterface.evalScript("sa_doConfirm('" + layerName + "')", function (result) {
        if (result && result.indexOf("confirmed") === 0) {
            hasPreview = false;
            document.getElementById("btnConfirm").disabled = true;
            document.getElementById("simplifySlider").disabled = true;

            // Disable shape override buttons
            var shapeBtns = document.querySelectorAll(".shape-btn");
            for (var sb = 0; sb < shapeBtns.length; sb++) shapeBtns[sb].disabled = true;

            // Show isolation mode hint and guidance
            updateDetected("In isolation mode \u2014 press Esc to exit", null);
            document.getElementById("isolationHint").style.display = "block";
            isIsolated = true;
            updateIsolationButton();
            updateStatus("ready");
        }
    });
}

/**
 * Undo the preview path — remove and clear state.
 */
function undoPreview() {
    csInterface.evalScript("sa_doUndoAverage()", function (result) {
        if (result === "undone") {
            hasPreview = false;
            document.getElementById("btnConfirm").disabled = true;
            document.getElementById("simplifySlider").disabled = true;
            clearShapeHighlight();
            updateDetected("No selection", null);

            // Disable shape override buttons
            var shapeBtns = document.querySelectorAll(".shape-btn");
            for (var sb = 0; sb < shapeBtns.length; sb++) shapeBtns[sb].disabled = true;

            // Hide isolation hint if visible
            document.getElementById("isolationHint").style.display = "none";

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

// ── Isolation Mode Exit ───────────────────────────────────────────

function exitIsolation() {
    csInterface.evalScript("app.executeMenuCommand('deselectall'); app.executeMenuCommand('exitisolation')", function() {
        document.getElementById("isolationHint").style.display = "none";
        isIsolated = false;
        updateIsolationButton();
    });
}

// ── Selection Polling ──────────────────────────────────────────────

/**
 * Poll Illustrator selection to update the anchor/path count display.
 * When a preview is active and selection changes (user shift-deselects
 * points), re-run averaging on the current selection for live feedback.
 */
function pollSelection() {
    csInterface.evalScript("sa_getSelectionInfo()", function (result) {
        if (!result || result === "EvalScript Error" || result === "undefined") {
            document.getElementById("selectionInfo").textContent = "No selection";
            return;
        }

        // Parse pipe-delimited: "anchorCount|pathCount"
        var parts = result.split("|");
        var anchorCount = parseInt(parts[0], 10) || 0;
        var pathCount = parseInt(parts[1], 10) || 0;

        if (anchorCount === 0) {
            document.getElementById("selectionInfo").textContent = "No selection";
        } else {
            document.getElementById("selectionInfo").textContent =
                anchorCount + " anchors on " + pathCount + " path" + (pathCount !== 1 ? "s" : "");
        }

        // Live re-average when preview is active and selection changes (debounced)
        if (hasPreview && result !== lastSelectionState) {
            lastSelectionState = result;
            clearTimeout(reAverageTimer);
            reAverageTimer = setTimeout(function() {
                csInterface.evalScript("sa_averageSelectedAnchors()", function (avgResult) {
                    if (avgResult && avgResult.indexOf("error") !== 0) {
                        var avgParts = avgResult.split("|");
                        updateDetected(avgParts[0], parseFloat(avgParts[1]));
                        highlightShape(avgParts[0]);
                        // Update lastSelectionState to the post-average selection
                        // so the next poll doesn't see this as a change
                        csInterface.evalScript("sa_getSelectionInfo()", function(newSel) {
                            if (newSel) lastSelectionState = newSel;
                        });
                    }
                });
            }, 300);
        }
    });
}

function startSelectionPolling() {
    if (selectionPollId) return;
    selectionPollId = setInterval(pollSelection, 500);
}

function stopSelectionPolling() {
    if (selectionPollId) {
        clearInterval(selectionPollId);
        selectionPollId = null;
    }
}

// ── Panel Visibility Lifecycle ────────────────────────────────────

csInterface.addEventListener("com.adobe.csxs.events.WindowVisibilityChanged", function(event) {
    if (event.data === "true") {
        startSelectionPolling();
    } else {
        stopSelectionPolling();
    }
});

// ── Clustering Mode ──────────────────────────────────────────────

var clusterData = null;        // cluster results from server
var selectedCluster = -1;      // currently selected cluster index

/**
 * Initiate clustering: read all extraction layers, send to MCP, display results.
 * The MCP tool adobe_ai_cluster_paths handles Python-side clustering;
 * for now we read paths and pass the JSON to sa_colorClusters in ExtendScript.
 */
function clusterLayers() {
    updateStatus("processing");

    csInterface.evalScript("sa_readLayerPaths(null)", function(pathJson) {
        if (!pathJson || pathJson.indexOf("error") === 0) {
            updateStatus("ready");
            return;
        }

        // Store pathJson for MCP bridge — the MCP tool will accept this data,
        // run Python clustering, and return cluster assignments.
        var threshold = parseInt(document.getElementById("distanceSlider").value, 10);

        var readout = document.getElementById("clusterReadout");
        readout.textContent = "Read paths. Awaiting cluster results (threshold: " + threshold + "pt)...";

        // Store path data on the Cluster tab container for MCP access
        var tabCluster = document.getElementById("tabCluster");
        tabCluster.setAttribute("data-path-json", pathJson);
        tabCluster.setAttribute("data-threshold", threshold);

        updateStatus("ready");
    });
}

/**
 * Display cluster results in the panel.
 * Called when the MCP tool returns cluster assignments as JSON.
 * Format: [{cluster_id, identity_key, path_names, color, stroke_width,
 *           dashed, confidence_tier, member_count}]
 */
function displayClusters(clusters) {
    clusterData = clusters;
    // Switch to Cluster tab so results are visible
    switchTab("Cluster");
    // Show the cluster action buttons
    var actionsSection = document.getElementById("clusterActions");
    if (actionsSection) actionsSection.style.display = "block";

    // Summary readout
    var high = 0, med = 0, low = 0, totalPaths = 0;
    for (var i = 0; i < clusters.length; i++) {
        totalPaths += clusters[i].member_count;
        if (clusters[i].confidence_tier === "high") high++;
        else if (clusters[i].confidence_tier === "medium") med++;
        else low++;
    }

    var readout = document.getElementById("clusterReadout");
    readout.textContent = clusters.length + " edge groups from " + totalPaths + " paths";
    if (high > 0 || med > 0 || low > 0) {
        readout.textContent += "\n" + high + " high, " + med + " medium, " + low + " low confidence";
    }

    // Cluster list
    var list = document.getElementById("clusterList");
    list.innerHTML = "";
    for (var c = 0; c < clusters.length; c++) {
        var cl = clusters[c];
        var row = document.createElement("div");
        row.className = "cluster-row";
        row.setAttribute("data-index", c);

        // Color swatch
        var swatch = document.createElement("span");
        swatch.className = "cluster-swatch";
        swatch.style.backgroundColor = "rgb(" + cl.color[0] + "," + cl.color[1] + "," + cl.color[2] + ")";
        row.appendChild(swatch);

        // Identity label
        var label = document.createElement("span");
        label.className = "cluster-label";
        label.textContent = (cl.identity_key || "unknown").replace(/\|/g, " / ");
        row.appendChild(label);

        // Confidence badge
        var badge = document.createElement("span");
        badge.className = "cluster-badge " + cl.confidence_tier;
        badge.textContent = cl.confidence_tier.charAt(0).toUpperCase();
        row.appendChild(badge);

        // Path count
        var count = document.createElement("span");
        count.className = "cluster-count";
        count.textContent = cl.member_count + "p";
        row.appendChild(count);

        // Click to select
        (function(index) {
            row.addEventListener("click", function() {
                selectCluster(index);
            });
        })(c);

        list.appendChild(row);
    }

    document.getElementById("btnAcceptAll").disabled = false;

    // Apply color-coding on the artboard
    // Safe escaping: JSON uses " for strings (never '), so escape \ ' \n \r for safe single-quote wrapping
    var clusterJson = JSON.stringify(clusters);
    var safeJson = clusterJson
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\n/g, '\\n')
        .replace(/\r/g, '\\r');
    csInterface.evalScript("sa_colorClusters('" + safeJson + "')", function(result) {
        if (result && result.indexOf("colored") === 0) {
            var coloredCount = result.split("|")[1];
            readout.textContent += " — " + coloredCount + " paths colored";
        }
    });
}

function selectCluster(index) {
    selectedCluster = index;
    // Highlight in list
    var rows = document.querySelectorAll(".cluster-row");
    for (var i = 0; i < rows.length; i++) {
        rows[i].classList.remove("selected");
    }
    if (rows[index]) rows[index].classList.add("selected");
}

function acceptAllClusters() {
    updateStatus("processing");
    csInterface.evalScript("sa_acceptAllClusters()", function(result) {
        if (result && result.indexOf("accepted_all") === 0) {
            var count = result.split("|")[1];
            document.getElementById("clusterReadout").textContent = "Accepted " + count + " clusters";
            document.getElementById("clusterList").innerHTML = "";
            document.getElementById("btnAcceptAll").disabled = true;
            clusterData = null;
            selectedCluster = -1;
        }
        updateStatus("ready");
    });
}

function acceptSelectedCluster() {
    if (selectedCluster < 0 || !clusterData) return;
    updateStatus("processing");
    csInterface.evalScript("sa_acceptCluster(" + selectedCluster + ")", function(result) {
        if (result && result.indexOf("accepted") === 0) {
            // Refresh display
            if (clusterData) {
                clusterData.splice(selectedCluster, 1);
                displayClusters(clusterData);
            }
            selectedCluster = -1;
        }
        updateStatus("ready");
    });
}

function rejectSelectedCluster() {
    if (selectedCluster < 0 || !clusterData) return;
    updateStatus("processing");
    csInterface.evalScript("sa_rejectCluster(" + selectedCluster + ")", function(result) {
        if (result && result.indexOf("rejected") === 0) {
            if (clusterData) {
                clusterData.splice(selectedCluster, 1);
                displayClusters(clusterData);
            }
            selectedCluster = -1;
        }
        updateStatus("ready");
    });
}

function exitClusterMode() {
    csInterface.evalScript("sa_exitClusterMode()", function() {
        document.getElementById("clusterReadout").textContent = "";
        document.getElementById("clusterList").innerHTML = "";
        document.getElementById("btnAcceptAll").disabled = true;
        var actionsSection = document.getElementById("clusterActions");
        if (actionsSection) actionsSection.style.display = "none";
        clusterData = null;
        selectedCluster = -1;
        // Switch back to Simplify tab
        switchTab("Simplify");
    });
}

// ── Select Small Paths ────────────────────────────────────────────

function selectSmallPaths() {
    var threshold = parseInt(document.getElementById("smallThreshold").value, 10) || 3;
    updateStatus("processing");
    csInterface.evalScript("sa_selectSmallPaths(" + threshold + ", 0)", function(result) {
        if (result && result.indexOf("error") !== 0) {
            var count = parseInt(result, 10) || 0;
            updateDetected("Selected " + count + " small path" + (count !== 1 ? "s" : ""), null);
        } else {
            var errMsg = result ? result.replace(/^error\|/, "") : "No paths found";
            updateDetected(errMsg, null);
        }
        updateStatus("ready");
    });
}

// ── Keyboard Shortcuts ────────────────────────────────────────────

document.addEventListener("keydown", function(e) {
    // Don't trigger when typing in inputs
    if (e.target.tagName === "INPUT" || e.target.tagName === "TEXTAREA") return;

    if (e.key === "Enter") {
        if (hasPreview) confirmPreview();
        else averageSelection();
    } else if (e.key === "Escape") {
        if (document.getElementById("isolationHint").style.display !== "none") {
            exitIsolation();
        } else {
            undoPreview();
        }
    } else if (hasPreview && e.key >= "1" && e.key <= "7") {
        var shapes = ["line", "arc", "lshape", "rectangle", "scurve", "ellipse", "freeform"];
        var idx = parseInt(e.key) - 1;
        if (idx < shapes.length) {
            highlightShape(shapes[idx]);
            reclassify(shapes[idx]);
        }
    }

    // Clustering shortcuts (only when Cluster tab is active)
    var clusterVisible = activeTab === "Cluster";
    if (clusterVisible) {
        if (e.key === "A" && e.shiftKey) {
            e.preventDefault();
            acceptAllClusters();
        } else if ((e.key === "Delete" || e.key === "Backspace") && selectedCluster >= 0) {
            rejectSelectedCluster();
        } else if (e.key === "[") {
            var distSlider = document.getElementById("distanceSlider");
            var val = parseInt(distSlider.value, 10);
            if (val > parseInt(distSlider.min, 10)) {
                distSlider.value = val - 1;
                document.getElementById("distanceValue").textContent = val - 1;
            }
        } else if (e.key === "]") {
            var distSlider2 = document.getElementById("distanceSlider");
            var val2 = parseInt(distSlider2.value, 10);
            if (val2 < parseInt(distSlider2.max, 10)) {
                distSlider2.value = val2 + 1;
                document.getElementById("distanceValue").textContent = val2 + 1;
            }
        }
    }
});

// ── Help Toggle ───────────────────────────────────────────────────

function toggleHelp() {
    var el = document.getElementById("helpText");
    el.style.display = el.style.display === "none" ? "block" : "none";
}

// ── Initialization ─────────────────────────────────────────────────

(function init() {
    initShapeButtons();
    initSliders();
    csInterface.evalScript("sa_cleanupOrphans()", function() {});
    startSelectionPolling();
    // Run an immediate poll so selection shows right away
    pollSelection();
    updateStatus("ready");
})();
