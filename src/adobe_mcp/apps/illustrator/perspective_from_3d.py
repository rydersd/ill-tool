"""3D-corrected 2D drawing — perspective error detection and reporting.

Compares 2D drawing points against 3D-rendered reference points to
detect and classify perspective errors, then generates a correction
report listing what to fix.

Pure Python — no JSX, no 3D engine required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiPerspectiveFrom3dInput(BaseModel):
    """Check perspective accuracy of 2D drawing against 3D reference."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: check_perspective, status",
    )
    drawing_points_2d: Optional[list[list[float]]] = Field(
        default=None,
        description="2D points from the drawing: [[x, y], ...]",
    )
    rendered_points_2d: Optional[list[list[float]]] = Field(
        default=None,
        description="2D points from the 3D render: [[x, y], ...]",
    )
    point_labels: Optional[list[str]] = Field(
        default=None,
        description="Optional names for each point (e.g. 'left_eye', 'chin')",
    )
    threshold: float = Field(
        default=5.0,
        description="Error threshold in pixels: below = minor, above = major",
    )
    character_name: str = Field(
        default="character",
        description="Character identifier",
    )


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def compute_perspective_error(
    drawing_points_2d: list[list[float]],
    rendered_points_2d: list[list[float]],
) -> dict:
    """Compute per-point Euclidean distance between drawing and 3D-rendered reference.

    Points at the same index in both lists are compared. If the lists
    differ in length, only the overlapping points are compared.

    Args:
        drawing_points_2d: 2D points from the artist's drawing.
        rendered_points_2d: 2D points from the 3D render.

    Returns:
        dict with:
        - ``errors``: list of per-point distances
        - ``mean_error``: average distance
        - ``max_error``: worst-case distance
        - ``point_count``: number of points compared
    """
    if not drawing_points_2d or not rendered_points_2d:
        return {"error": "Both drawing_points_2d and rendered_points_2d are required"}

    n = min(len(drawing_points_2d), len(rendered_points_2d))
    if n == 0:
        return {"error": "Point lists are empty"}

    errors = []
    for i in range(n):
        dp = drawing_points_2d[i]
        rp = rendered_points_2d[i]

        # Handle 2D points — pad to at least 2 elements
        dx = (dp[0] if len(dp) > 0 else 0) - (rp[0] if len(rp) > 0 else 0)
        dy = (dp[1] if len(dp) > 1 else 0) - (rp[1] if len(rp) > 1 else 0)

        dist = math.sqrt(dx * dx + dy * dy)
        errors.append(round(dist, 4))

    mean_error = round(sum(errors) / len(errors), 4) if errors else 0.0
    max_error = round(max(errors), 4) if errors else 0.0

    return {
        "errors": errors,
        "mean_error": mean_error,
        "max_error": max_error,
        "point_count": n,
    }


def classify_error(errors: list[float], threshold: float = 5.0) -> list[str]:
    """Classify each error as 'minor' (below threshold) or 'major' (above).

    Args:
        errors: list of per-point distances.
        threshold: cutoff in pixels.

    Returns:
        list of classification strings, same length as errors.
    """
    threshold = max(0.001, threshold)  # Prevent zero threshold
    return ["minor" if e <= threshold else "major" for e in errors]


def generate_correction_report(
    errors: list[float],
    classifications: list[str],
    point_labels: Optional[list[str]] = None,
) -> dict:
    """Generate a structured report of perspective corrections needed.

    Groups points into minor and major categories, and produces a
    human-readable summary with specific fix recommendations.

    Args:
        errors: per-point distances.
        classifications: 'minor' or 'major' per point.
        point_labels: optional names for each point.

    Returns:
        dict with summary counts, per-point details, and action items.
    """
    n = min(len(errors), len(classifications))
    if n == 0:
        return {
            "summary": "No points to evaluate",
            "major_count": 0,
            "minor_count": 0,
            "points": [],
        }

    details = []
    major_count = 0
    minor_count = 0

    for i in range(n):
        label = point_labels[i] if point_labels and i < len(point_labels) else f"point_{i}"
        cls = classifications[i]
        err = errors[i]

        if cls == "major":
            major_count += 1
            recommendation = f"Adjust '{label}' by ~{err:.1f}px to match 3D reference"
        else:
            minor_count += 1
            recommendation = f"'{label}' is close — {err:.1f}px deviation (acceptable)"

        details.append({
            "index": i,
            "label": label,
            "error_px": round(err, 2),
            "classification": cls,
            "recommendation": recommendation,
        })

    # Sort by error magnitude (worst first)
    details.sort(key=lambda d: d["error_px"], reverse=True)

    # Summary text
    total = major_count + minor_count
    if major_count == 0:
        summary = f"All {total} points within tolerance — perspective looks accurate"
    elif major_count <= 2:
        summary = f"{major_count} point(s) need correction out of {total} — mostly accurate"
    else:
        summary = f"{major_count} of {total} points off — significant perspective correction needed"

    return {
        "summary": summary,
        "major_count": major_count,
        "minor_count": minor_count,
        "total_points": total,
        "points": details,
    }


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_perspective_from_3d tool."""

    @mcp.tool(
        name="adobe_ai_perspective_from_3d",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_perspective_from_3d(params: AiPerspectiveFrom3dInput) -> str:
        """Check perspective accuracy of 2D drawing against 3D reference.

        Actions:
        - check_perspective: compute errors, classify, and generate report
        - status: show configuration and readiness
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps({
                "action": "status",
                "tool": "perspective_from_3d",
                "default_threshold": params.threshold,
                "ready": True,
            }, indent=2)

        elif action == "check_perspective":
            if not params.drawing_points_2d or not params.rendered_points_2d:
                return json.dumps({
                    "error": "Both drawing_points_2d and rendered_points_2d are required",
                })

            error_result = compute_perspective_error(
                params.drawing_points_2d,
                params.rendered_points_2d,
            )
            if "error" in error_result:
                return json.dumps(error_result)

            classifications = classify_error(error_result["errors"], params.threshold)
            report = generate_correction_report(
                error_result["errors"],
                classifications,
                params.point_labels,
            )

            return json.dumps({
                "action": "check_perspective",
                "character_name": params.character_name,
                "threshold": params.threshold,
                "errors": error_result,
                "report": report,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["check_perspective", "status"],
            })
