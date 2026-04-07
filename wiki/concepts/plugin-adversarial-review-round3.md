# Adversarial Review Round 3 — 5-Specialist Team

> Brief: 40 issues found by 5 parallel specialist reviewers (thread safety, math, memory, integration, MRC). All P0s fixed. Most P1s fixed.
> Tags: review, thread-safety, memory, cocoa, integration, adversarial
> Created: 2026-04-07
> Updated: 2026-04-07

## Motivation
After two rounds of adversarial review (Claude: 14 issues, Codex: 11 issues), a third round using 5 specialist agents found 40 additional issues across domains that single-reviewer passes missed.

## Reviewer Domains

| Reviewer | Focus | Issues Found |
|----------|-------|-------------|
| Thread Safety | Data races, mutex gaps, detached threads, torn reads | 12 |
| Math | Bezier correctness, convergence, coordinate transforms | 5 |
| Memory | Matches disposal, stale handles, SDK API usage | 7 |
| Integration | Dead code, missing wiring, panel registration gaps | 11 |
| Cocoa/MRC | Retain/release, dealloc, block cycles, leaked allocs | 24 |

## Key Findings

### Thread Safety P0s
- **VisionEngine had NO mutex** — HTTP endpoints called CV methods while LoadImage mutated pixel buffers
- **LearningEngine had NO mutex** — SQLite accessed from HTTP and SDK threads simultaneously
- **StopHttpBridge deleted gServer while detached HTTP thread still running** — use-after-free

### Integration P0s
- **Blend panel completely non-functional** — pollBlendState was an empty stub, custom easing disconnected (panel wrote to local static, engine read from HttpBridge), constructor didn't initialize Blend/Perspective panel pointers

### Cocoa/MRC P0s
- **EasingCurveView _controlPoints** was a dangling pointer — direct ivar assignment of autoreleased NSMutableArray without retain

### Math Findings
- Arc-length leaf averaging has systematic positive bias on tight curves
- Arc bezier handle approximation degrades for half-sweep > 60 degrees
- De Casteljau, bezier evaluation, Sobel kernels, shoelace formula all verified correct

## Fixes Applied
- VisionEngine: `recursive_mutex` wrapping all public methods
- LearningEngine: `mutex` wrapping all public methods
- HttpBridge: `join()` instead of `detach()` for server thread
- All matches disposal on early returns (ClassifySelection, ReclassifyAs, SimplifySelection)
- Blend pick hitRef released on miss
- EasingCurveView uses property setter (retains)
- pollBlendState wired to BridgeHasBlendPathA/B
- Custom easing forwarded to BridgeSetCustomEasingPoints
- Perspective visible state synced
- GroupingPanelController dealloc added
- MergePanelController [super dealloc] added
- Blend path validation before ExecuteBlend
- Constructor initializers for Blend/Perspective panel pointers

## See Also
- [[Pipeline Gaps Closed]] (first review round)
- [[Adversarial Review Findings]] (original 80+ bug review from April 4)
