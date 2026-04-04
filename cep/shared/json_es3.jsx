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
        var code = s.charCodeAt(i);
        if (ch === '"') result += '\\"';
        else if (ch === '\\') result += '\\\\';
        else if (ch === '\n') result += '\\n';
        else if (ch === '\r') result += '\\r';
        else if (ch === '\t') result += '\\t';
        else if (ch === '\b') result += '\\b';
        else if (ch === '\f') result += '\\f';
        else if (code < 0x20) {
            // Other control characters: use \uXXXX
            var hex = code.toString(16);
            while (hex.length < 4) hex = "0" + hex;
            result += '\\u' + hex;
        }
        else result += ch;
    }
    return result + '"';
}

/**
 * Safe recursive-descent JSON parser for ES3.
 * Does NOT use eval(). Handles strings, numbers, booleans, null, arrays, objects.
 */
function jsonParse(str) {
    var pos = 0;

    function _error(msg) { throw new Error("JSON parse error at " + pos + ": " + msg); }
    function _skipWS() { while (pos < str.length && " \t\n\r".indexOf(str.charAt(pos)) >= 0) pos++; }
    function _peek() { _skipWS(); return pos < str.length ? str.charAt(pos) : ""; }
    function _next() { _skipWS(); return pos < str.length ? str.charAt(pos++) : ""; }

    function _parseValue() {
        _skipWS();
        var ch = _peek();
        if (ch === '"') return _parseString();
        if (ch === '{') return _parseObject();
        if (ch === '[') return _parseArray();
        if (ch === 't' || ch === 'f') return _parseBool();
        if (ch === 'n') return _parseNull();
        if (ch === '-' || (ch >= '0' && ch <= '9')) return _parseNumber();
        _error("unexpected char: " + ch);
    }

    function _parseString() {
        if (_next() !== '"') _error("expected '\"'");
        var result = "";
        while (pos < str.length) {
            var ch = str.charAt(pos++);
            if (ch === '"') return result;
            if (ch === '\\') {
                var esc = str.charAt(pos++);
                if (esc === '"') result += '"';
                else if (esc === '\\') result += '\\';
                else if (esc === '/') result += '/';
                else if (esc === 'n') result += '\n';
                else if (esc === 'r') result += '\r';
                else if (esc === 't') result += '\t';
                else if (esc === 'b') result += '\b';
                else if (esc === 'f') result += '\f';
                else if (esc === 'u') {
                    var hex = str.substr(pos, 4); pos += 4;
                    result += String.fromCharCode(parseInt(hex, 16));
                }
                else result += esc;
            } else {
                result += ch;
            }
        }
        _error("unterminated string");
    }

    function _parseNumber() {
        var start = pos;
        if (str.charAt(pos) === '-') pos++;
        while (pos < str.length && str.charAt(pos) >= '0' && str.charAt(pos) <= '9') pos++;
        if (pos < str.length && str.charAt(pos) === '.') {
            pos++;
            while (pos < str.length && str.charAt(pos) >= '0' && str.charAt(pos) <= '9') pos++;
        }
        if (pos < str.length && (str.charAt(pos) === 'e' || str.charAt(pos) === 'E')) {
            pos++;
            if (pos < str.length && (str.charAt(pos) === '+' || str.charAt(pos) === '-')) pos++;
            while (pos < str.length && str.charAt(pos) >= '0' && str.charAt(pos) <= '9') pos++;
        }
        return parseFloat(str.substring(start, pos));
    }

    function _parseBool() {
        if (str.substr(pos, 4) === "true") { pos += 4; return true; }
        if (str.substr(pos, 5) === "false") { pos += 5; return false; }
        _error("expected boolean");
    }

    function _parseNull() {
        if (str.substr(pos, 4) === "null") { pos += 4; return null; }
        _error("expected null");
    }

    function _parseArray() {
        pos++; // skip '['
        var arr = [];
        _skipWS();
        if (_peek() === ']') { pos++; return arr; }
        while (true) {
            arr.push(_parseValue());
            _skipWS();
            var ch = _next();
            if (ch === ']') return arr;
            if (ch !== ',') _error("expected ',' or ']'");
        }
    }

    function _parseObject() {
        pos++; // skip '{'
        var obj = {};
        _skipWS();
        if (_peek() === '}') { pos++; return obj; }
        while (true) {
            var key = _parseString();
            _skipWS();
            if (_next() !== ':') _error("expected ':'");
            obj[key] = _parseValue();
            _skipWS();
            var ch = _next();
            if (ch === '}') return obj;
            if (ch !== ',') _error("expected ',' or '}'");
        }
    }

    try {
        var result = _parseValue();
        return result;
    } catch (e) {
        return null;
    }
}
