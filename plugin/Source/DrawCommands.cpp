//========================================================================================
//
//  IllTool Plugin — Draw Commands implementation
//
//  Thread-safe draw command buffer + JSON parsing.
//
//========================================================================================

#include "DrawCommands.h"
#include "vendor/json.hpp"
#include <cstdio>

using json = nlohmann::json;

//----------------------------------------------------------------------------------------
//  Globals (module-private)
//----------------------------------------------------------------------------------------

static std::mutex           gDrawMutex;
static std::vector<DrawCommand> gDrawCommands;
static std::atomic<bool>    gDirty{false};

//----------------------------------------------------------------------------------------
//  Thread-safe buffer
//----------------------------------------------------------------------------------------

void UpdateDrawCommands(std::vector<DrawCommand> commands)
{
    std::lock_guard<std::mutex> lock(gDrawMutex);
    gDrawCommands = std::move(commands);
}

std::vector<DrawCommand> GetDrawCommands()
{
    std::lock_guard<std::mutex> lock(gDrawMutex);
    return gDrawCommands;  // snapshot copy
}

size_t GetDrawCommandCount()
{
    std::lock_guard<std::mutex> lock(gDrawMutex);
    return gDrawCommands.size();
}

void SetDirty(bool dirty)
{
    gDirty.store(dirty, std::memory_order_release);
}

bool IsDirty()
{
    return gDirty.load(std::memory_order_acquire);
}

//----------------------------------------------------------------------------------------
//  JSON parsing helpers
//----------------------------------------------------------------------------------------

static DrawCommandType ParseType(const std::string& t)
{
    if (t == "line")    return DrawCommandType::Line;
    if (t == "circle")  return DrawCommandType::Circle;
    if (t == "rect")    return DrawCommandType::Rect;
    if (t == "text")    return DrawCommandType::Text;
    if (t == "polygon") return DrawCommandType::Polygon;
    return DrawCommandType::Line;  // default
}

static Color4 ParseColor(const json& j)
{
    Color4 c;
    if (j.is_array() && j.size() >= 3) {
        c.r = j[0].get<double>();
        c.g = j[1].get<double>();
        c.b = j[2].get<double>();
        c.a = (j.size() >= 4) ? j[3].get<double>() : 1.0;
    }
    return c;
}

static Point2D ParsePoint(const json& j)
{
    Point2D p;
    if (j.is_array() && j.size() >= 2) {
        p.x = j[0].get<double>();
        p.y = j[1].get<double>();
    }
    return p;
}

static std::vector<Point2D> ParsePoints(const json& j)
{
    std::vector<Point2D> pts;
    if (j.is_array()) {
        for (const auto& item : j) {
            pts.push_back(ParsePoint(item));
        }
    }
    return pts;
}

//----------------------------------------------------------------------------------------
//  ParseDrawCommands
//----------------------------------------------------------------------------------------

std::vector<DrawCommand> ParseDrawCommands(const std::string& jsonStr)
{
    std::vector<DrawCommand> result;
    try {
        json arr = json::parse(jsonStr);
        if (!arr.is_array()) {
            fprintf(stderr, "[IllTool] ParseDrawCommands: expected JSON array\n");
            return result;
        }

        for (const auto& obj : arr) {
            if (!obj.is_object()) continue;

            DrawCommand cmd;

            // type (required)
            if (obj.contains("type") && obj["type"].is_string()) {
                cmd.type = ParseType(obj["type"].get<std::string>());
            }

            // id
            if (obj.contains("id") && obj["id"].is_string()) {
                cmd.id = obj["id"].get<std::string>();
            }

            // points
            if (obj.contains("points")) {
                cmd.points = ParsePoints(obj["points"]);
            }

            // center
            if (obj.contains("center")) {
                cmd.center = ParsePoint(obj["center"]);
            }

            // radius
            if (obj.contains("radius") && obj["radius"].is_number()) {
                cmd.radius = obj["radius"].get<double>();
            }

            // strokeColor
            if (obj.contains("strokeColor")) {
                cmd.strokeColor = ParseColor(obj["strokeColor"]);
            }

            // fillColor
            if (obj.contains("fillColor")) {
                cmd.fillColor = ParseColor(obj["fillColor"]);
            }

            // strokeWidth
            if (obj.contains("strokeWidth") && obj["strokeWidth"].is_number()) {
                cmd.strokeWidth = obj["strokeWidth"].get<double>();
            }

            // filled
            if (obj.contains("filled") && obj["filled"].is_boolean()) {
                cmd.filled = obj["filled"].get<bool>();
            }

            // stroked
            if (obj.contains("stroked") && obj["stroked"].is_boolean()) {
                cmd.stroked = obj["stroked"].get<bool>();
            }

            // draggable
            if (obj.contains("draggable") && obj["draggable"].is_boolean()) {
                cmd.draggable = obj["draggable"].get<bool>();
            }

            // hitRadius
            if (obj.contains("hitRadius") && obj["hitRadius"].is_number()) {
                cmd.hitRadius = obj["hitRadius"].get<double>();
            }

            // text
            if (obj.contains("text") && obj["text"].is_string()) {
                cmd.text = obj["text"].get<std::string>();
            }

            // fontSize
            if (obj.contains("fontSize") && obj["fontSize"].is_number()) {
                cmd.fontSize = obj["fontSize"].get<double>();
            }

            result.push_back(std::move(cmd));
        }

        fprintf(stderr, "[IllTool] Parsed %zu draw commands\n", result.size());
    }
    catch (const json::exception& e) {
        fprintf(stderr, "[IllTool] ParseDrawCommands JSON error: %s\n", e.what());
    }
    return result;
}
