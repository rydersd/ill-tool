/**
 * plugin_globals.h — Global state for the IllTool Overlay Illustrator plugin.
 *
 * Holds all acquired suite pointers and runtime handles in one place.
 * Suites are acquired via SPBasicSuite::AcquireSuite() during plugin startup.
 *
 * Phase 1: only SPBasicSuite is acquired.
 * Phase 2+: annotator, tool, document view suites will be acquired here.
 */

#ifndef PLUGIN_GLOBALS_H
#define PLUGIN_GLOBALS_H

#include "sdk_includes.h"

/**
 * Central state struct — one instance lives as a file-scope global in main.cpp.
 * Every module can extern-reference it.
 */
struct PluginGlobals {
    /* -------------------------------------------------------------------- */
    /*  Core references                                                     */
    /* -------------------------------------------------------------------- */

    /** Sweet Pea basic suite — always available after startup. Used to acquire all other suites. */
    SPBasicSuite* basic = nullptr;

    /** Reference to this plugin, passed in every SP message. */
    SPPluginRef pluginRef = nullptr;

    /* -------------------------------------------------------------------- */
    /*  Suite pointers (acquired on demand per phase)                        */
    /* -------------------------------------------------------------------- */

    /** Phase 2 — overlay drawing */
    AIAnnotatorSuite*       annotatorSuite       = nullptr;
    AIAnnotatorDrawerSuite* annotatorDrawerSuite = nullptr;

    /** Phase 4 — custom tool */
    AIToolSuite*            toolSuite            = nullptr;

    /** Coordinate conversion (view <-> artboard) */
    AIDocumentViewSuite*    documentViewSuite    = nullptr;

    /* -------------------------------------------------------------------- */
    /*  Runtime handles                                                      */
    /* -------------------------------------------------------------------- */

    /** Handle to our registered annotator (Phase 2). */
    AIAnnotatorHandle annotator = nullptr;

    /** Handle to our registered tool (Phase 4). */
    AIToolHandle tool = nullptr;

    /* -------------------------------------------------------------------- */
    /*  State flags                                                         */
    /* -------------------------------------------------------------------- */

    /** True when the annotator is actively drawing overlays. */
    bool annotatorActive = false;

    /** True when the custom tool is selected in the toolbar. */
    bool toolActive = false;
};

/** The single global instance — defined in main.cpp, accessible everywhere via extern. */
extern PluginGlobals gPlugin;

#endif /* PLUGIN_GLOBALS_H */
