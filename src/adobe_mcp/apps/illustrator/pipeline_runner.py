"""Chain named tool sequences into reusable pipelines.

Define a sequence of steps (each referencing a tool name and params),
then run them in order, passing outputs between steps. Pipelines can
be saved to disk and reloaded for repeatable workflows.

Pure Python implementation.
"""

import copy
import json
import os
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiPipelineRunnerInput(BaseModel):
    """Chain named tool sequences into reusable pipelines."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: define_pipeline, run_pipeline, list_pipelines, save_pipeline, load_pipeline",
    )
    name: Optional[str] = Field(
        default=None,
        description="Pipeline name (required for define/run/save)",
    )
    steps: Optional[list[dict]] = Field(
        default=None,
        description='Steps list for define_pipeline: [{"tool": "...", "params": {...}}, ...]',
    )
    overrides: Optional[dict] = Field(
        default=None,
        description="Param overrides for run_pipeline, keyed by step index or tool name",
    )
    path: Optional[str] = Field(
        default=None,
        description="File path for save_pipeline / load_pipeline",
    )


# ---------------------------------------------------------------------------
# Built-in pipelines
# ---------------------------------------------------------------------------

BUILTIN_PIPELINES: dict[str, list[dict]] = {
    "character_setup": [
        {"tool": "detect_landmarks", "params": {"auto": True}},
        {"tool": "compute_axis", "params": {"from": "head_top", "to": "chin"}},
        {"tool": "reference_underlay", "params": {}},
    ],
    "panel_setup": [
        {"tool": "storyboard_template", "params": {"preset": "standard"}},
    ],
    "full_rig": [
        {"tool": "segment_parts", "params": {"n_clusters": 5}},
        {"tool": "detect_connections", "params": {}},
        {"tool": "build_hierarchy", "params": {}},
        {"tool": "auto_pivots", "params": {}},
    ],
}


# ---------------------------------------------------------------------------
# In-memory pipeline storage
# ---------------------------------------------------------------------------

_pipelines: dict[str, list[dict]] = {}


def _get_pipelines() -> dict[str, list[dict]]:
    """Return the merged built-in + user-defined pipelines dict."""
    merged = dict(BUILTIN_PIPELINES)
    merged.update(_pipelines)
    return merged


# ---------------------------------------------------------------------------
# Pipeline step executor
# ---------------------------------------------------------------------------


class StepResult:
    """Result from executing a single pipeline step."""
    __slots__ = ("tool", "params", "output", "success", "error")

    def __init__(self, tool: str, params: dict):
        self.tool = tool
        self.params = params
        self.output: Any = None
        self.success: bool = False
        self.error: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "tool": self.tool,
            "params": self.params,
            "output": self.output,
            "success": self.success,
            "error": self.error,
        }


def _execute_step(step: dict, previous_output: Any = None) -> StepResult:
    """Execute a single pipeline step.

    The step is a simulation -- we record what would be called and
    pass through params. In a real MCP context, each tool call would
    be dispatched to the actual tool handler.

    Output propagation: if a step's params contain the key "$prev",
    it is replaced with the previous step's output.

    Args:
        step: dict with "tool" and "params" keys
        previous_output: output from the previous step (if any)

    Returns:
        StepResult with the execution outcome.
    """
    tool = step.get("tool", "unknown")
    params = copy.deepcopy(step.get("params", {}))

    # Inject previous output where $prev is referenced
    for key, value in list(params.items()):
        if value == "$prev":
            params[key] = previous_output

    result = StepResult(tool, params)

    try:
        # In pipeline context, we record the step as a dispatch spec.
        # The actual execution is handled by the MCP tool dispatcher.
        result.output = {
            "dispatched": True,
            "tool": tool,
            "params": params,
        }
        result.success = True
    except Exception as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# Pure Python API
# ---------------------------------------------------------------------------


def define_pipeline(name: str, steps: list[dict]) -> dict:
    """Define a named pipeline from a list of steps.

    Each step should be: {"tool": "tool_name", "params": {...}}

    Args:
        name: pipeline identifier
        steps: ordered list of step dicts

    Returns:
        Confirmation dict with pipeline name and step count.
    """
    if not name:
        return {"error": "Pipeline name is required"}
    if not steps or not isinstance(steps, list):
        return {"error": "Steps must be a non-empty list"}

    # Validate each step has a tool key
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or "tool" not in step:
            return {"error": f"Step {i} must be a dict with a 'tool' key"}

    _pipelines[name] = steps
    return {
        "pipeline": name,
        "steps": len(steps),
        "tools": [s["tool"] for s in steps],
    }


def run_pipeline(name: str, overrides: Optional[dict] = None) -> dict:
    """Execute a named pipeline, running steps sequentially.

    Each step's output is available to the next step via the $prev
    param substitution.

    Args:
        name: pipeline name (user-defined or built-in)
        overrides: optional param overrides keyed by step index (int) or tool name

    Returns:
        Dict with pipeline name, step results, and overall status.
    """
    all_pipelines = _get_pipelines()
    if name not in all_pipelines:
        return {"error": f"Pipeline '{name}' not found. Available: {list(all_pipelines.keys())}"}

    steps = copy.deepcopy(all_pipelines[name])
    overrides = overrides or {}

    # Apply overrides
    for i, step in enumerate(steps):
        # Override by index (string key from JSON)
        idx_key = str(i)
        if idx_key in overrides:
            step["params"].update(overrides[idx_key])
        elif i in overrides:
            step["params"].update(overrides[i])
        # Override by tool name
        tool_name = step.get("tool", "")
        if tool_name in overrides:
            step["params"].update(overrides[tool_name])

    # Execute steps sequentially
    results = []
    previous_output = None
    all_success = True

    for step in steps:
        step_result = _execute_step(step, previous_output)
        results.append(step_result.to_dict())
        previous_output = step_result.output
        if not step_result.success:
            all_success = False
            break  # Stop pipeline on failure

    return {
        "pipeline": name,
        "steps_run": len(results),
        "steps_total": len(steps),
        "success": all_success,
        "results": results,
    }


def list_pipelines() -> dict:
    """List all available pipelines (built-in + user-defined).

    Returns:
        Dict with pipeline names and their step counts.
    """
    all_pipelines = _get_pipelines()
    return {
        "pipelines": {
            name: {
                "steps": len(steps),
                "tools": [s.get("tool", "unknown") for s in steps],
                "builtin": name in BUILTIN_PIPELINES,
            }
            for name, steps in all_pipelines.items()
        },
        "total": len(all_pipelines),
    }


def save_pipeline(name: str, path: str) -> dict:
    """Save a pipeline definition to a JSON file.

    Args:
        name: pipeline name to save
        path: filesystem path for the output JSON

    Returns:
        Confirmation dict or error.
    """
    all_pipelines = _get_pipelines()
    if name not in all_pipelines:
        return {"error": f"Pipeline '{name}' not found"}

    data = {
        "name": name,
        "steps": all_pipelines[name],
    }

    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2)

    return {"saved": path, "pipeline": name, "steps": len(data["steps"])}


def load_pipeline(path: str) -> dict:
    """Load a pipeline definition from a JSON file.

    Args:
        path: filesystem path to the pipeline JSON

    Returns:
        Confirmation dict with loaded pipeline name and steps.
    """
    if not os.path.isfile(path):
        return {"error": f"File not found: {path}"}

    with open(path) as f:
        data = json.load(f)

    name = data.get("name")
    steps = data.get("steps")

    if not name or not steps:
        return {"error": "Invalid pipeline file: must contain 'name' and 'steps'"}

    _pipelines[name] = steps
    return {
        "loaded": name,
        "steps": len(steps),
        "tools": [s.get("tool", "unknown") for s in steps],
    }


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_pipeline_runner tool."""

    @mcp.tool(
        name="adobe_ai_pipeline_runner",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": False,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_pipeline_runner(params: AiPipelineRunnerInput) -> str:
        """Chain named tool sequences into reusable pipelines.

        Actions:
        - define_pipeline: create a named sequence of steps
        - run_pipeline: execute a pipeline with optional overrides
        - list_pipelines: show all available pipelines
        - save_pipeline: persist a pipeline to JSON
        - load_pipeline: load a pipeline from JSON
        """
        action = params.action.lower().strip()

        if action == "define_pipeline":
            if not params.name or not params.steps:
                return json.dumps({"error": "define_pipeline requires name and steps"})
            return json.dumps(define_pipeline(params.name, params.steps))

        elif action == "run_pipeline":
            if not params.name:
                return json.dumps({"error": "run_pipeline requires a pipeline name"})
            return json.dumps(run_pipeline(params.name, params.overrides))

        elif action == "list_pipelines":
            return json.dumps(list_pipelines())

        elif action == "save_pipeline":
            if not params.name or not params.path:
                return json.dumps({"error": "save_pipeline requires name and path"})
            return json.dumps(save_pipeline(params.name, params.path))

        elif action == "load_pipeline":
            if not params.path:
                return json.dumps({"error": "load_pipeline requires a path"})
            return json.dumps(load_pipeline(params.path))

        else:
            return json.dumps({"error": f"Unknown action: {action}"})
