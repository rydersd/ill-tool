"""Core execution engine — JSX, AppleScript, and PowerShell runners.

Also provides the JSX template engine: load_template() reads co-located .jsx files
from the calling module's directory and fills {{param}} placeholders. This separates
ExtendScript from Python — JSX becomes testable in the ExtendScript Toolkit and
editable by non-Python developers.

Execution priority:
    1. WebSocket relay (if a CEP panel is connected for the target app)
    2. osascript / PowerShell subprocess (original path, always available)

The WebSocket path is purely additive — if the relay is unavailable or the
panel disconnects mid-call, the engine silently falls back to subprocess.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, TYPE_CHECKING

from adobe_mcp.config import ADOBE_APPS, IS_MACOS, IS_WINDOWS
from adobe_mcp.jsx.templates import escape_jsx_string

if TYPE_CHECKING:
    from adobe_mcp.relay.server import RelayServer

logger = logging.getLogger("adobe_mcp.engine")


# ── WebSocket Relay Integration ─────────────────────────────────────────
# Module-level relay reference. Set by server.py at startup via set_relay().

_relay: RelayServer | None = None


def set_relay(relay: RelayServer) -> None:
    """Register the WebSocket relay server for use by the execution engine.

    Called once at startup by the server module. After this, _async_run_jsx
    will attempt the WebSocket path before falling back to subprocess.

    Args:
        relay: The active RelayServer instance.
    """
    global _relay
    _relay = relay


def get_relay() -> RelayServer | None:
    """Return the current relay server instance, or None if not set."""
    return _relay


async def _run_jsx_websocket(app: str, jsx_code: str, timeout: float = 120) -> dict:
    """Execute JSX code via the WebSocket relay to a connected CEP panel.

    This path avoids the subprocess + temp file overhead of osascript.
    The JSX code is sent directly to the panel which runs it via
    CSInterface.evalScript().

    IMPORTANT: _prepare_jsx() must be called BEFORE this function to ensure
    polyfills (e.g. JSON for Illustrator) are already injected.

    Args:
        app: Target Adobe app name.
        jsx_code: Prepared JSX code (with polyfills already injected).
        timeout: Maximum seconds to wait for result.

    Returns:
        Dict matching engine result format: {success, stdout, stderr, returncode}

    Raises:
        ConnectionError: If no relay connection exists for this app.
        Exception: Any relay communication error.
    """
    if _relay is None:
        raise ConnectionError("Relay not initialized")
    return await _relay.execute_jsx(app, jsx_code, timeout=timeout)


# ── JSX Template Engine ───────────────────────────────────────────────

# Cache loaded template file contents to avoid repeated disk reads
_template_cache: dict[str, str] = {}


def load_template(template_name: str, _caller_dir: str | Path | None = None, **params: Any) -> str:
    """Load a .jsx template file and fill {{param}} placeholders.

    The template is resolved relative to the calling module's directory,
    so `load_template("shapes.jsx", x=10)` in `apps/illustrator/shapes.py`
    loads `apps/illustrator/shapes.jsx`.

    Note: the first arg is `template_name` (not `name`) to avoid collisions
    with common JSX parameters like `name`.

    Placeholder syntax:
        {{param_name}}     — replaced with escaped string value
        {{!param_name}}    — replaced with raw value (no escaping, for numbers/code)
        {{?param_name}}    — replaced if present, removed if missing (optional)

    All values are converted to str. Numeric values passed with {{!...}} are
    inserted raw so JSX gets proper numbers, not quoted strings.

    Args:
        template_name: Template filename (e.g. "shapes.jsx").
        _caller_dir: Override for the directory to resolve templates from.
                     If None, auto-detected from the call stack.
        **params: Key-value pairs to fill into the template.

    Returns:
        The filled JSX code string, ready for execution.

    Raises:
        FileNotFoundError: If the template file doesn't exist.
        ValueError: If required placeholders remain unfilled.
    """
    # Resolve the template directory from the caller's file location
    if _caller_dir is not None:
        template_dir = Path(_caller_dir)
    else:
        caller_frame = inspect.stack()[1]
        template_dir = Path(caller_frame.filename).parent

    template_path = template_dir / template_name
    cache_key = str(template_path)

    # Load from cache or disk
    if cache_key not in _template_cache:
        if not template_path.exists():
            raise FileNotFoundError(
                f"JSX template not found: {template_path}\n"
                f"Expected co-located with caller at: {template_dir}"
            )
        _template_cache[cache_key] = template_path.read_text(encoding="utf-8")

    template = _template_cache[cache_key]

    # Pass 1: Fill optional placeholders ({{?param}}) — remove if missing
    def _fill_optional(match: re.Match) -> str:
        key = match.group(1)
        if key in params:
            return escape_jsx_string(str(params[key]))
        return ""

    template = re.sub(r"\{\{\?(\w+)\}\}", _fill_optional, template)

    # Pass 2: Fill raw placeholders ({{!param}}) — no escaping
    def _fill_raw(match: re.Match) -> str:
        key = match.group(1)
        if key in params:
            return str(params[key])
        raise ValueError(f"Missing required raw parameter '{{{{!{key}}}}}' in template '{template_name}'")

    template = re.sub(r"\{\{!(\w+)\}\}", _fill_raw, template)

    # Pass 3: Fill standard placeholders ({{param}}) — with escaping
    def _fill_standard(match: re.Match) -> str:
        key = match.group(1)
        if key in params:
            return escape_jsx_string(str(params[key]))
        raise ValueError(f"Missing required parameter '{{{{{key}}}}}' in template '{template_name}'")

    template = re.sub(r"\{\{(\w+)\}\}", _fill_standard, template)

    return template


def clear_template_cache() -> None:
    """Clear the JSX template cache. Useful for testing or live-reloading."""
    _template_cache.clear()


# ── JSX Preparation ────────────────────────────────────────────────────

def _prepare_jsx(app: str, jsx_code: str) -> str:
    """Prepare JSX code for execution, injecting polyfills as needed.

    Illustrator uses ExtendScript ES3 which lacks native JSON support.
    This auto-prepends the JSON polyfill so all Illustrator tools can
    freely use JSON.stringify() / JSON.parse().
    """
    if app == "illustrator":
        from adobe_mcp.jsx.polyfills import JSON_POLYFILL
        return JSON_POLYFILL + "\n" + jsx_code
    return jsx_code


# ── PowerShell Runner ──────────────────────────────────────────────────

def _run_powershell(script: str, timeout: int = 120) -> dict:
    """Execute a PowerShell script and return stdout/stderr/returncode."""
    try:
        result = subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout expired", "returncode": -1}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "powershell.exe not found", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


# ── AppleScript Runner ────────────────────────────────────────────────

def _run_osascript(script: str, timeout: int = 120) -> dict:
    """Execute an AppleScript via osascript and return stdout/stderr/returncode."""
    try:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout.strip(),
            "stderr": result.stderr.strip(),
            "returncode": result.returncode,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "stdout": "", "stderr": "Timeout expired", "returncode": -1}
    except FileNotFoundError:
        return {"success": False, "stdout": "", "stderr": "osascript not found", "returncode": -1}
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}


# ── AppleScript JSX Builders ──────────────────────────────────────────

def _build_applescript_for_jsx(app: str, jsx_file_path: str, timeout: int = 120) -> str:
    """Build the correct AppleScript invocation for running a JSX file in a given Adobe app.

    Each Adobe app has a different AppleScript scripting dictionary for executing scripts.
    Wraps the command in a 'with timeout' block so long-running JSX (e.g. pathfinder
    operations, image embedding) doesn't hit the default 120s AppleEvent limit.
    """
    app_info = ADOBE_APPS[app]
    proc = app_info.get("mac_process", app_info["display"])
    bundle_id = app_info.get("bundle_id")

    if app == "photoshop":
        cmd = f'do javascript of file "{jsx_file_path}"'
    elif app == "illustrator":
        cmd = f'do javascript file "{jsx_file_path}"'
    elif app == "indesign":
        # InDesign uses bundle_id addressing
        return (
            f'with timeout of {timeout} seconds\n'
            f'  tell application id "{bundle_id}" to do script (POSIX file "{jsx_file_path}") language javascript\n'
            f'end timeout'
        )
    elif app == "aftereffects":
        cmd = f'DoScriptFile "{jsx_file_path}"'
    else:
        cmd = f'do script (POSIX file "{jsx_file_path}")'

    return (
        f'with timeout of {timeout} seconds\n'
        f'  tell application "{proc}" to {cmd}\n'
        f'end timeout'
    )


# ── JSX Execution (macOS) ────────────────────────────────────────────

def _run_jsx_mac(app: str, jsx_code: str, timeout: int = 120) -> dict:
    """Execute ExtendScript JSX code in the target Adobe app via AppleScript on macOS."""
    app_info = ADOBE_APPS.get(app)
    if not app_info or not app_info["extendscript"]:
        return {"success": False, "stdout": "", "stderr": f"App '{app}' does not support ExtendScript"}

    mac_cmd = app_info.get("mac_script_cmd")
    if mac_cmd is None:
        return {"success": False, "stdout": "", "stderr": f"App '{app_info['display']}' does not support AppleScript scripting on macOS. Use file-based execution or direct app CLI."}

    # Inject polyfills (e.g. JSON for Illustrator ES3)
    jsx_code = _prepare_jsx(app, jsx_code)

    tmp_file = None
    try:
        tmp_file = tempfile.NamedTemporaryFile(suffix=".jsx", delete=False, mode="w", encoding="utf-8")
        tmp_file.write(jsx_code)
        tmp_file.close()
        temp_path = tmp_file.name

        applescript = _build_applescript_for_jsx(app, temp_path, timeout)
        return _run_osascript(applescript, timeout)
    except Exception as e:
        return {"success": False, "stdout": "", "stderr": str(e), "returncode": -1}
    finally:
        if tmp_file is not None:
            try:
                os.unlink(tmp_file.name)
            except OSError:
                pass


def _run_jsx_file_mac(app: str, jsx_path: str, timeout: int = 120) -> dict:
    """Execute a .jsx file in the target Adobe app via AppleScript on macOS."""
    app_info = ADOBE_APPS.get(app)
    if not app_info or not app_info["extendscript"]:
        return {"success": False, "stdout": "", "stderr": f"App '{app}' does not support ExtendScript"}

    mac_cmd = app_info.get("mac_script_cmd")
    if mac_cmd is None:
        return {"success": False, "stdout": "", "stderr": f"App '{app_info['display']}' does not support AppleScript scripting on macOS. Use file-based execution or direct app CLI."}

    applescript = _build_applescript_for_jsx(app, jsx_path, timeout)
    return _run_osascript(applescript, timeout)


# ── JSX Execution (cross-platform) ───────────────────────────────────

def _run_jsx(app: str, jsx_code: str, timeout: int = 120) -> dict:
    """Execute ExtendScript JSX code in the target Adobe app.

    Routes to macOS (AppleScript) or Windows (PowerShell COM) based on platform.
    """
    if IS_MACOS:
        return _run_jsx_mac(app, jsx_code, timeout)

    # Windows: PowerShell COM path
    app_info = ADOBE_APPS.get(app)
    if not app_info or not app_info["extendscript"]:
        return {"success": False, "stdout": "", "stderr": f"App '{app}' does not support ExtendScript"}

    # Inject polyfills (e.g. JSON for Illustrator ES3)
    jsx_code = _prepare_jsx(app, jsx_code)

    ps_script = f"""
