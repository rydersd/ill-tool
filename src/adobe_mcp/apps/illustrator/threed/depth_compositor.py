"""3D-informed layer ordering for depth compositing.

Sorts illustration parts by depth values and assigns Illustrator
z-index ordering so that nearer objects overlap farther ones.

Pure Python — no 3D dependencies required.
"""

import json
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiDepthCompositorInput(BaseModel):
    """Compute depth-based layer ordering for illustration parts."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: compute_depth_order, status"
    )
    parts: Optional[list[str]] = Field(
        default=None,
        description="List of part/layer names to order",
    )
    depth_values: Optional[list[float]] = Field(
        default=None,
        description="Depth values for each part (lower = nearer to camera)",
    )
    z_index_start: int = Field(
        default=0,
        description="Starting z-index value for the nearest part",
    )
    z_index_step: int = Field(
        default=10,
        description="Step between z-index values (allows room for insertions)",
    )


# ---------------------------------------------------------------------------
# Depth sorting and z-index assignment
# ---------------------------------------------------------------------------


def sort_by_depth(parts: list[str], depth_values: list[float]) -> list[str]:
    """Sort parts list by depth, nearest first (ascending depth values).

    Args:
        parts: list of part/layer names
        depth_values: corresponding depth values (lower = nearer)

    Returns:
        Parts list reordered from nearest to farthest.

    Raises:
        ValueError: if parts and depth_values have different lengths.
    """
    if len(parts) != len(depth_values):
        raise ValueError(
            f"parts ({len(parts)}) and depth_values ({len(depth_values)}) "
            f"must have the same length"
        )

    # Pair, sort by depth ascending (near → far), extract names
    paired = list(zip(depth_values, parts))
    paired.sort(key=lambda x: x[0])
    return [name for _, name in paired]


def assign_z_index(
    parts: list[str],
    depth_order: list[str],
    z_start: int = 0,
    z_step: int = 10,
) -> dict[str, int]:
    """Assign Illustrator z-index values based on depth ordering.

    Parts earlier in depth_order (nearer) get higher z-index values
    so they render on top in Illustrator's layer stack.

    Args:
        parts: original list of part names (for validation)
        depth_order: parts sorted near→far
        z_start: starting z-index for the nearest part
        z_step: increment between z-index values

    Returns:
        Dict mapping part name → z-index value.
        Nearest parts get the highest z-index.

    Raises:
        ValueError: if depth_order contains names not in parts.
    """
    parts_set = set(parts)
    for name in depth_order:
        if name not in parts_set:
            raise ValueError(f"'{name}' in depth_order but not in parts")

    # Nearest object (first in depth_order) gets highest z-index
    # so it renders on top in Illustrator
    n = len(depth_order)
    z_map = {}
    for i, name in enumerate(depth_order):
        # Nearest (i=0) gets highest z-index, farthest gets lowest
        z_map[name] = z_start + (n - 1 - i) * z_step

    return z_map


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_depth_compositor tool."""

    @mcp.tool(
        name="adobe_ai_depth_compositor",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_depth_compositor(params: AiDepthCompositorInput) -> str:
        """Compute depth-based layer ordering for illustration parts.

        Actions:
        - compute_depth_order: sort parts by depth and assign z-indices
        - status: report tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "supported_actions": ["compute_depth_order", "status"],
                "description": "Sorts parts by depth and assigns z-index for Illustrator layer ordering",
            }, indent=2)

        # ── compute_depth_order ─────────────────────────────────────
        if action == "compute_depth_order":
            if not params.parts:
                return json.dumps({"error": "parts list is required"})
            if not params.depth_values:
                return json.dumps({"error": "depth_values list is required"})

            try:
                ordered = sort_by_depth(params.parts, params.depth_values)
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

            try:
                z_map = assign_z_index(
                    params.parts, ordered,
                    z_start=params.z_index_start,
                    z_step=params.z_index_step,
                )
            except ValueError as exc:
                return json.dumps({"error": str(exc)})

            return json.dumps({
                "action": "compute_depth_order",
                "depth_order": ordered,
                "z_index_map": z_map,
                "nearest": ordered[0] if ordered else None,
                "farthest": ordered[-1] if ordered else None,
                "part_count": len(ordered),
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["compute_depth_order", "status"],
        })
