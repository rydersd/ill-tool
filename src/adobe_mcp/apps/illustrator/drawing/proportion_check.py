"""Validate character proportions against known artistic canons.

Pure Python — no JSX needed.  Uses landmarks stored in the character rig
to compute head-to-body ratios and compare them against standard canons:

    realistic : 7.5 heads
    heroic    : 8.0 heads
    anime     : 5.0 heads
    chibi     : 2.0 heads
    cartoon   : 3.5 heads

Reports deviation percentage and per-limb proportion violations.
"""

import json
import math

from pydantic import BaseModel, ConfigDict, Field

from adobe_mcp.apps.illustrator.rigging.rig_data import _load_rig, _save_rig


# ---------------------------------------------------------------------------
# Input model
# ---------------------------------------------------------------------------


class AiProportionCheckInput(BaseModel):
    """Check character proportions against artistic canons."""
    model_config = ConfigDict(str_strip_whitespace=True)
    action: str = Field(
        ...,
        description="Action: check, set_canon",
    )
    character_name: str = Field(default="character", description="Character identifier")
    canon: str = Field(
        default="realistic",
        description="Canon to compare against: realistic, heroic, anime, chibi, cartoon",
    )


# ---------------------------------------------------------------------------
# Canons and proportion math
# ---------------------------------------------------------------------------


CANONS: dict[str, float] = {
    "realistic": 7.5,
    "heroic": 8.0,
    "anime": 5.0,
    "chibi": 2.0,
    "cartoon": 3.5,
}

# Expected limb proportions as percentage of total body height
# These are rough artistic guidelines
LIMB_PROPORTIONS: dict[str, dict[str, float]] = {
    "realistic": {
        "upper_arm": 14.0,   # shoulder→elbow
        "forearm": 12.0,     # elbow→wrist
        "upper_leg": 22.0,   # hip→knee
        "lower_leg": 22.0,   # knee→ankle
        "torso": 30.0,       # shoulder→hip
    },
    "heroic": {
        "upper_arm": 14.5,
        "forearm": 12.5,
        "upper_leg": 23.0,
        "lower_leg": 23.0,
        "torso": 28.0,
    },
    "anime": {
        "upper_arm": 12.0,
        "forearm": 10.0,
        "upper_leg": 22.0,
        "lower_leg": 20.0,
        "torso": 28.0,
    },
    "chibi": {
        "upper_arm": 10.0,
        "forearm": 8.0,
        "upper_leg": 14.0,
        "lower_leg": 12.0,
        "torso": 20.0,
    },
    "cartoon": {
        "upper_arm": 11.0,
        "forearm": 9.0,
        "upper_leg": 18.0,
        "lower_leg": 16.0,
        "torso": 25.0,
    },
}


def _distance(a: list, b: list) -> float:
    """Euclidean distance between two [x, y] positions."""
    return math.sqrt((b[0] - a[0]) ** 2 + (b[1] - a[1]) ** 2)


def compute_head_height(landmarks: dict) -> float | None:
    """Return the head height (head_top → chin) or None if landmarks missing."""
    ht = landmarks.get("head_top")
    ch = landmarks.get("chin")
    if not ht or "ai" not in ht or not ch or "ai" not in ch:
        return None
    return _distance(ht["ai"], ch["ai"])


def compute_body_height(landmarks: dict) -> float | None:
    """Return the total body height (head_top → feet_bottom).

    Falls back to head_top → ankle if feet_bottom isn't available.
    """
    ht = landmarks.get("head_top")
    if not ht or "ai" not in ht:
        return None

    # Try feet_bottom first
    fb = landmarks.get("feet_bottom")
    if fb and "ai" in fb:
        return _distance(ht["ai"], fb["ai"])

    # Fallback: average of ankle_l and ankle_r
    al = landmarks.get("ankle_l")
    ar = landmarks.get("ankle_r")
    if al and "ai" in al and ar and "ai" in ar:
        ankle_y = (al["ai"][1] + ar["ai"][1]) / 2.0
        ankle_x = (al["ai"][0] + ar["ai"][0]) / 2.0
        return _distance(ht["ai"], [ankle_x, ankle_y])

    return None


def compute_proportion_ratio(landmarks: dict) -> dict:
    """Compute the head-to-body proportion ratio.

    Returns {head_height, body_height, ratio} or {error}.
    """
    head_h = compute_head_height(landmarks)
    body_h = compute_body_height(landmarks)

    if head_h is None:
        return {"error": "Cannot compute head height (need head_top and chin landmarks)"}
    if body_h is None:
        return {"error": "Cannot compute body height (need head_top and feet_bottom or ankle landmarks)"}
    if head_h == 0:
        return {"error": "Head height is zero — check landmark positions"}

    ratio = body_h / head_h
    return {
        "head_height": round(head_h, 2),
        "body_height": round(body_h, 2),
        "ratio": round(ratio, 2),
    }


