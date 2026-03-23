"""Add text annotations to storyboard panels.

Supports dialogue, action descriptions, SFX, and notes with distinct
formatting for each type. Text data is stored in the rig file under
"panel_texts" for persistence across tool calls.
"""

import json

from adobe_mcp.engine import _async_run_jsx
from adobe_mcp.jsx.templates import escape_jsx_string
from adobe_mcp.apps.illustrator.models import AiPanelTextInput
from adobe_mcp.apps.illustrator.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Text formatting helpers (pure Python, testable without JSX)
# ---------------------------------------------------------------------------


def _format_dialogue(speaker: str | None, text: str) -> str:
    """Format dialogue text as 'SPEAKER: "text"'.

    If no speaker is provided, just wraps in quotes.
    """
    if speaker:
        return f'{speaker.upper()}: "{text}"'
    return f'"{text}"'


def _format_action(text: str) -> str:
    """Format action description text (italic style marker).

    Returns the text as-is — italic styling is applied via JSX.
    """
    return text


def _format_sfx(text: str) -> str:
    """Format SFX text as bold uppercase."""
    return text.upper()


def _format_note(text: str) -> str:
    """Format note text (small, gray — styling via JSX)."""
    return text


def format_panel_text(text_type: str, text: str, speaker: str | None = None) -> str:
    """Format text according to its type.

    Args:
        text_type: One of 'dialogue', 'action', 'sfx', 'note'.
        text: The raw text content.
        speaker: Speaker name (only used for dialogue).

    Returns:
        Formatted text string.
    """
    text_type = text_type.lower().strip()
    if text_type == "dialogue":
        return _format_dialogue(speaker, text)
    elif text_type == "action":
        return _format_action(text)
    elif text_type == "sfx":
        return _format_sfx(text)
    elif text_type == "note":
        return _format_note(text)
    return text


def _ensure_panel_texts(rig: dict) -> dict:
    """Ensure the rig has a panel_texts structure."""
    if "panel_texts" not in rig:
        rig["panel_texts"] = {}
    return rig


