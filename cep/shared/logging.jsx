/**
 * logging.jsx — Interaction logging for CEP panels (ES3).
 *
 * Requires: json_es3.jsx (must be #included first)
 *
 * Logs panel interactions as JSONL (one JSON object per line) to
 * ~/Library/Application Support/illtool/interactions/{panelName}_{YYYYMMDD}.jsonl
 *
 * Persistent storage in app data — survives reboots, accumulates over time.
 * Used by all 3 panels: Shape Cleanup, Grouping Tools, Smart Merge.
 */

/**
 * Log an interaction event to the JSONL file.
 *
 * @param {string} panelName - e.g. "shapeaverager", "pathrefine", "smartmerge"
 * @param {string} actionType - e.g. "reclassify", "confirm", "merge", "simplify"
 * @param {Object} beforeState - state before action (shape, confidence, etc.)
 * @param {Object} afterState - state after action
 * @param {Object} context - additional context (inputAnchors, bboxAngle, etc.)
 */
function logInteraction(panelName, actionType, beforeState, afterState, context) {
    try {
        // Sanitize panelName to prevent path traversal in log filenames
        panelName = panelName.replace(/[^a-zA-Z0-9_-]/g, "_");

        var now = new Date();
        var ts = now.getFullYear() + "-" +
            _pad2(now.getMonth() + 1) + "-" +
            _pad2(now.getDate()) + "T" +
            _pad2(now.getHours()) + ":" +
            _pad2(now.getMinutes()) + ":" +
            _pad2(now.getSeconds());

        var dateStr = now.getFullYear() +
            _pad2(now.getMonth() + 1) +
            _pad2(now.getDate());

        var entry = {
            timestamp: ts,
            panel: panelName,
            action: actionType,
            before: beforeState || null,
            after: afterState || null,
            context: context || null
        };

        var line = jsonStringify(entry);

        // Ensure directory exists — persistent app data location
        var appData = Folder("~/Library/Application Support/illtool/interactions");
        if (!appData.exists) appData.create();

        // Append to JSONL file
        var filePath = appData.fsName + "/" + panelName + "_" + dateStr + ".jsonl";
        var f = new File(filePath);
        if (!f.open("a")) return;  // silently fail if can't open
        f.writeln(line);
        f.close();
    } catch (e) {
        // Logging should never break the panel
    }
}

function _pad2(n) {
    return n < 10 ? "0" + n : "" + n;
}
