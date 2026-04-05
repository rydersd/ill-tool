/**
 * annotator.h — Annotator registration and drawing for the IllTool overlay.
 *
 * Phase 2 implements the full annotator using AIAnnotatorSuite.
 * Phase 3 (HTTP bridge) calls SetAnnotatorActive() to toggle the overlay.
 *
 * The annotator's draw callback reads from the shared command list
 * (draw_commands.h) to render overlays on the Illustrator canvas.
 */

#ifndef ANNOTATOR_H
#define ANNOTATOR_H

#include "sdk_includes.h"

/**
 * Register the annotator with Illustrator. Called during plugin startup.
 * Phase 2 implements this — Phase 3 stub returns kNoErr.
 */
ASErr RegisterAnnotator();

/**
 * Toggle annotator visibility. Thread-safe (called from HTTP bridge thread).
 */
void SetAnnotatorActive(bool active);

/**
 * Query whether the annotator is currently active.
 */
bool IsAnnotatorActive();

/**
 * Handle an annotator message from Illustrator (draw/invalidate).
 * Phase 2 implements the actual drawing logic.
 */
ASErr HandleAnnotatorMessage(const char* selector, void* message);

#endif /* ANNOTATOR_H */
