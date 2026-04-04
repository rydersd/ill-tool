"""Generate a self-contained HTML animatic preview from storyboard panels.

Pure Python -- no Adobe calls.  Reads panel data from the rig and
generates an HTML file with embedded JavaScript that:
- Auto-advances panels based on duration_frames / fps
- Shows a progress bar, panel number, description, timing
- Supports keyboard controls (Space=pause, Left/Right=navigate)
"""

import json
import os

from adobe_mcp.apps.illustrator.models import AiAnimaticPreviewInput
from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig


def _compute_panel_timings(panels: list[dict], fps: int) -> list[dict]:
    """Compute per-panel timing data for the animatic.

    Returns a list of panel timing dicts with cumulative start/end times.
    """
    timings = []
    cumulative_ms = 0

    for panel in panels:
        dur_frames = panel.get("duration_frames", 24)
        dur_ms = int((dur_frames / fps) * 1000) if fps > 0 else 1000

        timings.append({
            "number": panel.get("number", 0),
            "description": panel.get("description", ""),
            "camera": panel.get("camera", "medium"),
            "duration_ms": dur_ms,
            "start_ms": cumulative_ms,
            "end_ms": cumulative_ms + dur_ms,
            "duration_frames": dur_frames,
        })
        cumulative_ms += dur_ms

    return timings


def _generate_html(
    timings: list[dict],
    fps: int,
    auto_play: bool,
    show_timing: bool,
    show_descriptions: bool,
) -> str:
    """Generate a self-contained HTML animatic file.

    The HTML embeds all panel data as JSON and uses JavaScript for playback.
    Panel images are referenced from the storyboard export directory
    (/tmp/ai_storyboard_export/panel_NNN.png) or shown as placeholder
    colored rectangles.
    """
    total_ms = timings[-1]["end_ms"] if timings else 0
    total_seconds = round(total_ms / 1000, 1)
    panels_json = json.dumps(timings, indent=2)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Animatic Preview</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
