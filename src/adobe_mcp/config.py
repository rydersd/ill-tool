"""Adobe application configuration and platform constants."""

import sys
from pathlib import Path

# ── Platform Detection ──────────────────────────────────────────────────

IS_MACOS = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"

# ── Scripts Directory ───────────────────────────────────────────────────

SCRIPTS_DIR = Path(__file__).parent / "scripts"

# ── Adobe Application Registry ─────────────────────────────────────────

ADOBE_APPS = {
    "photoshop": {
        "com_id": "Photoshop.Application",
        "process": "Photoshop.exe",
        "extendscript": True,
        "jsx_target": "photoshop",
        "display": "Adobe Photoshop",
        "bundle_id": "com.adobe.Photoshop",
        "mac_process": "Adobe Photoshop 2026",
        "mac_script_cmd": "do javascript",
    },
    "illustrator": {
        "com_id": "Illustrator.Application",
        "process": "Illustrator.exe",
        "extendscript": True,
        "jsx_target": "illustrator",
        "display": "Adobe Illustrator",
        "bundle_id": "com.adobe.illustrator",
        "mac_process": "Adobe Illustrator",
        "mac_script_cmd": "do javascript",
    },
    "premierepro": {
        "com_id": "Premiere.Application",
        "process": "Adobe Premiere Pro.exe",
        "extendscript": True,
        "jsx_target": "premierepro",
        "display": "Adobe Premiere Pro",
        "bundle_id": "com.adobe.PremierePro",
        "mac_process": "Adobe Premiere Pro 2026",
        "mac_script_cmd": None,
    },
    "aftereffects": {
        "com_id": "AfterEffects.Application",
        "process": "AfterFX.exe",
        "extendscript": True,
        "jsx_target": "aftereffects",
        "display": "Adobe After Effects",
        "bundle_id": "com.adobe.AfterEffects",
        "mac_process": "Adobe After Effects 2026",
        "mac_script_cmd": "DoScriptFile",
    },
    "indesign": {
        "com_id": "InDesign.Application",
        "process": "InDesign.exe",
        "extendscript": True,
        "jsx_target": "indesign",
        "display": "Adobe InDesign",
        "bundle_id": "com.adobe.InDesign",
        "mac_process": "Adobe InDesign 2026",
        "mac_script_cmd": "do script",
    },
    "animate": {
        "com_id": "Animate.Application",
        "process": "Animate.exe",
        "extendscript": True,
        "jsx_target": "animate",
        "display": "Adobe Animate",
        "bundle_id": "com.adobe.Animate",
        "mac_process": "Animate",
        "mac_script_cmd": None,
    },
    "characteranimator": {
        "com_id": None,
        "process": "Character Animator.exe",
        "extendscript": False,
        "jsx_target": None,
        "display": "Adobe Character Animator",
        "bundle_id": None,
        "mac_process": "Character Animator",
        "mac_script_cmd": None,
    },
    "mediaencoder": {
        "com_id": "MediaEncoder.Application",
        "process": "Adobe Media Encoder.exe",
        "extendscript": True,
        "jsx_target": "ame",
        "display": "Adobe Media Encoder",
        "bundle_id": "com.adobe.ame",
        "mac_process": "Adobe Media Encoder 2026",
        "mac_script_cmd": None,
    },
}
