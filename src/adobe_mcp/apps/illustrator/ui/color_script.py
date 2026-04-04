"""Plan color palette progression across scenes.

Assigns mood-based color palettes to scenes and ensures visual contrast
between adjacent scenes for dynamic storytelling.

Pure Python — no JSX or Adobe required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiColorScriptInput(BaseModel):
    """Plan color palette progression across scenes."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="create",
        description="Action: create, assign_mood, color_arc",
    )
    character_name: str = Field(
        default="character", description="Character / project identifier"
    )
    scenes: Optional[list[dict]] = Field(
        default=None,
        description="List of scene dicts with 'name' and optional 'mood'/'description'",
    )
    scene_description: Optional[str] = Field(
        default=None,
        description="Text description for mood detection",
    )
    moods: Optional[list[str]] = Field(
        default=None,
        description="Ordered list of mood names for arc generation",
    )


# ---------------------------------------------------------------------------
# Mood palettes
# ---------------------------------------------------------------------------


MOOD_PALETTES = {
    "neutral": {"dominant": "#808080", "accent": "#4a90d9"},
    "warm": {"dominant": "#d4956b", "accent": "#c0392b"},
    "cool": {"dominant": "#5b9bd5", "accent": "#2c3e50"},
    "tense": {"dominant": "#2c3e50", "accent": "#e74c3c"},
    "happy": {"dominant": "#f39c12", "accent": "#27ae60"},
    "sad": {"dominant": "#34495e", "accent": "#7f8c8d"},
    "mysterious": {"dominant": "#2c2c54", "accent": "#9b59b6"},
}

# Keyword-to-mood mapping for automatic mood detection
_MOOD_KEYWORDS = {
    "dark": "tense",
    "shadow": "tense",
    "danger": "tense",
    "fight": "tense",
    "threat": "tense",
    "storm": "tense",
    "angry": "tense",
    "sunny": "happy",
    "bright": "happy",
    "joy": "happy",
    "celebrate": "happy",
    "laugh": "happy",
    "love": "happy",
    "play": "happy",
    "rain": "sad",
    "cry": "sad",
    "lonely": "sad",
    "grief": "sad",
    "loss": "sad",
    "cold": "cool",
    "ice": "cool",
    "night": "cool",
    "ocean": "cool",
    "winter": "cool",
    "fire": "warm",
    "heat": "warm",
    "desert": "warm",
    "sunset": "warm",
    "summer": "warm",
    "cozy": "warm",
    "fog": "mysterious",
    "mystery": "mysterious",
    "secret": "mysterious",
    "unknown": "mysterious",
    "hidden": "mysterious",
    "magic": "mysterious",
    "dream": "mysterious",
}


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------


def assign_mood(scene_description: str) -> str:
    """Detect mood from a scene description using keyword matching.

    Scans the description for known keywords and returns the most
    frequently matched mood. Falls back to 'neutral'.
    """
    if not scene_description:
        return "neutral"

    desc_lower = scene_description.lower()
    mood_counts: dict[str, int] = {}

    for keyword, mood in _MOOD_KEYWORDS.items():
        if keyword in desc_lower:
            mood_counts[mood] = mood_counts.get(mood, 0) + 1

    if not mood_counts:
        return "neutral"

    # Return the mood with the most keyword hits
    return max(mood_counts, key=mood_counts.get)


def _hex_to_rgb(hex_color: str) -> tuple[int, int, int]:
    """Convert hex color string to (r, g, b) tuple."""
    h = hex_color.lstrip("#")
    return (int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16))


def _color_distance(c1: str, c2: str) -> float:
    """Compute simple Euclidean distance between two hex colors."""
    r1, g1, b1 = _hex_to_rgb(c1)
    r2, g2, b2 = _hex_to_rgb(c2)
    return math.sqrt((r1 - r2) ** 2 + (g1 - g2) ** 2 + (b1 - b2) ** 2)


def create_color_script(scenes: list[dict]) -> list[dict]:
    """Assign a mood-based color palette to each scene.

    If a scene has a 'mood' key, that mood is used directly.
    If it has a 'description' key, mood is auto-detected via keywords.
    Otherwise, defaults to 'neutral'.

    Returns a list of scene dicts enriched with palette info.
    """
    results = []
    for scene in scenes:
        name = scene.get("name", f"Scene {len(results) + 1}")
        mood = scene.get("mood")

        if mood is None:
            description = scene.get("description", "")
            mood = assign_mood(description)

        # Validate mood; fall back to neutral
        if mood not in MOOD_PALETTES:
            mood = "neutral"

        palette = MOOD_PALETTES[mood]

        results.append({
            "name": name,
            "mood": mood,
            "dominant": palette["dominant"],
            "accent": palette["accent"],
        })

    return results


def generate_color_arc(moods: list[str]) -> list[dict]:
    """Plan the color progression across a sequence of moods.

    Ensures visual variety: if two adjacent scenes share the same mood,
    the second gets a shifted accent to maintain contrast.

    Returns a list of palette dicts with contrast annotations.
    """
    if not moods:
        return []

    arc = []
    for i, mood in enumerate(moods):
        valid_mood = mood if mood in MOOD_PALETTES else "neutral"
        palette = MOOD_PALETTES[valid_mood].copy()

        contrast_with_prev = None
        if i > 0:
            prev_dominant = arc[i - 1]["dominant"]
            contrast_with_prev = round(_color_distance(palette["dominant"], prev_dominant), 1)

            # If same mood as previous, flip dominant/accent for visual variety
            if valid_mood == arc[i - 1]["mood"]:
                palette["dominant"], palette["accent"] = palette["accent"], palette["dominant"]
                contrast_with_prev = round(
                    _color_distance(palette["dominant"], arc[i - 1]["dominant"]), 1
                )

        entry = {
            "index": i,
            "mood": valid_mood,
            "dominant": palette["dominant"],
            "accent": palette["accent"],
        }
        if contrast_with_prev is not None:
            entry["contrast_with_previous"] = contrast_with_prev

        arc.append(entry)

    return arc


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_color_script tool."""

    @mcp.tool(
        name="adobe_ai_color_script",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_color_script(params: AiColorScriptInput) -> str:
        """Plan color palette progression across scenes.

        Actions:
        - create: assign palettes to a list of scenes
        - assign_mood: detect mood from a scene description
        - color_arc: plan color progression from a mood sequence
        """
        action = params.action.lower().strip()

        if action == "create":
            if not params.scenes:
                return json.dumps({"error": "scenes list is required"})
            script = create_color_script(params.scenes)
            return json.dumps({
                "action": "create",
                "scene_count": len(script),
                "color_script": script,
            }, indent=2)

        elif action == "assign_mood":
            desc = params.scene_description or ""
            mood = assign_mood(desc)
            palette = MOOD_PALETTES.get(mood, MOOD_PALETTES["neutral"])
            return json.dumps({
                "action": "assign_mood",
                "description": desc,
                "mood": mood,
                "palette": palette,
            }, indent=2)

        elif action == "color_arc":
            if not params.moods:
                return json.dumps({"error": "moods list is required"})
            arc = generate_color_arc(params.moods)
            return json.dumps({
                "action": "color_arc",
                "mood_count": len(arc),
                "arc": arc,
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["create", "assign_mood", "color_arc"],
            })
