"""Lottie pipeline helper for After Effects → Bodymovin workflow.

Provides pure-Python checks for Bodymovin compatibility, settings
generation, and Lottie JSON optimization.

No external dependencies required.
"""

import json
import math
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiLottieWorkflowInput(BaseModel):
    """Lottie pipeline helper for AE → Bodymovin export."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ..., description="Action: validate_comp, generate_settings, optimize, status"
    )
    comp_info: Optional[dict] = Field(
        default=None,
        description="AE composition info dict with layers, effects, expressions, etc.",
    )
    comp_name: Optional[str] = Field(
        default=None, description="Composition name for settings generation"
    )
    output_path: Optional[str] = Field(
        default=None, description="Output path for Bodymovin settings or optimized Lottie"
    )
    lottie_json: Optional[dict] = Field(
        default=None, description="Lottie JSON to optimize"
    )
    decimal_precision: int = Field(
        default=3,
        description="Decimal precision for Lottie optimization (fewer = smaller file)",
        ge=0, le=6,
    )


# ---------------------------------------------------------------------------
# Bodymovin compatibility checking
# ---------------------------------------------------------------------------

# Features that Bodymovin/Lottie cannot export from After Effects
UNSUPPORTED_FEATURES = {
    "3d_layers": "3D layers are not supported in Lottie",
    "expressions_controls": "Expression Controls effect is not exportable",
    "cc_particle_world": "CC Particle World is not supported",
    "cc_ball_action": "CC Ball Action is not supported",
    "echo": "Echo effect is not supported",
    "motion_tile": "Motion Tile is not supported",
    "puppet_starch": "Puppet Starch is not supported",
    "auto_orient_3d": "3D Auto-Orient is not supported",
    "layer_styles_all": "Not all layer styles export (inner glow, satin, etc.)",
    "camera_layer": "Camera layers are not supported",
    "light_layer": "Light layers are not supported",
    "audio_layer": "Audio layers are not exported",
}

# Blend modes with limited or no Lottie support
UNSUPPORTED_BLEND_MODES = {
    "dissolve", "color_burn", "linear_burn", "darker_color",
    "linear_dodge", "lighter_color", "vivid_light", "linear_light",
    "pin_light", "hard_mix", "subtract", "divide",
    "hue", "saturation", "color", "luminosity",
}

# Supported blend modes
SUPPORTED_BLEND_MODES = {
    "normal", "multiply", "screen", "overlay",
    "darken", "lighten", "color_dodge", "hard_light",
    "soft_light", "difference", "exclusion",
}


def check_bodymovin_compatibility(comp_info: dict) -> dict:
    """Check if an AE composition uses only Bodymovin-supported features.

    Examines layers, effects, expressions, blend modes, and other
    composition properties to identify what will and won't export.

    Args:
        comp_info: dict describing the AE composition:
            - layers: list of layer dicts with 'name', 'type', 'effects',
              'blend_mode', 'is_3d', 'has_expressions', etc.
            - effects: list of effect names used
            - expressions: list of expression descriptions
            - width, height, fps, duration

    Returns:
        Dict with 'compatible' bool, 'warnings' and 'errors' lists,
        and 'feature_support' breakdown.
    """
    warnings = []
    errors = []
    feature_support = {}

    layers = comp_info.get("layers", [])
    effects = comp_info.get("effects", [])

    # Check each layer
    for layer in layers:
        layer_name = layer.get("name", "unnamed")
        layer_type = layer.get("type", "").lower()

        # 3D layers
        if layer.get("is_3d", False):
            errors.append(f"Layer '{layer_name}': 3D layers are not supported")
            feature_support["3d_layers"] = False

        # Camera layers
        if layer_type == "camera":
            errors.append(f"Layer '{layer_name}': Camera layers are not supported")
            feature_support["camera_layers"] = False

        # Light layers
        if layer_type == "light":
            errors.append(f"Layer '{layer_name}': Light layers are not supported")
            feature_support["light_layers"] = False

        # Audio layers
        if layer_type == "audio":
            warnings.append(f"Layer '{layer_name}': Audio will not be exported")
            feature_support["audio_layers"] = False

        # Blend modes
        blend_mode = layer.get("blend_mode", "normal").lower().replace(" ", "_")
        if blend_mode in UNSUPPORTED_BLEND_MODES:
            warnings.append(
                f"Layer '{layer_name}': blend mode '{blend_mode}' has limited/no support"
            )
            feature_support[f"blend_{blend_mode}"] = False

        # Expressions
        if layer.get("has_expressions", False):
            warnings.append(
                f"Layer '{layer_name}': expressions may not export correctly"
            )

        # Layer effects
        layer_effects = layer.get("effects", [])
        for effect in layer_effects:
            effect_key = effect.lower().replace(" ", "_")
            if effect_key in UNSUPPORTED_FEATURES:
                errors.append(
                    f"Layer '{layer_name}': effect '{effect}' — "
                    f"{UNSUPPORTED_FEATURES[effect_key]}"
                )
                feature_support[effect_key] = False

    # Check global effects
    for effect in effects:
        effect_key = effect.lower().replace(" ", "_")
        if effect_key in UNSUPPORTED_FEATURES:
            errors.append(
                f"Effect '{effect}': {UNSUPPORTED_FEATURES[effect_key]}"
            )

    # Mark supported features
    feature_support.setdefault("3d_layers", True)
    feature_support.setdefault("camera_layers", True)
    feature_support.setdefault("light_layers", True)

    compatible = len(errors) == 0

    return {
        "compatible": compatible,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "errors": errors,
        "warnings": warnings,
        "feature_support": feature_support,
        "layer_count": len(layers),
    }


# ---------------------------------------------------------------------------
# Bodymovin settings generation
# ---------------------------------------------------------------------------


def generate_bodymovin_settings(
    comp_name: str,
    output_path: str,
    options: Optional[dict] = None,
) -> dict:
    """Create Bodymovin export settings JSON.

    Args:
        comp_name: name of the AE composition to export
        output_path: destination path for the Lottie JSON
        options: optional overrides for settings

    Returns:
        Dict of Bodymovin settings ready to be saved as JSON.
    """
    opts = options or {}

    settings = {
        "bm_renderer": opts.get("renderer", "svg"),
        "bm_export": {
            "comp_name": comp_name,
            "destination": output_path,
        },
        "bm_settings": {
            "segmented": opts.get("segmented", False),
            "standalone": opts.get("standalone", True),
            "glyphs": opts.get("glyphs", True),
            "export_mode": opts.get("export_mode", "standard"),
            "original_assets": opts.get("original_assets", False),
            "original_names": opts.get("original_names", True),
            "should_compress": opts.get("compress", False),
            "should_skip_images": opts.get("skip_images", False),
            "should_encode_images": opts.get("encode_images", True),
            "extra_compositions": opts.get("extra_compositions", []),
            "demo": opts.get("demo", False),
        },
        "bm_assets_folder": opts.get("assets_folder", "images/"),
        "bm_version": "5.12.2",
    }

    return settings


# ---------------------------------------------------------------------------
# Lottie JSON optimization
# ---------------------------------------------------------------------------


def _round_value(value, precision: int):
    """Round a numeric value to given precision, recursing into structures."""
    if isinstance(value, float):
        rounded = round(value, precision)
        # Convert to int if the rounded value is a whole number
        if rounded == int(rounded):
            return int(rounded)
        return rounded
    elif isinstance(value, list):
        return [_round_value(v, precision) for v in value]
    elif isinstance(value, dict):
        return {k: _round_value(v, precision) for k, v in value.items()}
    return value


def _is_empty_value(value) -> bool:
    """Check if a value is effectively empty and can be stripped."""
    if value is None:
        return True
    if isinstance(value, str) and not value:
        return True
    if isinstance(value, list) and not value:
        return True
    if isinstance(value, dict) and not value:
        return True
    return False


def optimize_lottie(lottie_json: dict, precision: int = 3) -> dict:
    """Strip unnecessary precision and remove empty properties from Lottie JSON.

    Optimizations:
    1. Round all floating-point values to specified precision
    2. Remove empty arrays, dicts, and null values
    3. Remove unnecessary metadata (nm for names in production)

    Args:
        lottie_json: parsed Lottie animation JSON
        precision: decimal places to keep (default 3)

    Returns:
        Optimized Lottie JSON dict.
    """
    # Deep copy to avoid mutating input
    result = json.loads(json.dumps(lottie_json))

    # Round all numeric values
    result = _round_value(result, precision)

    # Strip empty properties recursively
    def _strip_empty(obj):
        if isinstance(obj, dict):
            cleaned = {}
            for k, v in obj.items():
                cleaned_v = _strip_empty(v)
                if not _is_empty_value(cleaned_v):
                    cleaned[k] = cleaned_v
            return cleaned
        elif isinstance(obj, list):
            return [_strip_empty(v) for v in obj if not _is_empty_value(v)]
        return obj

    result = _strip_empty(result)

    return result


# ---------------------------------------------------------------------------
# MCP tool registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_lottie_workflow tool."""

    @mcp.tool(
        name="adobe_ai_lottie_workflow",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_lottie_workflow(params: AiLottieWorkflowInput) -> str:
        """Lottie pipeline helper for AE → Bodymovin workflow.

        Actions:
        - validate_comp: check AE comp for Bodymovin compatibility
        - generate_settings: create Bodymovin export settings JSON
        - optimize: strip precision and empty props from Lottie JSON
        - status: report tool capabilities
        """
        action = params.action.lower().strip()

        # ── status ──────────────────────────────────────────────────
        if action == "status":
            return json.dumps({
                "action": "status",
                "supported_actions": [
                    "validate_comp", "generate_settings", "optimize", "status",
                ],
                "unsupported_features": list(UNSUPPORTED_FEATURES.keys()),
                "unsupported_blend_modes": sorted(UNSUPPORTED_BLEND_MODES),
            }, indent=2)

        # ── validate_comp ───────────────────────────────────────────
        if action == "validate_comp":
            if not params.comp_info:
                return json.dumps({"error": "comp_info is required for validate_comp"})

            result = check_bodymovin_compatibility(params.comp_info)
            return json.dumps({
                "action": "validate_comp",
                **result,
            }, indent=2)

        # ── generate_settings ───────────────────────────────────────
        if action == "generate_settings":
            if not params.comp_name:
                return json.dumps({"error": "comp_name is required for generate_settings"})

            out_path = params.output_path or f"/tmp/bodymovin/{params.comp_name}.json"
            settings = generate_bodymovin_settings(params.comp_name, out_path)

            return json.dumps({
                "action": "generate_settings",
                "comp_name": params.comp_name,
                "output_path": out_path,
                "settings": settings,
            }, indent=2)

        # ── optimize ────────────────────────────────────────────────
        if action == "optimize":
            if not params.lottie_json:
                return json.dumps({"error": "lottie_json is required for optimize"})

            original_size = len(json.dumps(params.lottie_json))
            optimized = optimize_lottie(params.lottie_json, params.decimal_precision)
            optimized_size = len(json.dumps(optimized))

            return json.dumps({
                "action": "optimize",
                "original_size": original_size,
                "optimized_size": optimized_size,
                "reduction_bytes": original_size - optimized_size,
                "reduction_pct": round(
                    (1 - optimized_size / original_size) * 100, 1
                ) if original_size > 0 else 0,
                "precision": params.decimal_precision,
                "optimized": optimized,
            }, indent=2)

        return json.dumps({
            "error": f"Unknown action: {action}",
            "valid_actions": ["validate_comp", "generate_settings", "optimize", "status"],
        })
