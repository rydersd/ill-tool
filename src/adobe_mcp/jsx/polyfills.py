"""JSON polyfill for Adobe Illustrator's ExtendScript ES3 engine.

Illustrator's ExtendScript lacks native JSON.stringify() and JSON.parse().
This polyfill is auto-prepended to all Illustrator JSX by engine._prepare_jsx(),
so every Illustrator tool can freely use JSON without manual string concatenation.
"""

JSON_POLYFILL = r"""
// JSON polyfill for ExtendScript ES3 (Illustrator)
if (typeof JSON === "undefined") {
    JSON = {};
    JSON.stringify = function(obj, replacer, space) {
        var t = typeof obj;
        if (t === "undefined" || obj === null) return "null";
        if (t === "number" || t === "boolean") return String(obj);
        if (t === "string") return '"' + obj.replace(/\\/g, '\\\\').replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r').replace(/\t/g, '\\t') + '"';
        if (obj instanceof Array) {
            var arr = [];
            for (var i = 0; i < obj.length; i++) {
                arr.push(JSON.stringify(obj[i], replacer, space));
            }
            return "[" + arr.join(",") + "]";
        }
        if (t === "object") {
            var parts = [];
            for (var k in obj) {
                if (obj.hasOwnProperty(k)) {
                    parts.push('"' + k + '":' + JSON.stringify(obj[k], replacer, space));
                }
            }
            return "{" + parts.join(",") + "}";
        }
        return "null";
    };
    // Safe recursive-descent JSON parser — NO eval().
    JSON.parse = (function() {
        var pos, str;
        function err(m) { throw new Error("JSON parse error at " + pos + ": " + m); }
        function ws() { while (pos < str.length && " \t\n\r".indexOf(str.charAt(pos)) >= 0) pos++; }
        function pk() { ws(); return pos < str.length ? str.charAt(pos) : ""; }
        function nx() { ws(); return pos < str.length ? str.charAt(pos++) : ""; }
        function pVal() {
            ws(); var ch = pk();
            if (ch === '"') return pStr();
            if (ch === '{') return pObj();
            if (ch === '[') return pArr();
            if (ch === 't' || ch === 'f') return pBool();
            if (ch === 'n') return pNull();
            if (ch === '-' || (ch >= '0' && ch <= '9')) return pNum();
            err("unexpected: " + ch);
        }
        function pStr() {
            if (nx() !== '"') err("expected '\"'");
            var r = "";
            while (pos < str.length) {
                var c = str.charAt(pos++);
                if (c === '"') return r;
                if (c === '\\') {
                    var e = str.charAt(pos++);
                    if (e === '"') r += '"'; else if (e === '\\') r += '\\';
                    else if (e === '/') r += '/'; else if (e === 'n') r += '\n';
                    else if (e === 'r') r += '\r'; else if (e === 't') r += '\t';
                    else if (e === 'b') r += '\b'; else if (e === 'f') r += '\f';
                    else if (e === 'u') { var h = str.substr(pos, 4); pos += 4; r += String.fromCharCode(parseInt(h, 16)); }
                    else r += e;
                } else r += c;
            }
            err("unterminated string");
        }
        function pNum() {
            var st = pos;
            if (str.charAt(pos) === '-') pos++;
            while (pos < str.length && str.charAt(pos) >= '0' && str.charAt(pos) <= '9') pos++;
            if (pos < str.length && str.charAt(pos) === '.') { pos++; while (pos < str.length && str.charAt(pos) >= '0' && str.charAt(pos) <= '9') pos++; }
            if (pos < str.length && (str.charAt(pos) === 'e' || str.charAt(pos) === 'E')) { pos++; if (pos < str.length && (str.charAt(pos) === '+' || str.charAt(pos) === '-')) pos++; while (pos < str.length && str.charAt(pos) >= '0' && str.charAt(pos) <= '9') pos++; }
            return parseFloat(str.substring(st, pos));
        }
        function pBool() { if (str.substr(pos, 4) === "true") { pos += 4; return true; } if (str.substr(pos, 5) === "false") { pos += 5; return false; } err("expected bool"); }
        function pNull() { if (str.substr(pos, 4) === "null") { pos += 4; return null; } err("expected null"); }
        function pArr() { pos++; var a = []; ws(); if (pk() === ']') { pos++; return a; } while (true) { a.push(pVal()); ws(); var c = nx(); if (c === ']') return a; if (c !== ',') err("expected ',' or ']'"); } }
        function pObj() { pos++; var o = {}; ws(); if (pk() === '}') { pos++; return o; } while (true) { var k = pStr(); ws(); if (nx() !== ':') err("expected ':'"); o[k] = pVal(); ws(); var c = nx(); if (c === '}') return o; if (c !== ',') err("expected ',' or '}'"); } }
        return function(s) { pos = 0; str = s; try { return pVal(); } catch(e) { return null; } };
    })();
}
""".strip()
