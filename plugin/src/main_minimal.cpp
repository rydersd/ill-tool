/**
 * main_minimal.cpp — Absolute minimal Illustrator plugin.
 * Just PluginMain that returns success. No dependencies, no statics.
 */

#include <cstdio>
#include <cstring>

// Log at dylib load time — before PluginMain is ever called
__attribute__((constructor))
static void onLoad() {
    fprintf(stderr, "[IllTool] dylib loaded\n");
}

typedef long ASErr;
#define kNoErr 0L

extern "C" __attribute__((visibility("default")))
ASErr PluginMain(const char* caller, const char* selector, void* message)
{
    fprintf(stderr, "[IllTool] PluginMain caller='%s' selector='%s'\n",
            caller ? caller : "(null)",
            selector ? selector : "(null)");
    return kNoErr;
}
