/**
 * json_es3.jsx — Minimal JSON serializer/parser for ExtendScript (ES3).
 *
 * Handles: strings, numbers, booleans, null, arrays, flat objects.
 * Does NOT handle: nested objects deeper than 2 levels, Date objects,
 * undefined, functions, circular references.
 *
 * Used by: logging.jsx (serialization), Smart Merge host.jsx (parsing).
 */

/**
 * Serialize a value to JSON string.
 * Handles strings, numbers, booleans, null, arrays, and flat objects.
 */
function jsonStringify(value) {
    if (value === null) return "null";
    if (value === undefined) return "null";

    var type = typeof value;

    if (type === "number") {
        if (isNaN(value) || !isFinite(value)) return "null";
        return String(value);
    }
    if (type === "boolean") return value ? "true" : "false";
    if (type === "string") return _jsonEscapeString(value);

    // Array
    if (value instanceof Array) {
        var items = [];
        for (var i = 0; i < value.length; i++) {
            items.push(jsonStringify(value[i]));
        }
        return "[" + items.join(",") + "]";
    }

    // Object
    if (type === "object") {
        var pairs = [];
        for (var key in value) {
            if (value.hasOwnProperty(key)) {
                pairs.push(_jsonEscapeString(key) + ":" + jsonStringify(value[key]));
            }
        }
        return "{" + pairs.join(",") + "}";
    }

    return "null";
}

function _jsonEscapeString(s) {
    var result = '"';
    for (var i = 0; i < s.length; i++) {
        var ch = s.charAt(i);
        if (ch === '"') result += '\\"';
        else if (ch === '\\') result += '\\\\';
        else if (ch === '\n') result += '\\n';
        else if (ch === '\r') result += '\\r';
        else if (ch === '\t') result += '\\t';
        else result += ch;
    }
    return result + '"';
}

/**
 * Parse a JSON string into a value.
 * Uses eval — safe when input is from our own sidecar files.
 */
function jsonParse(str) {
    try {
        return eval("(" + str + ")");
    } catch (e) {
        return null;
    }
}
