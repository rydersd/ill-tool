"""After Effects integration smoke tests — requires live Adobe After Effects.

Run with: uv run pytest tests/test_ae_smoke.py -v
Skip with: uv run pytest tests/ -k "not ae" -v
"""

import inspect
import json
import subprocess

import pytest

from adobe_mcp.server import mcp


def _ae_is_running() -> bool:
    """Check if After Effects is running via process list."""
    try:
        result = subprocess.run(
            ["pgrep", "-x", "After Effects"],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


pytestmark = [
    pytest.mark.ae,
    pytest.mark.skipif(not _ae_is_running(), reason="After Effects is not running"),
]


# ---------------------------------------------------------------------------
# Helper: call an MCP tool by name with a params dict
# ---------------------------------------------------------------------------

async def call_tool(name: str, params_dict: dict | None = None) -> str:
    """Invoke an MCP tool function by name and return its string result.

    Looks up the tool in the FastMCP internal registry, constructs the
    Pydantic model from *params_dict*, and awaits the tool function.
    """
    tool = mcp._tool_manager._tools[name]
    sig = inspect.signature(tool.fn)
    param_types = list(sig.parameters.values())

    if param_types and params_dict is not None:
        model_cls = param_types[0].annotation
        params = model_cls(**params_dict)
        result = await tool.fn(params)
    else:
        result = await tool.fn()

    return result


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_ae_comp_creation():
    """Create a basic AE composition and verify it was created."""
    result = await call_tool("adobe_ae_comp", {
        "action": "create",
        "name": "SmokeTest_Comp",
        "width": 1920,
        "height": 1080,
        "duration": 5,
        "framerate": 24,
    })
    # Result should be JSON with the comp name
    data = json.loads(result) if isinstance(result, str) else result
    assert "error" not in str(data).lower(), f"Comp creation failed: {data}"
    assert "SmokeTest_Comp" in str(data), f"Expected comp name in result: {data}"


async def test_ae_expression_gen():
    """Create a comp with a solid layer, then apply a wiggle expression."""
    # Step 1: create a comp to work in
    await call_tool("adobe_ae_comp", {
        "action": "create",
        "name": "SmokeTest_Expr",
        "width": 1920,
        "height": 1080,
        "duration": 5,
        "framerate": 24,
    })

    # Step 2: add a solid layer to apply the expression to
    await call_tool("adobe_ae_layer", {
        "action": "add_solid",
        "comp_name": "SmokeTest_Expr",
        "layer_name": "ExprSolid",
        "color_r": 128,
        "color_g": 128,
        "color_b": 128,
        "width": 1920,
        "height": 1080,
    })

    # Step 3: apply a wiggle expression to the layer's position
    result = await call_tool("adobe_ae_expression", {
        "comp_name": "SmokeTest_Expr",
        "layer_name": "ExprSolid",
        "property_path": "Transform.Position",
        "expression": "wiggle(5, 50)",
    })
    result_lower = result.lower()
    assert "error" not in result_lower, f"Expression application failed: {result}"
    assert "expression" in result_lower or "applied" in result_lower, (
        f"Expected confirmation of expression: {result}"
    )
