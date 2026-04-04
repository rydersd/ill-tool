"""Generate facial expression variants from rigged face landmarks.

Given a character with facial landmarks (eye_l, eye_r, eyebrow_l,
eyebrow_r, mouth_center), apply named expression presets that shift
landmark positions by offset deltas.

Actions:
    set_expression   – Apply a named expression to the character
    list_expressions – List all available expression presets
"""

import json
import math
import copy

from pydantic import BaseModel, ConfigDict, Field
from typing import Optional

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiCharacterExpressionInput(BaseModel):
    """Apply facial expressions to rigged characters."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: set_expression, list_expressions",
    )
    character_name: str = Field(default="character", description="Character identifier")
    expression: str = Field(
        default="neutral",
        description="Expression: neutral, angry, surprised, sad, happy, determined",
    )


# ---------------------------------------------------------------------------
# Expression presets: deltas applied to facial landmarks
# ---------------------------------------------------------------------------


# Each expression is a dict mapping landmark name to [dx, dy] offset
# relative to the character's head height (normalized, then scaled).
# Positive Y is upward in AI coordinates.

EXPRESSION_PRESETS: dict[str, dict[str, list[float]]] = {
    "neutral": {
        "eyebrow_l": [0.0, 0.0],
        "eyebrow_r": [0.0, 0.0],
        "eye_l": [0.0, 0.0],
        "eye_r": [0.0, 0.0],
        "mouth_center": [0.0, 0.0],
    },
    "angry": {
        "eyebrow_l": [2.0, -4.0],    # inward and down
        "eyebrow_r": [-2.0, -4.0],   # inward and down
        "eye_l": [0.0, -1.0],        # slightly squinted
        "eye_r": [0.0, -1.0],
        "mouth_center": [0.0, -2.0],  # tightened/lowered
    },
    "surprised": {
        "eyebrow_l": [0.0, 6.0],     # raised
        "eyebrow_r": [0.0, 6.0],
        "eye_l": [0.0, 2.0],         # wide open
        "eye_r": [0.0, 2.0],
        "mouth_center": [0.0, -4.0],  # dropped open
    },
    "sad": {
        "eyebrow_l": [-1.0, -3.0],   # outer edge down
        "eyebrow_r": [1.0, -3.0],
        "eye_l": [0.0, -1.0],
        "eye_r": [0.0, -1.0],
        "mouth_center": [0.0, -3.0],  # downturned
    },
    "happy": {
        "eyebrow_l": [0.0, 2.0],     # slightly raised
        "eyebrow_r": [0.0, 2.0],
        "eye_l": [0.0, 1.0],         # bright/open
        "eye_r": [0.0, 1.0],
        "mouth_center": [0.0, 2.0],   # upturned
    },
    "determined": {
        "eyebrow_l": [1.0, -2.0],    # slightly down
        "eyebrow_r": [-1.0, -2.0],
        "eye_l": [0.0, -0.5],        # focused
        "eye_r": [0.0, -0.5],
        "mouth_center": [0.0, -1.0],  # firm line
    },
}


def get_expression_deltas(expression_name: str) -> dict[str, list[float]] | None:
    """Return the delta offsets for a named expression, or None if not found."""
    return EXPRESSION_PRESETS.get(expression_name.lower().strip())


def apply_expression_deltas(
    landmarks: dict,
    deltas: dict[str, list[float]],
    scale: float = 1.0,
) -> dict:
    """Apply expression deltas to landmarks, returning modified landmarks.

    Parameters
    ----------
    landmarks : dict
        Current rig landmarks {name: {ai: [x,y], ...}}.
    deltas : dict
        Expression deltas {landmark_name: [dx, dy]}.
    scale : float
        Scale factor for deltas (based on head height).

    Returns
    -------
    dict
        Modified landmarks with expression offsets applied.
    """
    modified = copy.deepcopy(landmarks)
    applied = []

    for lm_name, delta in deltas.items():
        if lm_name in modified and "ai" in modified[lm_name]:
            modified[lm_name]["ai"][0] += delta[0] * scale
            modified[lm_name]["ai"][1] += delta[1] * scale
            modified[lm_name]["ai"][0] = round(modified[lm_name]["ai"][0], 2)
            modified[lm_name]["ai"][1] = round(modified[lm_name]["ai"][1], 2)
            applied.append(lm_name)

    return {"landmarks": modified, "applied": applied}


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_character_expression tool."""

    @mcp.tool(
        name="adobe_ai_character_expression",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_character_expression(params: AiCharacterExpressionInput) -> str:
        """Generate facial expression variants from rigged face landmarks.

        Apply named expression presets (neutral, angry, surprised, sad,
        happy, determined) to shift facial landmark positions.
        """
        action = params.action.lower().strip()

        if action == "list_expressions":
            expressions = {}
            for name, deltas in EXPRESSION_PRESETS.items():
                expressions[name] = {
                    lm: {"dx": d[0], "dy": d[1]}
                    for lm, d in deltas.items()
                }
            return json.dumps({
                "action": "list_expressions",
                "expressions": expressions,
                "count": len(expressions),
            })

        elif action == "set_expression":
            expression = params.expression.lower().strip()
            deltas = get_expression_deltas(expression)
            if deltas is None:
                return json.dumps({
                    "error": f"Unknown expression: {expression}",
                    "valid_expressions": list(EXPRESSION_PRESETS.keys()),
                })

            rig = _load_rig(params.character_name)
            landmarks = rig.get("landmarks", {})

            # Compute scale from head height (distance head_top → chin)
            head_top = landmarks.get("head_top")
            chin = landmarks.get("chin")
            scale = 1.0
            if head_top and "ai" in head_top and chin and "ai" in chin:
                head_h = math.sqrt(
                    (chin["ai"][0] - head_top["ai"][0]) ** 2 +
                    (chin["ai"][1] - head_top["ai"][1]) ** 2
                )
                # Scale deltas proportionally: 1 unit delta ≈ 1 % of head height
                scale = head_h / 100.0 if head_h > 0 else 1.0

            result = apply_expression_deltas(landmarks, deltas, scale)

            # Update rig with the modified landmarks
            rig["landmarks"] = result["landmarks"]

            # Store current expression in rig for reference
            rig.setdefault("expressions", {})
            rig["expressions"]["current"] = expression
            rig["expressions"]["presets"] = list(EXPRESSION_PRESETS.keys())
            _save_rig(params.character_name, rig)

            return json.dumps({
                "action": "set_expression",
                "expression": expression,
                "applied_to": result["applied"],
                "scale": round(scale, 4),
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["set_expression", "list_expressions"],
            })
