/**
 * main.cpp — Entry point for the IllTool Overlay Illustrator plugin.
 *
 * Illustrator calls PluginMain() with C linkage for every message directed
 * at this plugin. We dispatch based on caller+selector strings.
 *
 * Phase 1: handles startup/shutdown only.
 * Phase 2: annotator registration and draw dispatch.
 * Phase 3: HTTP bridge start/stop.
 * Phase 4: will add tool message dispatch.
 */

#include "plugin_globals.h"
#include "annotator.h"
#include "tool.h"
#include "http_bridge.h"
#include "llm_client.h"

#include <cstdio>
#include <cstring>

/* -------------------------------------------------------------------------- */
/*  Global state instance                                                     */
/* -------------------------------------------------------------------------- */

PluginGlobals gPlugin;

/* -------------------------------------------------------------------------- */
/*  Forward declarations                                                      */
/* -------------------------------------------------------------------------- */

static ASErr StartupPlugin(SPInterfaceMessage* msg);
static ASErr ShutdownPlugin(SPInterfaceMessage* msg);

/* -------------------------------------------------------------------------- */
/*  PluginMain — the single entry point Illustrator calls                     */
/* -------------------------------------------------------------------------- */

extern "C" __attribute__((visibility("default")))
ASErr PluginMain(const char* caller, const char* selector, void* message)
{
    ASErr result = kUnhandledMsgErr;

    /* --- SP Interface lifecycle ----------------------------------------- */
    if (std::strcmp(caller, kSPInterfaceCaller) == 0) {

        if (std::strcmp(selector, kSPInterfaceStartupSelector) == 0) {
            result = StartupPlugin(static_cast<SPInterfaceMessage*>(message));
        }
        else if (std::strcmp(selector, kSPInterfaceShutdownSelector) == 0) {
            result = ShutdownPlugin(static_cast<SPInterfaceMessage*>(message));
        }
    }

    /* --- Annotator messages (Phase 2) ----------------------------------- */
    else if (std::strcmp(caller, kCallerAIAnnotation) == 0) {
        result = HandleAnnotatorMessage(selector, message);
    }

    /* --- Tool messages (Phase 4) ---------------------------------------- */
    else if (std::strcmp(caller, kCallerAITool) == 0) {
        result = HandleToolMessage(caller, selector, message);
    }

    return result;
}

/* -------------------------------------------------------------------------- */
/*  StartupPlugin                                                             */
/* -------------------------------------------------------------------------- */

/**
 * Called once when Illustrator loads the plugin.
 * Stores the SPBasicSuite pointer and plugin reference, acquires suites,
 * and registers the annotator.
 */
static ASErr StartupPlugin(SPInterfaceMessage* msg)
{
    if (!msg || !msg->d.basic) {
        fprintf(stderr, "[IllTool] ERROR: null message or basic suite.\n");
        return kUnhandledMsgErr;
    }

    gPlugin.basic     = msg->d.basic;
    gPlugin.pluginRef = msg->d.self;

    fprintf(stderr, "[IllTool] Plugin loaded OK. basic=%p pluginRef=%p\n",
            static_cast<void*>(gPlugin.basic),
            static_cast<void*>(gPlugin.pluginRef));

    /* MINIMAL STARTUP — just prove we load. Features added incrementally. */

    /* Phase 3: HTTP bridge (no SDK dependency, pure sockets) */
    if (!StartHttpBridge(8787)) {
        fprintf(stderr, "[IllTool] WARNING: HTTP bridge failed to start.\n");
    } else {
        fprintf(stderr, "[IllTool] HTTP bridge listening on :8787\n");
    }

    return kNoErr;
}

/* -------------------------------------------------------------------------- */
/*  ShutdownPlugin                                                            */
/* -------------------------------------------------------------------------- */

/**
 * Called once when Illustrator unloads the plugin.
 * Deactivates the annotator, releases acquired suites, and clears global state.
 */
static ASErr ShutdownPlugin(SPInterfaceMessage* /*msg*/)
{
    fprintf(stderr, "[IllTool] IllTool Overlay plugin shutting down.\n");

    /* Stop HTTP bridge first — prevents new commands arriving during teardown. */
    StopHttpBridge();

    /* Deactivate annotator before releasing suites. */
    if (gPlugin.annotatorActive) {
        SetAnnotatorActive(false);
    }

    /* Release acquired suites. */
    if (gPlugin.basic) {
        if (gPlugin.toolSuite) {
            gPlugin.basic->ReleaseSuite(kAIToolSuite, kAIToolSuiteVersion);
        }
        if (gPlugin.annotatorDrawerSuite) {
            gPlugin.basic->ReleaseSuite(kAIAnnotatorDrawerSuite, kAIAnnotatorDrawerSuiteVersion);
        }
        if (gPlugin.annotatorSuite) {
            gPlugin.basic->ReleaseSuite(kAIAnnotatorSuite, kAIAnnotatorSuiteVersion);
        }
    }

    /* Clear all state. */
    gPlugin.basic                = nullptr;
    gPlugin.pluginRef            = nullptr;
    gPlugin.annotatorSuite       = nullptr;
    gPlugin.annotatorDrawerSuite = nullptr;
    gPlugin.toolSuite            = nullptr;
    gPlugin.documentViewSuite    = nullptr;
    gPlugin.annotator            = nullptr;
    gPlugin.tool                 = nullptr;
    gPlugin.annotatorActive      = false;
    gPlugin.toolActive           = false;

    fprintf(stderr, "[IllTool] Shutdown complete.\n");

    return kNoErr;
}