def _jsx_text_style(text_type: str) -> str:
    """Return JSX code fragment for text styling based on type.

    This is the style configuration applied after creating the text frame.
    Variable 'tf' must be in scope.
    """
    if text_type == "dialogue":
        return """
        tf.textRange.characterAttributes.size = 10;
        var clr = new RGBColor();
        clr.red = 30; clr.green = 30; clr.blue = 30;
        tf.textRange.characterAttributes.fillColor = clr;
        """
    elif text_type == "action":
        return """
        tf.textRange.characterAttributes.size = 9;
        var clr = new RGBColor();
        clr.red = 50; clr.green = 50; clr.blue = 80;
        tf.textRange.characterAttributes.fillColor = clr;
        """
    elif text_type == "sfx":
        return """
        tf.textRange.characterAttributes.size = 12;
        var clr = new RGBColor();
        clr.red = 200; clr.green = 50; clr.blue = 50;
        tf.textRange.characterAttributes.fillColor = clr;
        """
    else:  # note
        return """
        tf.textRange.characterAttributes.size = 7;
        var clr = new RGBColor();
        clr.red = 140; clr.green = 140; clr.blue = 140;
        tf.textRange.characterAttributes.fillColor = clr;
        """


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_panel_text tool."""

    @mcp.tool(
        name="adobe_ai_panel_text",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_panel_text(params: AiPanelTextInput) -> str:
        """Add, clear, or list text annotations on storyboard panels.

        Text types: dialogue (quoted with speaker), action (italic),
        sfx (bold uppercase), note (small gray).
        """
        # Panel texts are stored in a generic rig keyed by "storyboard"
        # Use a fixed character name for storyboard-level data
        rig = _load_rig("storyboard")
        rig = _ensure_panel_texts(rig)
        action = params.action.lower().strip()

        panel_key = str(params.panel_number)

        # ── set ───────────────────────────────────────────────────────
        if action == "set":
            if not params.text:
                return json.dumps({
                    "error": "text parameter is required for set action.",
                })

            formatted = format_panel_text(params.text_type, params.text, params.speaker)
            escaped = escape_jsx_string(formatted)

            # Store in rig
            if panel_key not in rig["panel_texts"]:
                rig["panel_texts"][panel_key] = []

            # Add or replace text of the same type for this panel
            existing = [t for t in rig["panel_texts"][panel_key]
                        if t.get("type") != params.text_type]
            existing.append({
                "type": params.text_type,
                "raw_text": params.text,
                "speaker": params.speaker,
                "formatted": formatted,
            })
            rig["panel_texts"][panel_key] = existing
            _save_rig("storyboard", rig)

            # Place text in AI via JSX
            text_type = params.text_type.lower().strip()
            style_jsx = _jsx_text_style(text_type)
            item_name = f"panel_{params.panel_number}_text_{text_type}"

            jsx = f"""(function() {{
    var doc = app.activeDocument;

    // Find the panel layer or use active layer
    var targetLayer = doc.activeLayer;
    for (var i = 0; i < doc.layers.length; i++) {{
        if (doc.layers[i].name === "Panel_{params.panel_number}") {{
            targetLayer = doc.layers[i];
            break;
        }}
    }}

    // Remove existing text of same type if present
    try {{
        var existing = targetLayer.textFrames.getByName("{item_name}");
        if (existing) existing.remove();
    }} catch(e) {{}}

    // Determine position based on panel frame
    var posX = 10;
    var posY = -10;
    try {{
        var frame = targetLayer.pathItems.getByName("panel_{params.panel_number}_frame");
        if (frame) {{
            var b = frame.geometricBounds;
            posX = b[0] + 8;
            // Stack text types vertically below the panel
            var typeOffset = {{"dialogue": 0, "action": 16, "sfx": 32, "note": 48}};
            var offset = typeOffset["{text_type}"] || 0;
            posY = b[3] + 16 + offset;
        }}
    }} catch(e) {{}}

    var tf = targetLayer.textFrames.add();
    tf.contents = "{escaped}";
    tf.name = "{item_name}";
    tf.position = [posX, posY];
    {style_jsx}

    return JSON.stringify({{
        panel: {params.panel_number},
        type: "{text_type}",
        name: "{item_name}",
        formatted: "{escaped}"
    }});
}})();"""

            result = await _async_run_jsx("illustrator", jsx)
            if not result.get("success", False):
                return json.dumps({"error": result.get("stderr", "Unknown error")})

            return json.dumps({
                "action": "set",
                "panel_number": params.panel_number,
                "text_type": params.text_type,
                "formatted": formatted,
            }, indent=2)

        # ── clear ─────────────────────────────────────────────────────
        elif action == "clear":
            removed_types = []
            if panel_key in rig["panel_texts"]:
                removed_types = [t["type"] for t in rig["panel_texts"][panel_key]]
                del rig["panel_texts"][panel_key]
                _save_rig("storyboard", rig)

            # Remove text items from AI
            if removed_types:
                names_to_remove = [
                    f"panel_{params.panel_number}_text_{t}" for t in removed_types
                ]
                names_js = json.dumps(names_to_remove)
                jsx = f"""(function() {{
    var doc = app.activeDocument;
    var names = {names_js};
    var removed = [];
    for (var n = 0; n < names.length; n++) {{
        for (var l = 0; l < doc.layers.length; l++) {{
            try {{
                var item = doc.layers[l].textFrames.getByName(names[n]);
                if (item) {{
                    item.remove();
                    removed.push(names[n]);
                    break;
                }}
            }} catch(e) {{}}
        }}
    }}
    return JSON.stringify({{removed: removed}});
}})();"""
                await _async_run_jsx("illustrator", jsx)

            return json.dumps({
                "action": "clear",
                "panel_number": params.panel_number,
                "removed_types": removed_types,
            }, indent=2)

        # ── list ──────────────────────────────────────────────────────
        elif action == "list":
            all_texts = rig.get("panel_texts", {})

            # If a specific panel is requested, filter to it
            if panel_key in all_texts:
                return json.dumps({
                    "action": "list",
                    "panel_number": params.panel_number,
                    "texts": all_texts[panel_key],
                }, indent=2)

            # Return all panels
            return json.dumps({
                "action": "list",
                "all_panels": {
                    k: v for k, v in all_texts.items()
                },
                "total_panels_with_text": len(all_texts),
            }, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["set", "clear", "list"],
            })
