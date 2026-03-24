"""Tests for the smart export tool.

Verifies manifest generation, rig JSON validity, and output directory
creation.
All tests are pure Python -- no JSX or Adobe required.
"""

import json
import os

import pytest

from adobe_mcp.apps.illustrator.smart_export import (
    prepare_ae_export,
    export_manifest,
)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_manifest_contains_expected_files(tmp_path):
    """prepare_ae_export should produce a manifest with rig JSON and AE JSX."""
    rig = {
        "character_name": "export_test",
        "joints": {"hip": {"position": [100, 200]}},
        "bones": [],
        "landmarks": {},
        "axes": {},
        "bindings": {},
        "poses": {},
        "image_source": "/tmp/test.ai",
        "image_size": [1920, 1080],
    }
    output_dir = str(tmp_path / "ae_out")
    manifest = prepare_ae_export(rig, output_dir)

    assert manifest["character_name"] == "export_test"
    assert manifest["file_count"] >= 2  # rig JSON + AE JSX at minimum

    # Check file types in manifest
    file_types = [f["type"] for f in manifest["files"]]
    assert "rig_json" in file_types
    assert "ae_import_jsx" in file_types

    # Verify files exist on disk
    for f in manifest["files"]:
        assert os.path.isfile(f["path"])


def test_rig_json_is_valid(tmp_path):
    """Exported rig JSON should be parseable and contain expected fields."""
    rig = {
        "character_name": "json_test",
        "joints": {
            "hip": {"position": [100, 200]},
            "knee": {"position": [100, 300]},
        },
        "bones": [{"parent_joint": "hip", "child_joint": "knee", "name": "thigh"}],
        "landmarks": {},
        "axes": {},
        "bindings": {},
        "poses": {"standing": {"hip": 0, "knee": 0}},
        "image_source": None,
        "image_size": None,
    }
    output_dir = str(tmp_path / "json_out")
    manifest = prepare_ae_export(rig, output_dir)

    # Find the rig JSON file
    rig_file = next(f for f in manifest["files"] if f["type"] == "rig_json")
    with open(rig_file["path"]) as f:
        exported = json.load(f)

    assert exported["character_name"] == "json_test"
    assert "hip" in exported["joints"]
    assert "knee" in exported["joints"]
    assert len(exported["bones"]) == 1


def test_export_dir_created(tmp_path):
    """prepare_ae_export should create the output directory if it doesn't exist."""
    rig = {
        "character_name": "dir_test",
        "joints": {},
        "bones": [],
        "landmarks": {},
        "axes": {},
        "bindings": {},
        "poses": {},
        "image_source": None,
        "image_size": None,
    }
    output_dir = str(tmp_path / "nested" / "deep" / "export")
    assert not os.path.exists(output_dir)

    manifest = prepare_ae_export(rig, output_dir)

    assert os.path.isdir(output_dir)
    assert manifest["file_count"] >= 2
