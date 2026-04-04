"""Shared fixtures for the adobe-mcp test suite.

Provides:
- Synthetic test images (no external dependencies)
- Mock for _async_run_jsx (isolates from Adobe apps)
- Temporary rig directories (isolates from /tmp/ai_rigs)
- Temporary recipe/progress directories
"""

import json
import os
import tempfile

import cv2
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# Synthetic test images — generated once per session, cached in /tmp
# ---------------------------------------------------------------------------

FIXTURES_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="session", autouse=True)
def create_fixtures_dir():
    """Ensure the fixtures directory exists."""
    os.makedirs(FIXTURES_DIR, exist_ok=True)


@pytest.fixture(scope="session")
def white_rect_png():
    """100x100 white rectangle (60x40) centered on black background."""
    path = os.path.join(FIXTURES_DIR, "white_rect.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 30), (80, 70), (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def white_circle_png():
    """100x100 white circle (radius 30) centered on black background."""
    path = os.path.join(FIXTURES_DIR, "white_circle.png")
    img = np.zeros((100, 100, 3), dtype=np.uint8)
    cv2.circle(img, (50, 50), 30, (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def nested_shapes_png():
    """200x200 image: white rectangle containing a white circle (for hierarchy tests)."""
    path = os.path.join(FIXTURES_DIR, "nested_shapes.png")
    img = np.zeros((200, 200, 3), dtype=np.uint8)
    cv2.rectangle(img, (20, 20), (180, 180), (255, 255, 255), -1)
    # Inner circle (black on white rect creates a nested contour)
    cv2.circle(img, (100, 100), 40, (0, 0, 0), -1)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def red_image_png():
    """50x50 solid red image for color sampling tests."""
    path = os.path.join(FIXTURES_DIR, "red_image.png")
    img = np.zeros((50, 50, 3), dtype=np.uint8)
    img[:, :] = (0, 0, 255)  # BGR format — red
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def gradient_png():
    """100x50 horizontal gradient from black to white for color tests."""
    path = os.path.join(FIXTURES_DIR, "gradient.png")
    img = np.zeros((50, 100, 3), dtype=np.uint8)
    for x in range(100):
        val = int(x * 255 / 99)
        img[:, x] = (val, val, val)
    cv2.imwrite(path, img)
    return path


@pytest.fixture(scope="session")
def two_rects_png():
    """200x100 image with two separate white rectangles for multi-contour tests."""
    path = os.path.join(FIXTURES_DIR, "two_rects.png")
    img = np.zeros((100, 200, 3), dtype=np.uint8)
    cv2.rectangle(img, (10, 20), (80, 80), (255, 255, 255), -1)
    cv2.rectangle(img, (120, 20), (190, 80), (255, 255, 255), -1)
    cv2.imwrite(path, img)
    return path


# ---------------------------------------------------------------------------
# Mock for _async_run_jsx — isolates tests from Adobe apps
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_jsx(monkeypatch):
    """Mock _async_run_jsx to return configurable responses without Adobe.

    Usage:
        def test_something(mock_jsx):
            mock_jsx.set_response('{"result": "ok"}')
            # ... call tool that uses JSX
            assert mock_jsx.calls[-1]["app"] == "illustrator"
    """

    class JSXMock:
        def __init__(self):
            self.calls = []
            self._response = '""'

        def set_response(self, stdout):
            """Set the stdout that the next JSX call will return."""
            self._response = stdout

        async def __call__(self, app, jsx_code, timeout=120):
            self.calls.append({"app": app, "code": jsx_code, "timeout": timeout})
            return {"success": True, "stdout": self._response, "stderr": "", "returncode": 0}

    mock = JSXMock()
    monkeypatch.setattr("adobe_mcp.engine._async_run_jsx", mock)
    return mock


# ---------------------------------------------------------------------------
# Temporary rig isolation — prevents tests from polluting /tmp/ai_rigs
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_rig_dir(tmp_path, monkeypatch):
    """Redirect rig_data storage to a temp directory."""
    rig_dir = tmp_path / "ai_rigs"
    rig_dir.mkdir()

    def _patched_rig_path(character_name):
        return str(rig_dir / f"{character_name}.json")

    monkeypatch.setattr(
        "adobe_mcp.apps.illustrator.rigging.rig_data._rig_path", _patched_rig_path
    )
    return rig_dir


# ---------------------------------------------------------------------------
# Temporary directories for progress and recipes
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_progress_file(tmp_path):
    """Return a temp path for progress tracker JSON."""
    return str(tmp_path / ".line-art-progress.json")


@pytest.fixture
def tmp_recipe_path(tmp_path):
    """Return a temp path for shape recipes JSON."""
    path = tmp_path / "shape-recipes.json"
    return str(path)
