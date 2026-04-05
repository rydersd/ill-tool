/**
 * ai_sdk_compat.h — TEMPORARY compatibility shim for Illustrator Plugin SDK types.
 *
 * This file defines the minimum types, structs, and constants needed to compile
 * the IllTool Overlay plugin WITHOUT the real Adobe Illustrator SDK headers.
 *
 * !! REPLACE THIS FILE with real SDK headers once they are available. !!
 * !! Every type here is a stand-in. Real SDK types may differ in layout. !!
 *
 * Phase 1 only — just enough to compile and not crash on load.
 */

#ifndef AI_SDK_COMPAT_H
#define AI_SDK_COMPAT_H

#include <cstdint>
#include <cstring>

/* -------------------------------------------------------------------------- */
/*  Primitive types                                                           */
/* -------------------------------------------------------------------------- */

/** Standard error type. 0 = success. */
using ASErr = int32_t;
constexpr ASErr kNoErr = 0;
constexpr ASErr kUnhandledMsgErr = 'UNHN';  /* message not handled */

/** Opaque references — real SDK uses typed pointers. */
using SPPluginRef       = void*;
using AIAnnotatorHandle = void*;
using AIToolHandle      = void*;

/* -------------------------------------------------------------------------- */
/*  Caller / Selector string constants                                        */
/* -------------------------------------------------------------------------- */

/** Sweet Pea interface lifecycle. */
constexpr const char* kSPInterfaceCaller            = "SP Interface";
constexpr const char* kSPInterfaceStartupSelector   = "SP Interface Startup";
constexpr const char* kSPInterfaceShutdownSelector  = "SP Interface Shutdown";

/** Annotator caller — Illustrator sends draw/invalidate messages here. */
constexpr const char* kCallerAIAnnotation = "AI Annotation";

/** Tool caller — Illustrator sends mouse/key events here. */
constexpr const char* kCallerAITool = "AI Tool";

/* -------------------------------------------------------------------------- */
/*  SPBasicSuite — the root suite, always available                           */
/* -------------------------------------------------------------------------- */

/**
 * Minimal SPBasicSuite. The real suite has more members, but startup only
 * needs AcquireSuite and ReleaseSuite.
 */
struct SPBasicSuite {
    /** Acquire a named suite at a specific version. Returns suite pointer via acquiredSuite. */
    ASErr (*AcquireSuite)(const char* name, int32_t version, const void** acquiredSuite);

    /** Release a previously acquired suite. */
    ASErr (*ReleaseSuite)(const char* name, int32_t version);

    /** Check if a suite is available without acquiring it. */
    ASErr (*IsEqual)(const char* token1, const char* token2);

    /** Allocate memory via the host allocator. */
    ASErr (*AllocateBlock)(size_t size, void** block);

    /** Free memory allocated by AllocateBlock. */
    ASErr (*FreeBlock)(void* block);

    /** Undefined / reserved — keeps struct size flexible. */
    ASErr (*Undefined)(void);
};

/* -------------------------------------------------------------------------- */
/*  Message structs                                                           */
/* -------------------------------------------------------------------------- */

/**
 * SPMessageData — the 'd' sub-struct inside every SP message.
 * The real SDK nests this as message->d.basic / message->d.self.
 */
struct SPMessageData {
    int32_t       SPCheck;       /* magic validation token */
    SPPluginRef   self;          /* reference to this plugin */
    void*         globals;       /* pointer to plugin's global data */
    SPBasicSuite* basic;         /* always non-null at startup */
};

/**
 * SPInterfaceMessage — the top-level message for startup/shutdown.
 * Cast the void* message to this for kSPInterfaceCaller.
 */
struct SPInterfaceMessage {
    SPMessageData d;
};

/* -------------------------------------------------------------------------- */
/*  Geometric types                                                           */
/* -------------------------------------------------------------------------- */

/** Floating-point type used throughout the SDK. */
using AIReal = double;

