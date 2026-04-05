/**
 * json_parse.cpp — Parse JSON draw command arrays into DrawCommand structs.
 *
 * Uses nlohmann/json for parsing. Each command in the array is independently
 * parsed — a malformed element is skipped without affecting others.
 */

#include "json_parse.h"
#include "json.hpp"

#include <cstdio>
#include <unordered_map>

using json = nlohmann::json;

/* -------------------------------------------------------------------------- */
/*  Type string → enum mapping                                                */
/* -------------------------------------------------------------------------- */

static const std::unordered_map<std::string, DrawCommandType> sTypeMap = {
    {"line",      DrawCommandType::Line},
    {"polyline",  DrawCommandType::Polyline},
    {"polygon",   DrawCommandType::Polygon},
    {"rect",      DrawCommandType::Rect},
    {"ellipse",   DrawCommandType::Ellipse},
    {"circle",    DrawCommandType::Circle},
    {"arc",       DrawCommandType::Arc},
    {"bezier",    DrawCommandType::Bezier},
    {"text",      DrawCommandType::Text},
    {"handle",    DrawCommandType::Handle},
    {"crosshair", DrawCommandType::Crosshair},
    {"grid",      DrawCommandType::Grid},
    {"image",     DrawCommandType::Image},
};

/* -------------------------------------------------------------------------- */
/*  Helper: parse a [x, y] array into Point2D                                 */
/* -------------------------------------------------------------------------- */

static bool ParsePoint(const json& j, Point2D& out)
{
    if (!j.is_array() || j.size() < 2) return false;
    if (!j[0].is_number() || !j[1].is_number()) return false;
    out.x = j[0].get<double>();
    out.y = j[1].get<double>();
    return true;
}

/* -------------------------------------------------------------------------- */
/*  Helper: parse a [r, g, b, a] array into Color                             */
/* -------------------------------------------------------------------------- */

static bool ParseColor(const json& j, Color& out)
{
    if (!j.is_array() || j.size() < 3) return false;
    for (size_t i = 0; i < std::min(j.size(), (size_t)4); ++i) {
        if (!j[i].is_number()) return false;
    }
    out.r = j[0].get<double>();
    out.g = j[1].get<double>();
    out.b = j[2].get<double>();
    out.a = (j.size() >= 4) ? j[3].get<double>() : 1.0;
    return true;
}

/* -------------------------------------------------------------------------- */
/*  Helper: parse a single BezierSegment from a JSON object                    */
/* -------------------------------------------------------------------------- */

static bool ParseBezierSegment(const json& j, BezierSegment& out)
{
    if (!j.is_object()) return false;

    /* Each control point is a [x, y] array keyed as p0, p1, p2, p3 */
    if (!j.contains("p0") || !ParsePoint(j["p0"], out.p0)) return false;
    if (!j.contains("p1") || !ParsePoint(j["p1"], out.p1)) return false;
    if (!j.contains("p2") || !ParsePoint(j["p2"], out.p2)) return false;
    if (!j.contains("p3") || !ParsePoint(j["p3"], out.p3)) return false;

    return true;
}

/* -------------------------------------------------------------------------- */
/*  Helper: safe JSON value extraction with defaults                           */
/* -------------------------------------------------------------------------- */

template<typename T>
static T SafeGet(const json& j, const char* key, T defaultVal)
{
    if (j.contains(key) && !j[key].is_null()) {
        try {
            return j[key].get<T>();
        } catch (...) {
            /* type mismatch — use default */
        }
    }
    return defaultVal;
}

/* -------------------------------------------------------------------------- */
/*  Parse a single draw command object                                         */
/* -------------------------------------------------------------------------- */

