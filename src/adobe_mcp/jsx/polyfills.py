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
    JSON.parse = function(s) {
        return eval("(" + s + ")");
    };
}
""".strip()
