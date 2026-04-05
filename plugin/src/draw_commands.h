/**
 * draw_commands.h — Data structures for draw commands sent from TypeScript to the C++ plugin.
 *
 * These structs define the wire format for JSON draw commands received via HTTP.
 * The annotator (Phase 2) reads from the shared command list to render overlays.
 * The HTTP bridge (Phase 3) parses JSON into these structs.
 *
 * Thread safety: The command list is protected by a mutex. All access must go
 * through UpdateDrawCommands() / GetDrawCommands().
 */

#ifndef DRAW_COMMANDS_H
#define DRAW_COMMANDS_H

#include <cstdint>
#include <mutex>
#include <string>
#include <vector>

/* -------------------------------------------------------------------------- */
/*  Primitive types                                                           */
/* -------------------------------------------------------------------------- */

struct Point2D {
    double x = 0.0;
    double y = 0.0;
};

struct Color {
    double r = 0.0;
    double g = 0.0;
    double b = 0.0;
    double a = 1.0;
};

struct BezierSegment {
    Point2D p0;  /* start */
    Point2D p1;  /* control 1 */
    Point2D p2;  /* control 2 */
    Point2D p3;  /* end */
};

/* -------------------------------------------------------------------------- */
/*  DrawCommand types                                                         */
/* -------------------------------------------------------------------------- */

enum class DrawCommandType : uint8_t {
    Unknown = 0,
    Line,
    Polyline,
    Polygon,
    Rect,
    Ellipse,
    Circle,
    Arc,
    Bezier,
    Text,
    Handle,     /* draggable control point */
    Crosshair,
    Grid,
    Image,
};

/**
 * A single draw command — maps 1:1 to a JSON object in the /draw payload.
 * Not every field is used by every type. Unused fields keep their defaults.
 */
struct DrawCommand {
    DrawCommandType type = DrawCommandType::Unknown;
    std::string     id;

    /* Geometry */
    std::vector<Point2D>        points;     /* polyline, polygon, line endpoints */
    std::vector<BezierSegment>  segments;   /* bezier curves */
    Point2D                     center;     /* circle, ellipse, arc center */
    double                      radius  = 0.0;
    double                      width   = 0.0;
    double                      height  = 0.0;
    double                      angle   = 0.0;

    /* Text */
    std::string text;
    double      fontSize = 12.0;

    /* Style */
    Color  strokeColor  = {1.0, 1.0, 1.0, 1.0};
    Color  fillColor    = {0.0, 0.0, 0.0, 0.0};
    double strokeWidth  = 1.0;
    double opacity      = 1.0;
    bool   filled       = false;
    bool   stroked      = true;

    /* Interaction */
    bool   draggable  = false;
    bool   viewSpace  = true;   /* true = screen coords, false = document coords */
    double hitRadius  = 5.0;
};

/* -------------------------------------------------------------------------- */
/*  Thread-safe shared command list                                            */
/* -------------------------------------------------------------------------- */

/**
 * Replace the entire draw command list. Thread-safe.
 * Called by the HTTP bridge when /draw or /clear is received.
 */
void UpdateDrawCommands(std::vector<DrawCommand> cmds);

/**
 * Get a snapshot of the current draw commands. Thread-safe.
 * Called by the annotator during its draw callback.
 */
std::vector<DrawCommand> GetDrawCommands();

/**
 * Get the number of commands currently stored. Thread-safe.
 */
size_t GetDrawCommandCount();

#endif /* DRAW_COMMANDS_H */
