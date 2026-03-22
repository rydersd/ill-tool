"""Core execution engine — JSX, AppleScript, and PowerShell runners.

Also provides the JSX template engine: load_template() reads co-located .jsx files
from the calling module's directory and fills {{param}} placeholders. This separates
ExtendScript from Python — JSX becomes testable in the ExtendScript Toolkit and
editable by non-Python developers.
"""

import asyncio
import inspect
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from adobe_mcp.config import ADOBE_APPS, IS_MACOS, IS_WINDOWS
from adobe_mcp.jsx.templates import escape_jsx_string


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

def _build_applescript_for_jsx(app: str, jsx_file_path: str) -> str:
    """Build the correct AppleScript invocation for running a JSX file in a given Adobe app.

    Each Adobe app has a different AppleScript scripting dictionary for executing scripts.
    """
    app_info = ADOBE_APPS[app]
    proc = app_info.get("mac_process", app_info["display"])
    bundle_id = app_info.get("bundle_id")

    if app == "photoshop":
        return f'tell application "{proc}" to do javascript of file "{jsx_file_path}"'
    elif app == "illustrator":
        return f'tell application "{proc}" to do javascript file "{jsx_file_path}"'
    elif app == "indesign":
        return f'tell application id "{bundle_id}" to do script (POSIX file "{jsx_file_path}") language javascript'
    elif app == "aftereffects":
        return f'tell application "{proc}" to DoScriptFile "{jsx_file_path}"'
    else:
        return f'tell application "{proc}" to do script (POSIX file "{jsx_file_path}")'


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

        applescript = _build_applescript_for_jsx(app, temp_path)
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

    applescript = _build_applescript_for_jsx(app, jsx_path)
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
    """Async wrapper for JSX execution."""
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
