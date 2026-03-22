"""Design Token System — define and apply consistent design vocabularies.

Design tokens are named values for colors, typography, spacing, and effects
that can be referenced by name across all Adobe tools. Instead of specifying
`fill_r=255, fill_g=0, fill_b=100` everywhere, define a token `color.primary`
once and reference it by name.

This enables:
1. Consistent design across operations (no color drift)
2. Rapid theme switching (change token values, everything updates)
3. Design system enforcement (tokens = your brand guidelines)
4. Compact tool calls (token names instead of raw values)

Architecture:
    - Tokens are stored in a global TokenRegistry (per server process)
    - Token sets can be saved to / loaded from JSON files
    - Tools can resolve token references via `resolve_tokens(params)`
    - The adobe_design_tokens tool lets the LLM manage tokens interactively
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class DesignToken:
    """A single design token — a named, typed design value."""
    name: str
    value: Any
    category: str  # color, typography, spacing, effect
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "value": self.value,
            "category": self.category,
            "description": self.description,
        }


class TokenRegistry:
    """Global design token registry. One per MCP server process.

    Usage:
        from adobe_mcp.tokens import tokens

        # Define tokens
        tokens.set("color.primary", {"r": 255, "g": 0, "b": 100}, category="color")
        tokens.set("color.bg", {"r": 10, "g": 10, "b": 10}, category="color")
        tokens.set("type.heading", {"font": "HelveticaNeue-Bold", "size": 72}, category="typography")
        tokens.set("spacing.margin", 40, category="spacing")

        # Resolve tokens in params
        params = {"fill_r": "$color.primary.r", "fill_g": "$color.primary.g", "fill_b": "$color.primary.b"}
        resolved = tokens.resolve(params)
        # -> {"fill_r": 255, "fill_g": 0, "fill_b": 100}
    """

    def __init__(self) -> None:
        self._tokens: dict[str, DesignToken] = {}

    def set(self, name: str, value: Any, category: str = "custom", description: str = "") -> None:
        """Set a design token value."""
        self._tokens[name] = DesignToken(
            name=name, value=value, category=category, description=description
        )

    def get(self, name: str) -> Any | None:
        """Get a token value by name. Returns None if not found."""
        token = self._tokens.get(name)
        return token.value if token else None

    def get_nested(self, path: str) -> Any | None:
        """Get a nested value from a token using dot notation.

        Examples:
            get_nested("color.primary.r") -> looks up token "color.primary", returns value["r"]
            get_nested("spacing.margin") -> returns the token value directly if not a dict
        """
        parts = path.split(".")

        # Try progressively longer prefixes
        for i in range(len(parts), 0, -1):
            token_name = ".".join(parts[:i])
            token = self._tokens.get(token_name)
            if token is not None:
                remaining = parts[i:]
                value = token.value
                for key in remaining:
                    if isinstance(value, dict):
                        value = value.get(key)
                    else:
                        return None
                return value
        return None

    def resolve(self, params: dict[str, Any]) -> dict[str, Any]:
        """Resolve token references in parameter dict.

        Token references start with '$': "$color.primary.r" -> 255
        Non-token values pass through unchanged.
        """
        resolved = {}
        for key, value in params.items():
            if isinstance(value, str) and value.startswith("$"):
                token_path = value[1:]  # Strip $
                token_value = self.get_nested(token_path)
                if token_value is not None:
                    resolved[key] = token_value
                else:
                    resolved[key] = value  # Keep original if not found
            else:
                resolved[key] = value
        return resolved

    def list_tokens(self, category: str | None = None) -> list[dict]:
        """List all tokens, optionally filtered by category."""
        results = []
        for token in self._tokens.values():
            if category and token.category != category:
                continue
            results.append(token.to_dict())
        return results

    def save(self, path: str | Path) -> None:
        """Save all tokens to a JSON file."""
        path = Path(path)
        data = {
            "version": 1,
            "tokens": [t.to_dict() for t in self._tokens.values()],
        }
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2))

    def load(self, path: str | Path) -> int:
        """Load tokens from a JSON file. Returns number loaded."""
        path = Path(path)
        if not path.exists():
            return 0
        data = json.loads(path.read_text())
        count = 0
        for t in data.get("tokens", []):
            self.set(
                name=t["name"],
                value=t["value"],
                category=t.get("category", "custom"),
                description=t.get("description", ""),
            )
            count += 1
        return count

    def clear(self) -> None:
        """Clear all tokens."""
        self._tokens.clear()

    def apply_preset(self, preset_name: str) -> str:
        """Apply a built-in design preset. Returns description of what was set."""
        presets = {
            "void": {
                "description": "VOID engine aesthetic — dark, technical, high contrast",
                "tokens": {
                    "color.bg": ({"r": 10, "g": 10, "b": 10}, "color", "Background — near-black"),
                    "color.primary": ({"r": 255, "g": 0, "b": 100}, "color", "Primary — hot pink"),
                    "color.secondary": ({"r": 0, "g": 200, "b": 255}, "color", "Secondary — electric cyan"),
                    "color.accent": ({"r": 255, "g": 220, "b": 0}, "color", "Accent — warning yellow"),
                    "color.text": ({"r": 230, "g": 230, "b": 230}, "color", "Text — off-white"),
                    "type.heading": ({"font": "HelveticaNeue-Bold", "size": 72}, "typography", "Heading"),
                    "type.subheading": ({"font": "HelveticaNeue-Medium", "size": 36}, "typography", "Subheading"),
                    "type.body": ({"font": "InputMono-Regular", "size": 11}, "typography", "Body/code"),
                    "type.label": ({"font": "HelveticaNeue-Light", "size": 8}, "typography", "Labels"),
                    "spacing.margin": (40, "spacing", "Outer margin"),
                    "spacing.gutter": (20, "spacing", "Column gutter"),
                    "spacing.padding": (12, "spacing", "Inner padding"),
                    "effect.stroke_width": (0.5, "effect", "Default stroke weight"),
                    "effect.corner_radius": (2, "effect", "Default corner radius"),
                },
            },
            "minimal": {
                "description": "Clean minimalist — white space, subtle grays, sharp typography",
                "tokens": {
                    "color.bg": ({"r": 255, "g": 255, "b": 255}, "color", "Background — pure white"),
                    "color.primary": ({"r": 20, "g": 20, "b": 20}, "color", "Primary — near-black"),
                    "color.secondary": ({"r": 120, "g": 120, "b": 120}, "color", "Secondary — mid gray"),
                    "color.accent": ({"r": 0, "g": 100, "b": 255}, "color", "Accent — clean blue"),
                    "color.text": ({"r": 30, "g": 30, "b": 30}, "color", "Text — dark gray"),
                    "type.heading": ({"font": "HelveticaNeue-Light", "size": 48}, "typography", "Heading"),
                    "type.body": ({"font": "Georgia", "size": 14}, "typography", "Body text"),
                    "spacing.margin": (60, "spacing", "Generous outer margin"),
                    "spacing.gutter": (30, "spacing", "Column gutter"),
                },
            },
            "brutalist": {
                "description": "Brutalist web aesthetic — raw, bold, unfinished",
                "tokens": {
                    "color.bg": ({"r": 245, "g": 245, "b": 230}, "color", "Background — off-white"),
                    "color.primary": ({"r": 0, "g": 0, "b": 0}, "color", "Primary — pure black"),
                    "color.accent": ({"r": 255, "g": 0, "b": 0}, "color", "Accent — raw red"),
                    "color.text": ({"r": 0, "g": 0, "b": 0}, "color", "Text — black"),
                    "type.heading": ({"font": "Courier-Bold", "size": 96}, "typography", "Heading — oversized mono"),
                    "type.body": ({"font": "Times-Roman", "size": 18}, "typography", "Body — serif"),
                    "spacing.margin": (20, "spacing", "Tight margin"),
                    "effect.stroke_width": (3, "effect", "Heavy stroke"),
                    "effect.border": (2, "effect", "Border width"),
                },
            },
        }

        preset = presets.get(preset_name)
        if not preset:
            available = ", ".join(presets.keys())
            return f"Unknown preset '{preset_name}'. Available: {available}"

        for name, (value, category, desc) in preset["tokens"].items():
            self.set(name, value, category=category, description=desc)

        return f"Applied '{preset_name}' preset: {preset['description']} ({len(preset['tokens'])} tokens set)"

    @property
    def count(self) -> int:
        return len(self._tokens)


# ── Global singleton ──────────────────────────────────────────────────
tokens = TokenRegistry()
