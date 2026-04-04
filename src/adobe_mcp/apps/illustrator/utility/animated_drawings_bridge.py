"""Meta Animated Drawings bridge (Docker service integration).

Sends character images to the Meta Animated Drawings Docker service for
joint detection and rig extraction.  Maps the service response to our
internal rig schema.

No ML dependencies required — communicates via HTTP to a Docker container.
"""

import json
import os
from typing import Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AnimatedDrawingsBridgeInput(BaseModel):
    """Control Animated Drawings bridge."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        default="status",
        description="Action: status, process",
    )
    image_path: Optional[str] = Field(
        default=None, description="Path to character image to process"
    )
    service_url: str = Field(
        default="http://localhost:8080",
        description="URL of the Animated Drawings Docker service",
    )


# ---------------------------------------------------------------------------
# Our rig schema joint names
# ---------------------------------------------------------------------------

RIG_JOINT_NAMES = [
    "root",
    "hip",
    "spine",
    "chest",
    "neck",
    "head",
    "shoulder_l",
    "upper_arm_l",
    "lower_arm_l",
    "hand_l",
    "shoulder_r",
    "upper_arm_r",
    "lower_arm_r",
    "hand_r",
    "upper_leg_l",
    "lower_leg_l",
    "foot_l",
    "upper_leg_r",
    "lower_leg_r",
    "foot_r",
]

# Mapping from Animated Drawings joint names to our rig joint names
AD_TO_RIG_MAP: Dict[str, str] = {
    "root": "root",
    "hip": "hip",
    "torso": "spine",
    "chest": "chest",
    "neck": "neck",
    "head": "head",
    "left_shoulder": "shoulder_l",
    "left_upper_arm": "upper_arm_l",
    "left_lower_arm": "lower_arm_l",
    "left_hand": "hand_l",
    "right_shoulder": "shoulder_r",
    "right_upper_arm": "upper_arm_r",
    "right_lower_arm": "lower_arm_r",
    "right_hand": "hand_r",
    "left_upper_leg": "upper_leg_l",
    "left_lower_leg": "lower_leg_l",
    "left_foot": "foot_l",
    "right_upper_leg": "upper_leg_r",
    "right_lower_leg": "lower_leg_r",
    "right_foot": "foot_r",
}


# ---------------------------------------------------------------------------
# Pure Python helpers
# ---------------------------------------------------------------------------


def map_ad_to_rig(ad_response: dict) -> dict:
    """Map Animated Drawings joint format to our rig schema.

    Args:
        ad_response: Response from the AD service containing joints.
            Expected format: {"joints": [{"name": str, "x": float, "y": float}, ...]}

    Returns:
        Dict with our rig schema: {"joints": [...], "unmapped": [...], "joint_count": int}
    """
    if not isinstance(ad_response, dict):
        return {"error": "Invalid response format — expected dict"}

    ad_joints = ad_response.get("joints", [])
    if not isinstance(ad_joints, list):
        return {"error": "Invalid joints format — expected list"}

    mapped_joints = []
    unmapped_joints = []

    for joint in ad_joints:
        if not isinstance(joint, dict):
            continue

        ad_name = joint.get("name", "")
        rig_name = AD_TO_RIG_MAP.get(ad_name)

        if rig_name:
            mapped_joints.append({
                "name": rig_name,
                "x": joint.get("x", 0.0),
                "y": joint.get("y", 0.0),
                "original_name": ad_name,
            })
        else:
            unmapped_joints.append(ad_name)

    return {
        "joints": mapped_joints,
        "joint_count": len(mapped_joints),
        "unmapped": unmapped_joints,
        "schema": "rig_v1",
    }


def _check_service(service_url: str) -> dict:
    """Check if the Animated Drawings Docker service is reachable."""
    try:
        import urllib.request
        req = urllib.request.Request(
            f"{service_url}/health",
            method="GET",
        )
        req.add_header("Accept", "application/json")
        with urllib.request.urlopen(req, timeout=5) as resp:
            status_code = resp.status
            return {
                "service_url": service_url,
                "reachable": True,
                "status_code": status_code,
                "rig_joint_names": RIG_JOINT_NAMES,
            }
    except Exception as exc:
        return {
            "service_url": service_url,
            "reachable": False,
            "error": str(exc),
            "hint": "Start the Animated Drawings Docker container: docker run -p 8080:8080 facebookresearch/animated-drawings",
            "rig_joint_names": RIG_JOINT_NAMES,
        }


def _process_image(image_path: str, service_url: str) -> dict:
    """Send an image to the Animated Drawings service for processing."""
    if not image_path or not os.path.isfile(image_path):
        return {"error": f"Image not found: {image_path}"}

    try:
        import urllib.request

        # Read image file
        with open(image_path, "rb") as f:
            image_data = f.read()

        # Determine content type from extension
        ext = os.path.splitext(image_path)[1].lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
        }
        content_type = content_types.get(ext, "application/octet-stream")

        # POST to the service
        req = urllib.request.Request(
            f"{service_url}/process",
            data=image_data,
            method="POST",
        )
        req.add_header("Content-Type", content_type)
        req.add_header("Accept", "application/json")

        with urllib.request.urlopen(req, timeout=60) as resp:
            response_data = json.loads(resp.read().decode("utf-8"))

        # Map the response to our rig schema
        rig_data = map_ad_to_rig(response_data)
        rig_data["image_path"] = image_path
        rig_data["service_url"] = service_url
        return rig_data

    except Exception as exc:
        error_msg = str(exc)
        if "urlopen" in error_msg.lower() or "connection" in error_msg.lower():
            return {
                "error": f"Cannot connect to Animated Drawings service: {error_msg}",
                "hint": "Ensure Docker container is running: docker run -p 8080:8080 facebookresearch/animated-drawings",
            }
        return {"error": f"Processing failed: {error_msg}"}


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_animated_drawings_bridge tool."""

    @mcp.tool(
        name="adobe_ai_animated_drawings_bridge",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": True,
        },
    )
    async def adobe_ai_animated_drawings_bridge(
        params: AnimatedDrawingsBridgeInput,
    ) -> str:
        """Meta Animated Drawings bridge for joint detection.

        Actions:
        - status: Check if Docker service is reachable
        - process: Send image, get joints mapped to our rig schema

        Requires the Animated Drawings Docker container running locally.
        """
        action = params.action.lower().strip()

        if action == "status":
            return json.dumps(_check_service(params.service_url), indent=2)

        elif action == "process":
            result = _process_image(params.image_path, params.service_url)
            return json.dumps(result, indent=2)

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["status", "process"],
            })
