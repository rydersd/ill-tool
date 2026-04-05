/**
 * json_parse.h — Parse JSON draw command arrays into DrawCommand structs.
 *
 * Bridges nlohmann/json to the DrawCommand types defined in draw_commands.h.
 * Used by the HTTP bridge to convert POST /draw request bodies.
 */

#ifndef JSON_PARSE_H
#define JSON_PARSE_H

#include "draw_commands.h"
#include <string>
#include <vector>

/**
 * Parse a JSON string containing an array of draw command objects.
 *
 * Returns a vector of DrawCommand structs. Malformed commands are skipped
 * with a warning to stderr — the parser never throws or crashes.
 *
 * Expected JSON format:
 * [
 *   {
 *     "type": "line",
 *     "id": "handle_1",
 *     "points": [[100, 200], [300, 400]],
 *     "strokeColor": [1.0, 0.0, 0.0, 1.0],
 *     "strokeWidth": 2.0,
 *     ...
 *   },
 *   ...
 * ]
 */
std::vector<DrawCommand> ParseDrawCommands(const std::string& jsonStr);

#endif /* JSON_PARSE_H */
