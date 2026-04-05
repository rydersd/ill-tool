/**
 * draw_commands.cpp — Thread-safe shared draw command storage.
 *
 * Provides the mutex-protected command list that the HTTP bridge writes to
 * and the annotator reads from. Both modules include draw_commands.h for
 * the struct definitions and call these functions for access.
 */

#include "draw_commands.h"

/* -------------------------------------------------------------------------- */
/*  Internal state — mutex-protected                                          */
/* -------------------------------------------------------------------------- */

static std::mutex              sCommandMutex;
static std::vector<DrawCommand> sCommands;

/* -------------------------------------------------------------------------- */
/*  Public API                                                                */
/* -------------------------------------------------------------------------- */

void UpdateDrawCommands(std::vector<DrawCommand> cmds)
{
    std::lock_guard<std::mutex> lock(sCommandMutex);
    sCommands = std::move(cmds);
}

std::vector<DrawCommand> GetDrawCommands()
{
    std::lock_guard<std::mutex> lock(sCommandMutex);
    return sCommands;  /* returns a copy — safe to use outside the lock */
}

size_t GetDrawCommandCount()
{
    std::lock_guard<std::mutex> lock(sCommandMutex);
    return sCommands.size();
}