body {{
    background: #1a1a1a;
    color: #e0e0e0;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    display: flex;
    flex-direction: column;
    align-items: center;
    height: 100vh;
    overflow: hidden;
}}
#viewer {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    width: 100%;
    max-width: 960px;
    position: relative;
}}
#panel-display {{
    width: 100%;
    aspect-ratio: 16/9;
    background: #2a2a2a;
    border: 2px solid #444;
    border-radius: 4px;
    display: flex;
    align-items: center;
    justify-content: center;
    position: relative;
    overflow: hidden;
}}
#panel-display img {{
    max-width: 100%;
    max-height: 100%;
    object-fit: contain;
}}
#panel-placeholder {{
    text-align: center;
    color: #888;
    font-size: 2em;
}}
#info-bar {{
    width: 100%;
    max-width: 960px;
    padding: 8px 12px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    background: #222;
    font-size: 14px;
}}
#panel-label {{
    font-weight: bold;
    color: #fff;
    font-size: 16px;
}}
#description {{
    color: #aaa;
    font-style: italic;
    flex: 1;
    margin: 0 16px;
    text-align: center;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
}}
#timing {{
    color: #888;
    font-size: 13px;
    white-space: nowrap;
}}
#progress-container {{
    width: 100%;
    max-width: 960px;
    height: 6px;
    background: #333;
    cursor: pointer;
    position: relative;
}}
#progress-bar {{
    height: 100%;
    background: #4a9eff;
    width: 0%;
    transition: width 0.1s linear;
}}
#controls {{
    width: 100%;
    max-width: 960px;
    padding: 10px 12px;
    display: flex;
    justify-content: center;
    gap: 12px;
    background: #1e1e1e;
}}
.btn {{
    background: #333;
    color: #ddd;
    border: 1px solid #555;
    padding: 6px 16px;
    border-radius: 4px;
    cursor: pointer;
    font-size: 14px;
}}
.btn:hover {{ background: #444; }}
.btn.active {{ background: #4a9eff; color: #fff; border-color: #4a9eff; }}
#help {{
    color: #555;
    font-size: 11px;
    padding: 6px;
    text-align: center;
}}
</style>
</head>
<body>

<div id="viewer">
    <div id="panel-display">
        <div id="panel-placeholder">Loading...</div>
        <img id="panel-img" style="display:none" alt="Panel">
    </div>
</div>

<div id="info-bar">
    <span id="panel-label">Panel 1</span>
    <span id="description"></span>
    <span id="timing"></span>
</div>

<div id="progress-container">
    <div id="progress-bar"></div>
</div>

<div id="controls">
    <button class="btn" id="btn-prev" title="Previous (Left Arrow)">&larr; Prev</button>
    <button class="btn" id="btn-play" title="Play/Pause (Space)">&#9654; Play</button>
    <button class="btn" id="btn-next" title="Next (Right Arrow)">Next &rarr;</button>
</div>

<div id="help">
    Space = Play/Pause &nbsp;|&nbsp; &larr;&rarr; = Navigate &nbsp;|&nbsp; {len(timings)} panels &nbsp;|&nbsp; {total_seconds}s total &nbsp;|&nbsp; {fps} fps
</div>

<script>
(function() {{
    var panels = {panels_json};
    var currentIndex = 0;
    var playing = {'true' if auto_play else 'false'};
    var timer = null;
    var totalDuration = {total_ms};
    var showTiming = {'true' if show_timing else 'false'};
    var showDesc = {'true' if show_descriptions else 'false'};

    var imgEl = document.getElementById('panel-img');
    var placeholderEl = document.getElementById('panel-placeholder');
    var labelEl = document.getElementById('panel-label');
    var descEl = document.getElementById('description');
    var timingEl = document.getElementById('timing');
    var progressBar = document.getElementById('progress-bar');
    var btnPlay = document.getElementById('btn-play');

    function showPanel(idx) {{
        if (idx < 0 || idx >= panels.length) return;
        currentIndex = idx;
        var p = panels[idx];

        // Try to load panel image from export directory
        var imgPath = '/tmp/ai_storyboard_export/panel_' +
            String(p.number).padStart(3, '0') + '.png';

        imgEl.onerror = function() {{
            imgEl.style.display = 'none';
            placeholderEl.style.display = 'block';
            // Generate a colored placeholder based on panel number
            var hue = (p.number * 47) % 360;
            placeholderEl.style.background =
                'hsl(' + hue + ', 30%, 25%)';
            placeholderEl.textContent = 'Panel ' + p.number;
        }};
        imgEl.onload = function() {{
            imgEl.style.display = 'block';
            placeholderEl.style.display = 'none';
        }};
        imgEl.src = imgPath;

        labelEl.textContent = 'Panel ' + p.number +
            ' (' + (idx + 1) + '/' + panels.length + ')';

        if (showDesc) {{
            descEl.textContent = p.description || '';
        }}

        if (showTiming) {{
            var durSec = (p.duration_ms / 1000).toFixed(1);
            timingEl.textContent = p.camera.toUpperCase() +
                ' | ' + durSec + 's (' + p.duration_frames + 'f)';
        }}

        // Update progress bar
        if (totalDuration > 0) {{
            var progress = (p.start_ms / totalDuration) * 100;
            progressBar.style.width = progress + '%';
        }}
    }}

    function nextPanel() {{
        if (currentIndex < panels.length - 1) {{
            showPanel(currentIndex + 1);
        }} else {{
            // Loop back to start
            showPanel(0);
            if (playing) {{
                stopPlayback();
            }}
        }}
    }}

    function prevPanel() {{
        if (currentIndex > 0) {{
            showPanel(currentIndex - 1);
        }}
    }}

    function startPlayback() {{
        playing = true;
        btnPlay.innerHTML = '&#9646;&#9646; Pause';
        btnPlay.classList.add('active');
        scheduleNext();
    }}

    function stopPlayback() {{
        playing = false;
        btnPlay.innerHTML = '&#9654; Play';
        btnPlay.classList.remove('active');
        if (timer) {{
            clearTimeout(timer);
            timer = null;
        }}
    }}

    function scheduleNext() {{
        if (!playing || currentIndex >= panels.length) return;
        var p = panels[currentIndex];
        timer = setTimeout(function() {{
            nextPanel();
            if (playing && currentIndex < panels.length) {{
                scheduleNext();
            }}
        }}, p.duration_ms);
    }}

    function togglePlay() {{
        if (playing) {{
            stopPlayback();
        }} else {{
            startPlayback();
        }}
    }}

    // Button handlers
    document.getElementById('btn-prev').addEventListener('click', function() {{
        stopPlayback();
        prevPanel();
    }});
    document.getElementById('btn-next').addEventListener('click', function() {{
        stopPlayback();
        nextPanel();
    }});
    btnPlay.addEventListener('click', togglePlay);

    // Progress bar click-to-seek
    document.getElementById('progress-container').addEventListener('click', function(e) {{
        var rect = this.getBoundingClientRect();
        var pct = (e.clientX - rect.left) / rect.width;
        var targetMs = pct * totalDuration;
        // Find which panel this time falls into
        for (var i = 0; i < panels.length; i++) {{
            if (targetMs >= panels[i].start_ms && targetMs < panels[i].end_ms) {{
                stopPlayback();
                showPanel(i);
                break;
            }}
        }}
    }});

    // Keyboard controls
    document.addEventListener('keydown', function(e) {{
        switch(e.code) {{
            case 'Space':
                e.preventDefault();
                togglePlay();
                break;
            case 'ArrowLeft':
                e.preventDefault();
                stopPlayback();
                prevPanel();
                break;
            case 'ArrowRight':
                e.preventDefault();
                stopPlayback();
                nextPanel();
                break;
        }}
    }});

    // Initialize
    showPanel(0);
    if (playing) {{
        startPlayback();
    }}
}})();
</script>
</body>
</html>"""


def register(mcp):
    """Register the adobe_ai_animatic_preview tool."""

    @mcp.tool(
        name="adobe_ai_animatic_preview",
        annotations={
            "readOnlyHint": False,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_animatic_preview(params: AiAnimaticPreviewInput) -> str:
        """Generate an HTML-based animatic preview from storyboard panel data.

        Creates a self-contained HTML file with:
        - Panel image display (from storyboard export PNGs or placeholders)
        - Auto-advance based on panel duration/fps
        - Progress bar with click-to-seek
        - Keyboard controls: Space=pause, Left/Right=navigate
        - Panel info: number, description, camera, timing

        No Adobe connection needed -- pure Python generation.
        """
        character_name = "storyboard"
        rig = _load_rig(character_name)

        panels = rig.get("storyboard", {}).get("panels", [])
        if not panels:
            return json.dumps({
                "error": "No storyboard panels found.",
                "hint": "Create panels first with adobe_ai_storyboard_panel.",
            })

        timeline = rig.get("timeline", {"fps": 24})
        fps = timeline.get("fps", 24)
        if fps <= 0:
            fps = 24

        # Compute timings
        timings = _compute_panel_timings(panels, fps)

        # Generate HTML
        html = _generate_html(
            timings,
            fps,
            auto_play=params.auto_play,
            show_timing=params.show_timing,
            show_descriptions=params.show_descriptions,
        )

        # Determine output path
        output_path = params.output_path
        if not output_path:
            output_path = "/tmp/ai_storyboard_animatic.html"
        if not output_path.lower().endswith(".html"):
            output_path += ".html"

        # Write HTML file
        out_dir = os.path.dirname(output_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)

        with open(output_path, "w") as f:
            f.write(html)

        total_ms = timings[-1]["end_ms"] if timings else 0
        return json.dumps({
            "action": "animatic_preview",
            "output_path": output_path,
            "panel_count": len(timings),
            "total_duration_ms": total_ms,
            "total_duration_seconds": round(total_ms / 1000, 2),
            "fps": fps,
            "auto_play": params.auto_play,
            "show_timing": params.show_timing,
            "show_descriptions": params.show_descriptions,
        }, indent=2)