static bool ParseSingleCommand(const json& j, DrawCommand& cmd)
{
    if (!j.is_object()) {
        fprintf(stderr, "[IllTool] json_parse: skipping non-object element.\n");
        return false;
    }

    /* Type is required */
    if (!j.contains("type") || !j["type"].is_string()) {
        fprintf(stderr, "[IllTool] json_parse: command missing 'type' field.\n");
        return false;
    }

    std::string typeStr = j["type"].get<std::string>();
    auto it = sTypeMap.find(typeStr);
    if (it == sTypeMap.end()) {
        fprintf(stderr, "[IllTool] json_parse: unknown command type '%s'.\n", typeStr.c_str());
        cmd.type = DrawCommandType::Unknown;
    } else {
        cmd.type = it->second;
    }

    /* ID */
    cmd.id = SafeGet<std::string>(j, "id", "");

    /* Points array: [[x,y], [x,y], ...] */
    if (j.contains("points") && j["points"].is_array()) {
        for (const auto& pt : j["points"]) {
            Point2D p;
            if (ParsePoint(pt, p)) {
                cmd.points.push_back(p);
            }
        }
    }

    /* Bezier segments: [{p0:[],p1:[],p2:[],p3:[]}, ...] */
    if (j.contains("segments") && j["segments"].is_array()) {
        for (const auto& seg : j["segments"]) {
            BezierSegment bs;
            if (ParseBezierSegment(seg, bs)) {
                cmd.segments.push_back(bs);
            }
        }
    }

    /* Center point */
    if (j.contains("center")) {
        ParsePoint(j["center"], cmd.center);
    }

    /* Scalar geometry */
    cmd.radius = SafeGet<double>(j, "radius", 0.0);
    cmd.width  = SafeGet<double>(j, "width",  0.0);
    cmd.height = SafeGet<double>(j, "height", 0.0);
    cmd.angle  = SafeGet<double>(j, "angle",  0.0);

    /* Text */
    cmd.text     = SafeGet<std::string>(j, "text", "");
    cmd.fontSize = SafeGet<double>(j, "fontSize", 12.0);

    /* Style — colors */
    if (j.contains("strokeColor")) {
        ParseColor(j["strokeColor"], cmd.strokeColor);
    }
    if (j.contains("fillColor")) {
        ParseColor(j["fillColor"], cmd.fillColor);
    }

    /* Style — scalars */
    cmd.strokeWidth = SafeGet<double>(j, "strokeWidth", 1.0);
    cmd.opacity     = SafeGet<double>(j, "opacity",     1.0);
    cmd.filled      = SafeGet<bool>(j, "filled",  false);
    cmd.stroked     = SafeGet<bool>(j, "stroked", true);

    /* Interaction */
    cmd.draggable = SafeGet<bool>(j, "draggable", false);
    cmd.viewSpace = SafeGet<bool>(j, "viewSpace", true);
    cmd.hitRadius = SafeGet<double>(j, "hitRadius", 5.0);

    return true;
}

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

std::vector<DrawCommand> ParseDrawCommands(const std::string& jsonStr)
{
    std::vector<DrawCommand> result;

    json root;
    try {
        root = json::parse(jsonStr);
    } catch (const json::parse_error& e) {
        fprintf(stderr, "[IllTool] json_parse: JSON parse error: %s\n", e.what());
        return result;
    }

    /* Accept both a single object and an array of objects */
    if (root.is_object()) {
        DrawCommand cmd;
        if (ParseSingleCommand(root, cmd)) {
            result.push_back(std::move(cmd));
        }
    } else if (root.is_array()) {
        result.reserve(root.size());
        for (size_t i = 0; i < root.size(); ++i) {
            DrawCommand cmd;
            if (ParseSingleCommand(root[i], cmd)) {
                result.push_back(std::move(cmd));
            } else {
                fprintf(stderr, "[IllTool] json_parse: skipping malformed command at index %zu.\n", i);
            }
        }
    } else {
        fprintf(stderr, "[IllTool] json_parse: expected JSON array or object, got %s.\n",
                root.type_name());
    }

    fprintf(stderr, "[IllTool] json_parse: parsed %zu draw commands.\n", result.size());
    return result;
}