$app = New-Object -ComObject '{app_info["com_id"]}'
$jsx = @'
{jsx_code}
'@
try {{
    $result = $app.DoJavaScript($jsx)
    Write-Output $result
}} catch {{
    Write-Error $_.Exception.Message
}}
"""
    return _run_powershell(ps_script, timeout)


def _run_jsx_file(app: str, jsx_path: str, timeout: int = 120) -> dict:
    """Execute a .jsx file in the target Adobe app.

    Routes to macOS (AppleScript) or Windows (PowerShell COM) based on platform.
    """
    if IS_MACOS:
        return _run_jsx_file_mac(app, jsx_path, timeout)

    # Windows: PowerShell COM path
    app_info = ADOBE_APPS.get(app)
    if not app_info or not app_info["extendscript"]:
        return {"success": False, "stdout": "", "stderr": f"App '{app}' does not support ExtendScript"}

    ps_script = f"""
$app = New-Object -ComObject '{app_info["com_id"]}'
try {{
    $result = $app.DoJavaScriptFile('{jsx_path}')
    Write-Output $result
}} catch {{
    Write-Error $_.Exception.Message
}}
"""
    return _run_powershell(ps_script, timeout)


# ── Async Wrappers ───────────────────────────────────────────────────

async def _async_run_jsx(app: str, jsx_code: str, timeout: int = 120) -> dict:
    """Async JSX execution — tries WebSocket relay first, falls back to subprocess.

    If a CEP panel is connected for the target app via the relay server,
    this sends the JSX directly over WebSocket (faster, no temp file overhead).
    On any relay failure, it silently falls back to the original osascript/
    PowerShell subprocess path.
    """
    # Attempt WebSocket relay path if available
    if _relay is not None and _relay.is_connected(app):
        try:
            # Prepare JSX with polyfills (same as subprocess path)
            prepared_jsx = _prepare_jsx(app, jsx_code)
            result = await _run_jsx_websocket(app, prepared_jsx, timeout=timeout)
            if result.get("success"):
                return result
            # If relay returned a failure due to connection issues, fall through
            # to subprocess. If it was a genuine JSX error, return it as-is.
            stderr = result.get("stderr", "")
            if "connection" in stderr.lower() or "timeout" in stderr.lower() or "relay" in stderr.lower():
                logger.debug("Relay execution failed for %s, falling back to subprocess: %s", app, stderr)
            else:
                # Genuine JSX execution error — return it, don't retry via subprocess
                return result
        except Exception as exc:
            # Any relay error — silently fall back to subprocess
            logger.debug("Relay unavailable for %s, falling back to subprocess: %s", app, exc)

    # Subprocess path (original, always available)
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_jsx, app, jsx_code, timeout)


async def _async_run_jsx_file(app: str, jsx_path: str, timeout: int = 120) -> dict:
    """Async wrapper for JSX file execution."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_jsx_file, app, jsx_path, timeout)


async def _async_run_powershell(script: str, timeout: int = 120) -> dict:
    """Async wrapper for PowerShell execution."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_powershell, script, timeout)


async def _async_run_osascript(script: str, timeout: int = 120) -> dict:
    """Async wrapper for AppleScript execution."""
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _run_osascript, script, timeout)
