# Cross-Layer Edge Clustering

> Brief: Automatic clustering of paths across extraction layers into "same structural edge" groups. Color-coded visualization, distance threshold slider, one-click Accept All cleanup. Learning loop trains from accept/split/reject corrections.
> Tags: clustering, cleanup, tracing, learning, workflow
> Created: 2026-04-04
> Updated: 2026-04-04

## Motivation

The tracing pipeline produces 200-400 paths across 5-7 layers (Scale Fine/Medium/Coarse, Ink Lines, Forms 5%). Many paths represent the SAME structural edge detected at different thresholds. The user spends 80% of cleanup time manually identifying and selecting which paths overlap. The tools are fast once selected — finding what to select is the bottleneck.

## How It Works

1. **Cluster Layers** reads ALL extraction layers, computes pairwise path similarity (proximity × angle alignment × surface coherence × curvature match), clusters with DBSCAN using a user-controllable **distance threshold**
2. Paths merged onto a single color-coded working layer — each cluster gets a distinct hue
3. **Overlap confidence**: edges detected by 3+ layers = high confidence (real structure), 1 layer = low confidence (possible noise)
4. **Accept/Accept All** averages each cluster → one clean path per structural edge
5. Every accept/split/reject correction trains the clustering thresholds for next time

## The Learning Loop

| Action | Training Signal |
|--------|----------------|
| Accept cluster | "This grouping was correct at this distance/angle/surface" |
| Split cluster | "Proximity was misleading — tighten threshold for this surface type" |
| Reject cluster | "This is noise — paths below this length/count are junk" |
| Adjust distance slider | "My preferred clustering radius for this type of artwork" |

Corrections feed into correction_learning. After enough sessions, the initial clustering is so accurate you just hit Accept All.

## See Also
- [[Expanded Normal Renderings]] — Surface classification that powers coherence scoring
- [[Smart Merge Architecture]] — Endpoint merging after clustering
- [[Adversarial Review Findings]] — Patterns the clustering implementation must avoid
