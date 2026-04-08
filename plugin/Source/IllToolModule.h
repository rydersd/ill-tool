#ifndef __ILLTOOLMODULE_H__
#define __ILLTOOLMODULE_H__

//========================================================================================
//  IllToolModule — Base interface for modular plugin features
//
//  Each feature (cleanup, perspective, merge, etc.) implements this interface.
//  The plugin core routes operations, mouse events, and draw calls to modules.
//========================================================================================

#include "IllustratorSDK.h"
#include "HttpBridge.h"
#include "IllToolSuites.h"
#include <vector>

// Forward declarations
class IllToolPlugin;

class IllToolModule {
public:
    virtual ~IllToolModule() {}

    /** Set the plugin pointer (called once during module registration). */
    void SetPlugin(IllToolPlugin* plugin) { fPlugin = plugin; }

    //------------------------------------------------------------------------------------
    //  Operation dispatch
    //------------------------------------------------------------------------------------

    /** Handle an operation from the queue. Return true if this module handled it. */
    virtual bool HandleOp(const PluginOp& op) = 0;

    //------------------------------------------------------------------------------------
    //  Mouse event dispatch (return true if consumed)
    //------------------------------------------------------------------------------------

    virtual bool HandleMouseDown(AIToolMessage* msg) { return false; }
    virtual bool HandleMouseDrag(AIToolMessage* msg) { return false; }
    virtual bool HandleMouseUp(AIToolMessage* msg) { return false; }

    //------------------------------------------------------------------------------------
    //  Annotator overlay
    //------------------------------------------------------------------------------------

    /** Draw this module's overlays. Called every annotator draw cycle. */
    virtual void DrawOverlay(AIAnnotatorMessage* msg) {}

    //------------------------------------------------------------------------------------
    //  Notifications
    //------------------------------------------------------------------------------------

    /** Called when Illustrator's selection changes. */
    virtual void OnSelectionChanged() {}

    /** Called on document change (new doc, open, close). Clear cached state. */
    virtual void OnDocumentChanged() {}

    //------------------------------------------------------------------------------------
    //  Undo support
    //------------------------------------------------------------------------------------

    /** Return true if this module has something to undo. */
    virtual bool CanUndo() { return false; }

    /** Undo the last operation in this module. */
    virtual void Undo() {}

    //------------------------------------------------------------------------------------
    //  Invalidation helper
    //------------------------------------------------------------------------------------

    /** Request a full view redraw (annotator invalidation). */
    void InvalidateFullView();

protected:
    IllToolPlugin* fPlugin = nullptr;
};

//========================================================================================
//  UndoStack — generic multi-level undo for path operations
//  Shared across modules. Each module owns its own instance.
//========================================================================================

class UndoStack {
public:
    struct PathSnapshot {
        AIArtHandle art;
        std::vector<AIPathSegment> segments;
        AIBoolean closed;
    };

    /** Begin a new undo frame. Call before a destructive operation. */
    void PushFrame();

    /** Save a path's current state into the top frame. */
    void SnapshotPath(AIArtHandle art);

    /** Restore all paths in the top frame and pop it. Returns number restored. */
    int Undo();

    /** Check if there's anything to undo. */
    bool CanUndo() const { return !stack.empty(); }

    /** Clear all frames. */
    void Clear() { stack.clear(); }

    static const int kMaxFrames = 20;

private:
    std::vector<std::vector<PathSnapshot>> stack;
};

#endif // __ILLTOOLMODULE_H__
