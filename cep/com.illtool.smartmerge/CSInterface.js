/**
 * CSInterface — Minimal stub for Adobe CEP (Common Extensibility Platform).
 *
 * This provides the core API surface used by relay-client.js:
 *   - evalScript()      — execute ExtendScript/JSX in the host app
 *   - getHostEnvironment() — identify which app this panel is running in
 *   - getSystemPath()   — resolve extension-relative paths
 *
 * IMPORTANT: Replace this file with the official CSInterface.js from
 * https://github.com/Adobe-CEP/CEP-Resources/tree/master/CEP_12.x
 * The official library provides full event support, flyout menus,
 * persistent storage, vulcan messaging, and more.
 *
 * This stub is sufficient for WebSocket relay functionality only.
 */

/* global window */

/**
 * System path type constants used by getSystemPath().
 */
var SystemPath = {
    USER_DATA: "userData",
    COMMON_FILES: "commonFiles",
    MY_DOCUMENTS: "myDocuments",
    APPLICATION: "application",
    EXTENSION: "extension",
    HOST_APPLICATION: "hostApplication"
};

/**
 * CSInterface class — bridge between CEP panel JavaScript and host app ExtendScript.
 *
 * @constructor
 */
function CSInterface() {
    // Host environment is populated by the CEP runtime when running inside
    // an Adobe app. In a stub context, we provide reasonable defaults.
    this._hostEnvironment = null;
}

/**
 * Evaluate ExtendScript code in the host application.
 *
 * This is the primary bridge between the panel's JavaScript context and the
 * host app's ExtendScript engine. The callback receives the string result
 * of the last expression evaluated.
 *
 * @param {string} code  — ExtendScript/JSX code to execute
 * @param {function} callback — called with (resultString) when execution completes
 */
CSInterface.prototype.evalScript = function (code, callback) {
    // In real CEP runtime, this delegates to the native bridge.
    // The stub checks for the native __adobe_cep__ API and falls back
    // to logging if not available (e.g. during browser testing).
    if (typeof window !== "undefined" && window.__adobe_cep__) {
        window.__adobe_cep__.evalScript(code, function (result) {
            if (typeof callback === "function") {
                callback(result);
            }
        });
    } else {
        // Outside CEP runtime — log and return error for debugging
        console.warn("[CSInterface stub] evalScript called outside CEP runtime:", code.substring(0, 100));
        if (typeof callback === "function") {
            callback("EvalScript Error: Not running inside Adobe CEP");
        }
    }
};

/**
 * Get information about the host application environment.
 *
 * Returns an object with appName, appVersion, appLocale, appId, etc.
 * In the real CSInterface, this is populated by the CEP runtime.
 *
 * @returns {object} Host environment descriptor
 */
CSInterface.prototype.getHostEnvironment = function () {
    if (this._hostEnvironment) {
        return this._hostEnvironment;
    }

    // Try to read from the native CEP API
    if (typeof window !== "undefined" && window.__adobe_cep__) {
        try {
            var envStr = window.__adobe_cep__.getHostEnvironment();
            this._hostEnvironment = (typeof envStr === "string") ? JSON.parse(envStr) : envStr;
            return this._hostEnvironment;
        } catch (e) {
            console.warn("[CSInterface] Failed to parse host environment:", e);
        }
    }

    // Fallback for non-CEP contexts (testing/debugging)
    return {
        appName: "unknown",
        appVersion: "0.0.0",
        appLocale: "en_US",
        appId: "unknown",
        appUILocale: "en_US",
        appSkinInfo: null,
        isAppOnline: true
    };
};

/**
 * Get a system path by type.
 *
 * @param {string} pathType — one of the SystemPath constants
 * @returns {string} Resolved file path
 */
CSInterface.prototype.getSystemPath = function (pathType) {
    // In real CEP, this returns actual paths from the runtime.
    if (typeof window !== "undefined" && window.__adobe_cep__) {
        return window.__adobe_cep__.getSystemPath(pathType);
    }

    // Stub paths for testing
    var paths = {};
    paths[SystemPath.USER_DATA] = "/tmp/cep-user-data";
    paths[SystemPath.EXTENSION] = "/tmp/cep-extension";
    paths[SystemPath.APPLICATION] = "/Applications";
    paths[SystemPath.COMMON_FILES] = "/Library/Application Support/Adobe";
    paths[SystemPath.MY_DOCUMENTS] = "~/Documents";
    paths[SystemPath.HOST_APPLICATION] = "/Applications";

    return paths[pathType] || "";
};

/**
 * Register a callback for a specific CEP event.
 *
 * @param {string} type — event type string
 * @param {function} listener — callback function
 * @param {object} obj — optional context object
 */
CSInterface.prototype.addEventListener = function (type, listener, obj) {
    // In real CEP, this registers with the native event system.
    if (typeof window !== "undefined" && window.__adobe_cep__) {
        window.__adobe_cep__.addEventListener(type, listener, obj);
    }
};

/**
 * Remove a previously registered event listener.
 *
 * @param {string} type — event type string
 * @param {function} listener — the callback to remove
 * @param {object} obj — optional context object
 */
CSInterface.prototype.removeEventListener = function (type, listener, obj) {
    if (typeof window !== "undefined" && window.__adobe_cep__) {
        window.__adobe_cep__.removeEventListener(type, listener, obj);
    }
};

/**
 * Close this extension panel.
 */
CSInterface.prototype.closeExtension = function () {
    if (typeof window !== "undefined" && window.__adobe_cep__) {
        window.__adobe_cep__.closeExtension();
    }
};