/** Integer point — view/screen coordinates (pixels). */
struct AIPoint {
    int32_t h = 0;  /* horizontal (x) */
    int32_t v = 0;  /* vertical   (y) */
};

/** Floating-point point — document/artboard coordinates. */
struct AIRealPoint {
    AIReal h = 0.0;  /* horizontal (x) */
    AIReal v = 0.0;  /* vertical   (y) */
};

/** Integer rectangle — view/screen coordinates. */
struct AIRect {
    int32_t top    = 0;
    int32_t left   = 0;
    int32_t bottom = 0;
    int32_t right  = 0;
};

/** RGB color — each channel is 0-65535 (unsigned short). */
struct AIRGBColor {
    uint16_t red   = 0;
    uint16_t green = 0;
    uint16_t blue  = 0;
};

/* -------------------------------------------------------------------------- */
/*  Annotator selectors                                                       */
/* -------------------------------------------------------------------------- */

/** Selector sent when the annotator should draw its overlay. */
constexpr const char* kSelectorAIDrawAnnotation  = "AI Draw Annotation";

/** Selector sent when the annotator's region should be invalidated. */
constexpr const char* kSelectorAIInvalAnnotation = "AI Inval Annotation";

/* -------------------------------------------------------------------------- */
/*  Annotator message and drawer types                                        */
/* -------------------------------------------------------------------------- */

/** Opaque handle to the annotation drawer context. */
using AIAnnotatorDrawer = void;

/**
 * AIAnnotatorMessage — passed to the plugin when handling annotator selectors.
 * The drawer member is valid only during kSelectorAIDrawAnnotation.
 */
struct AIAnnotatorMessage {
    SPMessageData      d;
    AIAnnotatorDrawer* drawer = nullptr;
};

/* -------------------------------------------------------------------------- */
/*  AIAnnotatorSuite — register and manage annotators                         */
/* -------------------------------------------------------------------------- */

struct AIAnnotatorSuite {
    /**
     * Register a new annotator.
     * @param pluginRef   This plugin's reference.
     * @param name        Display name for the annotator.
     * @param outHandle   Receives the annotator handle.
     */
    ASErr (*AddAnnotator)(SPPluginRef pluginRef, const char* name,
                          AIAnnotatorHandle* outHandle);

    /**
     * Toggle annotator on or off.
     * @param handle  Annotator handle from AddAnnotator.
     * @param active  true = draw, false = hidden.
     */
    ASErr (*SetAnnotatorActive)(AIAnnotatorHandle handle, bool active);

    /**
     * Invalidate a rectangular region so the annotator redraws.
     * Pass a null or full-view rect to invalidate everything.
     */
    ASErr (*InvalAnnotationRect)(const AIRect* rect);
};

/* -------------------------------------------------------------------------- */
/*  AIAnnotatorDrawerSuite (v8) — drawing primitives for annotation overlay   */
/* -------------------------------------------------------------------------- */

struct AIAnnotatorDrawerSuite {
    /** Set stroke/fill color for subsequent draw calls. */
    ASErr (*SetColor)(AIAnnotatorDrawer* drawer, const AIRGBColor* color);

    /** Set line width in pixels. */
    ASErr (*SetLineWidth)(AIAnnotatorDrawer* drawer, AIReal width);

    /**
     * Draw a line segment from start to end.
     * Coordinates are in view (screen) space.
     */
    ASErr (*DrawLine)(AIAnnotatorDrawer* drawer,
                      const AIPoint* start, const AIPoint* end);

    /**
     * Draw a rectangle.
     * @param filled  If true, fill the rect; otherwise stroke only.
     */
    ASErr (*DrawRect)(AIAnnotatorDrawer* drawer,
                      const AIRect* rect, bool filled);

    /**
     * Draw an ellipse inscribed in the given rect.
     * @param filled  If true, fill the ellipse; otherwise stroke only.
     */
    ASErr (*DrawEllipse)(AIAnnotatorDrawer* drawer,
                         const AIRect* rect, bool filled);