def check_limb_proportions(landmarks: dict, canon: str, body_height: float) -> list[dict]:
    """Check individual limb proportions against the canon.

    Returns a list of violations where actual deviates more than 20 %
    from expected.
    """
    if canon not in LIMB_PROPORTIONS:
        return []

    expected = LIMB_PROPORTIONS[canon]
    violations = []

    # Limb measurement pairs: (limb_name, landmark_a, landmark_b)
    limb_pairs = [
        ("upper_arm", "shoulder_l", "elbow_l"),
        ("forearm", "elbow_l", "wrist_l"),
        ("upper_leg", "hip_l", "knee_l"),
        ("lower_leg", "knee_l", "ankle_l"),
    ]

    # Torso
    sl = landmarks.get("shoulder_l")
    sr = landmarks.get("shoulder_r")
    hc = landmarks.get("hip_center")
    if sl and "ai" in sl and sr and "ai" in sr and hc and "ai" in hc:
        shoulder_mid = [(sl["ai"][0] + sr["ai"][0]) / 2, (sl["ai"][1] + sr["ai"][1]) / 2]
        torso_len = _distance(shoulder_mid, hc["ai"])
        actual_pct = (torso_len / body_height) * 100 if body_height > 0 else 0
        exp_pct = expected.get("torso", 30.0)
        dev = abs(actual_pct - exp_pct) / exp_pct * 100 if exp_pct > 0 else 0
        if dev > 20:
            violations.append({
                "limb": "torso",
                "expected_pct": round(exp_pct, 1),
                "actual_pct": round(actual_pct, 1),
                "deviation_pct": round(dev, 1),
            })

    for limb_name, la_name, lb_name in limb_pairs:
        la = landmarks.get(la_name)
        lb = landmarks.get(lb_name)
        if not la or "ai" not in la or not lb or "ai" not in lb:
            continue
        limb_len = _distance(la["ai"], lb["ai"])
        actual_pct = (limb_len / body_height) * 100 if body_height > 0 else 0
        exp_pct = expected.get(limb_name, 0)
        if exp_pct == 0:
            continue
        dev = abs(actual_pct - exp_pct) / exp_pct * 100
        if dev > 20:
            violations.append({
                "limb": limb_name,
                "expected_pct": round(exp_pct, 1),
                "actual_pct": round(actual_pct, 1),
                "deviation_pct": round(dev, 1),
            })

    return violations


# ---------------------------------------------------------------------------
# MCP registration
# ---------------------------------------------------------------------------


def register(mcp):
    """Register the adobe_ai_proportion_check tool."""

    @mcp.tool(
        name="adobe_ai_proportion_check",
        annotations={
            "readOnlyHint": True,
            "destructiveHint": False,
            "idempotentHint": True,
            "openWorldHint": False,
        },
    )
    async def adobe_ai_proportion_check(params: AiProportionCheckInput) -> str:
        """Validate character proportions against artistic canons.

        Compare head-to-body ratio and per-limb proportions against
        standard canons (realistic, heroic, anime, chibi, cartoon).
        """
        action = params.action.lower().strip()

        if action == "check":
            rig = _load_rig(params.character_name)
            landmarks = rig.get("landmarks", {})

            canon = params.canon.lower().strip()
            if canon not in CANONS:
                return json.dumps({
                    "error": f"Unknown canon: {canon}",
                    "valid_canons": list(CANONS.keys()),
                })

            ratio_info = compute_proportion_ratio(landmarks)
            if "error" in ratio_info:
                return json.dumps(ratio_info)

            expected_ratio = CANONS[canon]
            actual_ratio = ratio_info["ratio"]
            deviation_pct = round(
                abs(actual_ratio - expected_ratio) / expected_ratio * 100, 1
            )

            violations = check_limb_proportions(
                landmarks, canon, ratio_info["body_height"]
            )

            return json.dumps({
                "action": "check",
                "canon": canon,
                "expected_ratio": expected_ratio,
                "actual_ratio": actual_ratio,
                "deviation_pct": deviation_pct,
                "head_height": ratio_info["head_height"],
                "body_height": ratio_info["body_height"],
                "violations": violations,
                "pass": deviation_pct <= 10 and len(violations) == 0,
            })

        elif action == "set_canon":
            rig = _load_rig(params.character_name)
            canon = params.canon.lower().strip()
            if canon not in CANONS:
                return json.dumps({
                    "error": f"Unknown canon: {canon}",
                    "valid_canons": list(CANONS.keys()),
                })
            rig["canon"] = canon
            _save_rig(params.character_name, rig)
            return json.dumps({
                "action": "set_canon",
                "canon": canon,
                "expected_ratio": CANONS[canon],
            })

        else:
            return json.dumps({
                "error": f"Unknown action: {action}",
                "valid_actions": ["check", "set_canon"],
            })
