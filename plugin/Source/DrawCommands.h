//========================================================================================
//
//  IllTool Plugin — Draw Commands
//
//  Thread-safe draw command buffer for annotator rendering.
//  Receives draw commands from HTTP bridge, stores them for
//  the annotator to render on the next paint cycle.
//
//========================================================================================

#ifndef __DRAWCOMMANDS_H__
#define __DRAWCOMMANDS_H__

#include <string>
#include <vector>
#include <mutex>
#include <atomic>

//----------------------------------------------------------------------------------------
//  Types
//----------------------------------------------------------------------------------------

/** 2D point used in draw commands (document coordinates, floating-point). */
struct Point2D {
    double x = 0.0;
    double y = 0.0;
};

/** RGBA color with components in [0,1]. */
struct Color4 {
    double r = 0.0;
    double g = 0.0;
    double b = 0.0;
    double a = 1.0;
};

/** Types of draw commands the annotator can render. */
enum class DrawCommandType {
    Line,
    Circle,
    Rect,
    Text,
    Polygon
};

/** A single draw command describing a shape to render as an annotation overlay. */
struct DrawCommand {
    DrawCommandType     type        = DrawCommandType::Line;
    std::string         id;

    // Geometry
    std::vector<Point2D> points;    // Line: 2 points, Polygon: N points
    Point2D             center;     // Circle center
    double              radius      = 0.0;

    // Appearance
    Color4              strokeColor = {1.0, 1.0, 1.0, 1.0};
    Color4              fillColor   = {0.0, 0.0, 0.0, 0.0};
    double              strokeWidth = 1.0;
    bool                filled      = false;
    bool                stroked     = true;
    bool                dashed      = false;

    // Rect geometry (for Rect type)
    double              width       = 0.0;
    double              height      = 0.0;

    // Interaction
    bool                draggable   = false;
    double              hitRadius   = 5.0;

    // Text
    std::string         text;
    double              fontSize    = 12.0;
};

//----------------------------------------------------------------------------------------
//  Thread-safe buffer
//----------------------------------------------------------------------------------------

/** Replace all draw commands atomically.  Thread-safe. */
void UpdateDrawCommands(std::vector<DrawCommand> commands);

/** Get a snapshot copy of the current draw commands.  Thread-safe. */
std::vector<DrawCommand> GetDrawCommands();

/** Get the number of draw commands currently buffered. */
size_t GetDrawCommandCount();

/** Mark the buffer dirty (set from HTTP thread, cleared from main thread). */
void SetDirty(bool dirty);

/** Check if the buffer has been modified since last clear. */
bool IsDirty();

//----------------------------------------------------------------------------------------
//  JSON parsing
//----------------------------------------------------------------------------------------

/** Parse a JSON string into a vector of DrawCommands.
    Expects a JSON array of objects, each with at minimum a "type" field.
    Returns an empty vector on parse failure.
*/
std::vector<DrawCommand> ParseDrawCommands(const std::string& json);

#endif // __DRAWCOMMANDS_H__