    /**
     * Draw a polygon from an array of points.
     * @param numPoints  Number of points in the array.
     * @param filled     If true, fill; otherwise stroke only.
     */
    ASErr (*DrawPolygon)(AIAnnotatorDrawer* drawer,
                         const AIPoint* points, int32_t numPoints, bool filled);

    /**
     * Enable or disable dashed line style.
     * @param dashed  true = dashed, false = solid.
     */
    ASErr (*SetLineDashed)(AIAnnotatorDrawer* drawer, bool dashed);
};

/* -------------------------------------------------------------------------- */
/*  Tool selectors                                                            */
/* -------------------------------------------------------------------------- */

/** Selectors sent when the custom tool receives mouse/cursor events. */
constexpr const char* kSelectorAIToolMouseDown    = "AI Tool Mouse Down";
constexpr const char* kSelectorAIToolMouseDrag    = "AI Tool Mouse Drag";
constexpr const char* kSelectorAIToolMouseUp      = "AI Tool Mouse Up";
constexpr const char* kSelectorAITrackToolCursor  = "AI Track Tool Cursor";

/* -------------------------------------------------------------------------- */
/*  Tool cursor constants                                                     */
/* -------------------------------------------------------------------------- */

constexpr int32_t kCursorCrosshair = 1;
constexpr int32_t kCursorArrow     = 0;

/** Sentinel for "no tool registered". */
constexpr AIToolHandle kNoTool = nullptr;

/** Tool option flag — request cursor tracking messages. */
constexpr int32_t kToolWantsToTrackCursorOption = (1 << 0);

/* -------------------------------------------------------------------------- */
/*  Tool message and suite types                                              */
/* -------------------------------------------------------------------------- */

/**
 * AIToolMessage — passed to the plugin for tool mouse/cursor events.
 * Contains cursor position in document coordinates and pressure.
 */
struct AIToolMessage {
    SPMessageData d;
    AIRealPoint   cursor;       /* document-space coordinates */
    double        pressure;     /* 0.0 - 1.0, tablet pressure */
};

/**
 * AIAddToolData — data for registering a new tool.
 */
struct AIAddToolData {
    const char* title;
    const char* tooltip;
};

/**
 * AIToolSuite — register and manage custom tools.
 */
struct AIToolSuite {
    /**
     * Register a new tool with the Illustrator toolbox.
     * @param pluginRef  This plugin's reference.
     * @param data       Tool registration data (title, tooltip).
     * @param options    Option flags (e.g. kToolWantsToTrackCursorOption).
     * @param outHandle  Receives the tool handle.
     */
    ASErr (*AddTool)(SPPluginRef pluginRef, const AIAddToolData* data,
                     int32_t options, AIToolHandle* outHandle);

    /**
     * Set the cursor shape for the tool.
     * @param cursorId  Cursor constant (kCursorCrosshair, kCursorArrow, etc).
     */
    ASErr (*SetToolCursor)(int32_t cursorId);
};

/* -------------------------------------------------------------------------- */
/*  Forward-declared suite structs (Phase 5+)                                 */
/* -------------------------------------------------------------------------- */

/** Will be fully defined when real SDK headers are integrated. */
struct AIDocumentViewSuite;

/* -------------------------------------------------------------------------- */
/*  Suite name / version constants (for AcquireSuite calls)                   */
/* -------------------------------------------------------------------------- */

constexpr const char* kAIAnnotatorSuite       = "AI Annotator Suite";
constexpr int32_t     kAIAnnotatorSuiteVersion = 1;

constexpr const char* kAIAnnotatorDrawerSuite       = "AI Annotator Drawer Suite";
constexpr int32_t     kAIAnnotatorDrawerSuiteVersion = 8;

constexpr const char* kAIToolSuite       = "AI Tool Suite";
constexpr int32_t     kAIToolSuiteVersion = 1;

constexpr const char* kAIDocumentViewSuite       = "AI Document View Suite";
constexpr int32_t     kAIDocumentViewSuiteVersion = 1;

#endif /* AI_SDK_COMPAT_H */
