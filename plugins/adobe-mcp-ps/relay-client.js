/**
 * RelayClient — WebSocket bridge between Adobe CEP panels and the MCP relay server.
 *
 * Connects to the Python MCP relay server via WebSocket, sends periodic heartbeats,
 * receives EXECUTE messages (JSX code), runs them through CSInterface.evalScript(),
 * and sends RESULT messages back.
 *
 * Usage (in panel's index.html):
 *   <script src="../shared/js/CSInterface.js"></script>
 *   <script src="../shared/js/relay-client.js"></script>
 *   <script>RelayClient.init('photoshop');</script>
 */

/* global CSInterface */

var RelayClient = (function () {
    "use strict";

    // ── Configuration ────────────────────────────────────────────────

    var DEFAULT_PORT = 8765;
    var HEARTBEAT_INTERVAL_MS = 5000;       // 5 seconds between heartbeats
    var RECONNECT_BASE_MS = 1000;            // initial reconnect delay
    var RECONNECT_MAX_MS = 30000;            // max reconnect delay (30s)
    var MAX_CACHED_OPERATIONS = 50;          // localStorage cache limit
    var MAX_LOG_ENTRIES = 10;                 // visible log entries in panel UI
    var CACHE_STORAGE_KEY = "adobemcp_cache";

    // ── State ────────────────────────────────────────────────────────

    var _appName = "";
    var _port = DEFAULT_PORT;
    var _ws = null;
    var _csInterface = null;
    var _heartbeatTimer = null;
    var _reconnectTimer = null;
    var _reconnectDelay = RECONNECT_BASE_MS;
    var _connected = false;
    var _executing = false;
    var _operationLog = [];                  // in-memory log for UI display

    // ── Public API ───────────────────────────────────────────────────

    /**
     * Initialize the relay client. Call once when the panel loads.
     *
     * @param {string} appName  — Adobe app identifier (e.g. "photoshop", "illustrator", "aftereffects")
     * @param {number} [port]   — WebSocket port (default: 8765)
     */
    function init(appName, port) {
        _appName = appName || "unknown";
        _port = port || DEFAULT_PORT;
        _csInterface = new CSInterface();

        _log("Initializing relay client for " + _appName + " on port " + _port);
        _updateStatus("disconnected");

        // Load cached operations from localStorage
        _loadCache();

        // Start connection
        _connect();
    }

    /**
     * Disconnect from the relay server. Stops heartbeat and reconnect timers.
     */
    function disconnect() {
        _stopHeartbeat();
        _stopReconnect();

        if (_ws) {
            _ws.onclose = null; // prevent reconnect on intentional close
            _ws.close();
            _ws = null;
        }

        _connected = false;
        _updateStatus("disconnected");
        _log("Disconnected intentionally");
    }

    /**
     * Check if currently connected to the relay server.
     *
     * @returns {boolean}
     */
    function isConnected() {
        return _connected && _ws && _ws.readyState === WebSocket.OPEN;
    }

    /**
     * Get the current operation log (most recent first).
     *
     * @returns {Array} Array of {timestamp, action, detail, success} objects
     */
    function getLog() {
        return _operationLog.slice();
    }

    // ── WebSocket Connection ─────────────────────────────────────────

    /**
     * Establish a WebSocket connection to the relay server.
     * On success, resets reconnect delay and starts heartbeat.
     * On failure, schedules reconnect with exponential backoff.
     */
    function _connect() {
        if (_ws && (_ws.readyState === WebSocket.CONNECTING || _ws.readyState === WebSocket.OPEN)) {
            return; // already connecting or connected
        }

        var url = "ws://localhost:" + _port;
        _log("Connecting to " + url + "...");
        _updateStatus("connecting");

        try {
            _ws = new WebSocket(url);
        } catch (e) {
            _log("WebSocket creation failed: " + e.message);
            _scheduleReconnect();
            return;
        }

        _ws.onopen = function () {
            _connected = true;
            _reconnectDelay = RECONNECT_BASE_MS; // reset backoff on successful connect
            _updateStatus("connected");
            _log("Connected to relay server");

            // Send initial heartbeat immediately to identify ourselves
            _sendHeartbeat();

            // Start periodic heartbeat
            _startHeartbeat();
        };

        _ws.onmessage = function (event) {
            _handleMessage(event.data);
        };

        _ws.onclose = function (event) {
            _connected = false;
            _stopHeartbeat();
            _updateStatus("disconnected");

            var reason = event.reason || "connection closed";
            _log("Connection closed: " + reason + " (code " + event.code + ")");

            // Reconnect unless intentionally closed
            _scheduleReconnect();
        };

        _ws.onerror = function () {
            // The error event has no useful information in browsers.
            // The subsequent onclose will handle reconnection.
            _log("WebSocket error occurred");
        };
    }

    // ── Message Handling ─────────────────────────────────────────────

    /**
     * Process an incoming message from the relay server.
     * Handles EXECUTE (run JSX), WELCOME (confirmation), and ERROR messages.
     *
     * @param {string} rawData — raw WebSocket message payload
     */
    function _handleMessage(rawData) {
        var msg;
        try {
            msg = JSON.parse(rawData);
        } catch (e) {
            _log("Received non-JSON message, ignoring");
            return;
        }

        if (!msg || !msg.type) {
            _log("Received message without type field, ignoring");
            return;
        }

        switch (msg.type) {
            case "execute":
                _handleExecute(msg);
                break;

            case "welcome":
                _log("Server acknowledged: " + (msg.message || "connected"));
                break;

            case "error":
                _log("Server error: " + (msg.error || "unknown"));
                break;

            default:
                _log("Unknown message type: " + msg.type);
        }
    }

    /**
     * Handle an EXECUTE message — run JSX code through CSInterface.evalScript().
     *
     * Sends back a RESULT message with the output, or an ERROR message on failure.
     *
     * @param {object} msg — parsed EXECUTE message with {id, jsx} fields
     */
    function _handleExecute(msg) {
        if (!msg.jsx || !msg.id) {
            _log("Invalid EXECUTE message: missing jsx or id");
            _sendError(msg.id || "unknown", "Invalid EXECUTE message: missing jsx or id");
            return;
        }

        _executing = true;
        _updateStatus("executing");

        var msgId = msg.id;
        var jsxCode = msg.jsx;
        var startTime = Date.now();

        _log("Executing JSX (" + jsxCode.length + " chars)...");

        try {
            _csInterface.evalScript(jsxCode, function (result) {
                var elapsed = Date.now() - startTime;
                _executing = false;
                _updateStatus("connected");

                // Check for EvalScript errors — CEP returns "EvalScript error."
                // for syntax errors and runtime exceptions
                var isError = (typeof result === "string") &&
                    (result.indexOf("EvalScript error") === 0 ||
                     result.indexOf("Error:") === 0 ||
                     result === "undefined");

                if (isError && result !== "undefined") {
                    _log("JSX error (" + elapsed + "ms): " + result.substring(0, 100));
                    _sendResult(msgId, false, "", result);
                    _cacheOperation(jsxCode, result, false, elapsed);
                } else {
                    // "undefined" is a valid result for void-returning scripts
                    var stdout = (result === "undefined") ? "" : result;
                    _log("JSX completed (" + elapsed + "ms): " + (stdout || "(no output)").substring(0, 80));
                    _sendResult(msgId, true, stdout, "");
                    _cacheOperation(jsxCode, stdout, true, elapsed);
                }
            });
        } catch (e) {
            var elapsed = Date.now() - startTime;
            _executing = false;
            _updateStatus("connected");

            var errorMsg = "evalScript exception: " + (e.message || String(e));
            _log("JSX exception (" + elapsed + "ms): " + errorMsg);
            _sendError(msgId, errorMsg);
            _cacheOperation(jsxCode, errorMsg, false, elapsed);
        }
    }

    // ── Message Sending ──────────────────────────────────────────────

    /**
     * Send a HEARTBEAT message to identify this panel and keep the connection alive.
     */
    function _sendHeartbeat() {
        _send({
            type: "heartbeat",
            id: _generateId(),
            app: _appName,
            timestamp: Date.now()
        });
    }

    /**
     * Send a RESULT message in response to an EXECUTE.
     *
     * @param {string} msgId    — correlation ID from the EXECUTE message
     * @param {boolean} success — whether execution succeeded
     * @param {string} stdout   — script output
     * @param {string} stderr   — error output
     */
    function _sendResult(msgId, success, stdout, stderr) {
        _send({
            type: "result",
            id: msgId,
            success: success,
            stdout: stdout || "",
            stderr: stderr || ""
        });
    }

    /**
     * Send an ERROR message for a failed EXECUTE.
     *
     * @param {string} msgId — correlation ID from the EXECUTE message
     * @param {string} error — human-readable error description
     */
    function _sendError(msgId, error) {
        _send({
            type: "error",
            id: msgId,
            error: error
        });
    }

    /**
     * Send a JSON message over the WebSocket. Silently drops if not connected.
     *
     * @param {object} msg — message object to serialize and send
     */
    function _send(msg) {
        if (!_ws || _ws.readyState !== WebSocket.OPEN) {
            return;
        }
        try {
            _ws.send(JSON.stringify(msg));
        } catch (e) {
            _log("Send failed: " + e.message);
        }
    }

    // ── Heartbeat Management ─────────────────────────────────────────

    function _startHeartbeat() {
        _stopHeartbeat();
        _heartbeatTimer = setInterval(_sendHeartbeat, HEARTBEAT_INTERVAL_MS);
    }

    function _stopHeartbeat() {
        if (_heartbeatTimer) {
            clearInterval(_heartbeatTimer);
            _heartbeatTimer = null;
        }
    }

    // ── Reconnect with Exponential Backoff ───────────────────────────

    function _scheduleReconnect() {
        _stopReconnect();

        _log("Reconnecting in " + (_reconnectDelay / 1000).toFixed(1) + "s...");
        _reconnectTimer = setTimeout(function () {
            _reconnectTimer = null;
            _connect();
        }, _reconnectDelay);

        // Exponential backoff: double the delay, cap at max
        _reconnectDelay = Math.min(_reconnectDelay * 2, RECONNECT_MAX_MS);
    }

    function _stopReconnect() {
        if (_reconnectTimer) {
            clearTimeout(_reconnectTimer);
            _reconnectTimer = null;
        }
    }

    // ── Operation Cache (localStorage) ───────────────────────────────

    /**
     * Cache an operation result in localStorage for persistence across panel reloads.
     * Keeps the most recent MAX_CACHED_OPERATIONS entries.
     *
     * @param {string} jsx     — JSX code that was executed
     * @param {string} result  — execution result or error
     * @param {boolean} success — whether it succeeded
     * @param {number} elapsed — execution time in ms
     */
    function _cacheOperation(jsx, result, success, elapsed) {
        var cache = _getCache();

        cache.push({
            ts: Date.now(),
            app: _appName,
            jsx_preview: jsx.substring(0, 200),
            result_preview: (result || "").substring(0, 200),
            success: success,
            elapsed_ms: elapsed
        });

        // Trim to max size
        while (cache.length > MAX_CACHED_OPERATIONS) {
            cache.shift();
        }

        _saveCache(cache);
    }

    function _getCache() {
        try {
            var raw = localStorage.getItem(CACHE_STORAGE_KEY);
            if (raw) {
                return JSON.parse(raw);
            }
        } catch (e) {
            // localStorage may be unavailable or corrupted
        }
        return [];
    }

    function _saveCache(cache) {
        try {
            localStorage.setItem(CACHE_STORAGE_KEY, JSON.stringify(cache));
        } catch (e) {
            // localStorage may be full or unavailable
        }
    }

    function _loadCache() {
        var cache = _getCache();
        if (cache.length > 0) {
            _log("Loaded " + cache.length + " cached operations from previous session");
        }
    }

    // ── UI Status Updates ────────────────────────────────────────────

    /**
     * Update the panel UI status indicator. Looks for elements with specific IDs:
     *   - #relay-status       — text content showing connection state
     *   - #relay-status-dot   — CSS class updated (connected/disconnected/executing/connecting)
     *   - #last-operation     — text of the most recent log entry
     *   - #operation-log      — scrollable list of recent operations
     *
     * @param {string} status — "connected", "disconnected", "executing", "connecting"
     */
    function _updateStatus(status) {
        var statusEl = document.getElementById("relay-status");
        if (statusEl) {
            var labels = {
                connected: "MCP Relay: connected",
                disconnected: "MCP Relay: disconnected",
                executing: "MCP Relay: executing\u2026",
                connecting: "MCP Relay: connecting\u2026"
            };
            statusEl.textContent = labels[status] || ("MCP Relay: " + status);
            statusEl.className = "status " + status;
        }

        var dotEl = document.getElementById("relay-status-dot");
        if (dotEl) {
            dotEl.className = "status-dot " + status;
        }
    }

    /**
     * Add an entry to the in-memory log and update the panel UI.
     *
     * @param {string} message — log message text
     */
    function _log(message) {
        var entry = {
            timestamp: new Date().toLocaleTimeString(),
            message: message
        };

        _operationLog.push(entry);

        // Trim log to max display size
        while (_operationLog.length > MAX_LOG_ENTRIES * 2) {
            _operationLog.shift();
        }

        // Update last-operation element
        var lastOpEl = document.getElementById("last-operation");
        if (lastOpEl) {
            lastOpEl.textContent = message;
        }

        // Update operation log list
        var logEl = document.getElementById("operation-log");
        if (logEl) {
            var recent = _operationLog.slice(-MAX_LOG_ENTRIES);
            var html = "";
            for (var i = 0; i < recent.length; i++) {
                html += '<div class="log-entry">' +
                    '<span class="log-time">' + recent[i].timestamp + '</span> ' +
                    '<span class="log-msg">' + _escapeHtml(recent[i].message) + '</span>' +
                    '</div>';
            }
            logEl.innerHTML = html;
            // Auto-scroll to bottom
            logEl.scrollTop = logEl.scrollHeight;
        }

        // Also log to console for DevTools debugging
        console.log("[RelayClient:" + _appName + "] " + message);
    }

    // ── Utilities ────────────────────────────────────────────────────

    /**
     * Generate a unique message ID (simplified UUID v4).
     * @returns {string}
     */
    function _generateId() {
        var hex = "0123456789abcdef";
        var id = "";
        for (var i = 0; i < 32; i++) {
            id += hex.charAt(Math.floor(Math.random() * 16));
        }
        return id;
    }

    /**
     * Escape HTML entities to prevent XSS in log display.
     * @param {string} str
     * @returns {string}
     */
    function _escapeHtml(str) {
        var div = document.createElement("div");
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // ── Public Interface ─────────────────────────────────────────────

    return {
        init: init,
        disconnect: disconnect,
        isConnected: isConnected,
        getLog: getLog
    };

})();
