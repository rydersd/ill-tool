# AITimerSuite Dispatch Pattern

> Brief: Universal SDK-context dispatch via AITimerSuite — the fix for the DOC? error that blocks all panel button operations.
> Tags: sdk, architecture, timer, dispatch, critical-fix
> Created: 2026-04-06
> Updated: 2026-04-06

## Motivation

SDK API calls (GetMatchingArt, GetPathSegments, DuplicateArt, etc.) ONLY work during SDK message dispatch — from PluginMain handlers. They return error `1146045247` (`DOC?` = "no document") when called from NSTimer callbacks, Cocoa button action handlers, or HTTP bridge threads.

This blocked ALL panel button operations. The initial workaround used atomic flags checked in `TrackToolCursor`, but that only fires when the IllTool is the active tool AND the mouse moves.

## The Fix

`AITimerSuite` (in `AITimer.h`) sends `kSelectorAIGoTimer` messages through PluginMain — which means they run in SDK context. A timer at `kTicksPerSecond/10` (~10Hz, 6 ticks) provides reliable dispatch regardless of active tool.

## Implementation

```
IllToolSuites.h/cpp  — Add AITimerSuite to gImportSuites
IllToolPlugin.h      — Add AITimerHandle fOperationTimer
IllToolPlugin.cpp    — StartupPlugin: sAITimer->AddTimer(self, "IllTool Ops", 6, &fOperationTimer)
                     — Message: handle kCallerAITimer/kSelectorAIGoTimer -> ProcessOperationQueue()
                     — ProcessOperationQueue: drain all atomic flags, execute SDK operations
```

Panel buttons set atomic flags → Timer fires in SDK context → Operations execute safely.

## Key Constants

- `kCallerAITimer` = "AI Timer"
- `kSelectorAIGoTimer` = "AI Go"
- `kTicksPerSecond` = 60
- Timer period = kTicksPerSecond/10 = 6 ticks = ~100ms

## Gotchas

- Timer registration failure is non-fatal (log warning, continue)
- Deactivate timer in ShutdownPlugin before cleanup
- Keep IsDirty/MergeDrawCommands in BOTH timer AND TrackToolCursor for responsiveness
- HTTP endpoints must also use atomic flags, NOT call Plugin* functions directly (found via adversarial review: /cleanup/average was calling PluginAverageSelection() from HTTP thread)

## See Also
- [[Illustrator C++ Plugin SDK]] — full SDK article
- [[Plugin Architecture Hardening]] — operation queue replacing atomic flags
