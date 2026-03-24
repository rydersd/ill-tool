"""Tests for the universal format hub tool.

Verifies format listing, availability check, routing logic,
unknown format error, and registry completeness —
all pure Python, no Adobe required.
"""

import pytest

from adobe_mcp.apps.illustrator.format_hub import (
    available_formats,
    route_export,
    FORMAT_REGISTRY,
)


# ---------------------------------------------------------------------------
# test_format_listing
# ---------------------------------------------------------------------------


class TestFormatListing:
    """List all supported export formats."""

    def test_list_all_formats(self):
        """available_formats returns entries for every format in the registry."""
        result = available_formats(installed_deps=set())

        total = result["available_count"] + result["unavailable_count"]
        assert total == len(FORMAT_REGISTRY)
        assert result["total_formats"] == len(FORMAT_REGISTRY)

    def test_list_format_entries_have_required_fields(self):
        """Each format entry has the expected fields."""
        result = available_formats(installed_deps=set())

        for entry in result["available"] + result["unavailable"]:
            assert "format" in entry
            assert "tool" in entry
            assert "description" in entry
            assert "extension" in entry


# ---------------------------------------------------------------------------
# test_availability_check
# ---------------------------------------------------------------------------


class TestAvailabilityCheck:
    """Check format availability based on installed deps."""

    def test_no_deps_available(self):
        """Formats with no dependency are always available."""
        result = available_formats(installed_deps=set())

        available_names = {f["format"] for f in result["available"]}

        # These formats have dep=None, should always be available
        for fmt_name, fmt_info in FORMAT_REGISTRY.items():
            if fmt_info["dep"] is None:
                assert fmt_name in available_names, (
                    f"Format '{fmt_name}' has no dep but is not available"
                )

    def test_with_trimesh_installed(self):
        """When trimesh is installed, usdz becomes available."""
        result = available_formats(installed_deps={"trimesh"})

        available_names = {f["format"] for f in result["available"]}
        assert "usdz" in available_names

    def test_without_trimesh(self):
        """Without trimesh, usdz is unavailable."""
        result = available_formats(installed_deps=set())

        unavailable_names = {f["format"] for f in result["unavailable"]}
        assert "usdz" in unavailable_names

    def test_with_all_deps(self):
        """With all deps installed, everything is available."""
        all_deps = {info["dep"] for info in FORMAT_REGISTRY.values() if info["dep"]}
        result = available_formats(installed_deps=all_deps)

        assert result["unavailable_count"] == 0
        assert result["available_count"] == len(FORMAT_REGISTRY)


# ---------------------------------------------------------------------------
# test_routing_logic
# ---------------------------------------------------------------------------


class TestRoutingLogic:
    """Route export to the correct tool."""

    def test_route_known_format(self):
        """Routing a known format returns the correct tool name."""
        # lottie has no dep, should always route successfully
        result = route_export("lottie", data={"test": True})

        assert result["routed"] is True
        assert result["format"] == "lottie"
        assert result["tool"] == "lottie_workflow"
        assert result["data"] == {"test": True}

    def test_route_edl(self):
        """EDL format routes to edl_export tool."""
        result = route_export("edl")
        assert result["routed"] is True
        assert result["tool"] == "edl_export"

    def test_route_case_insensitive(self):
        """Format names are matched case-insensitively."""
        result = route_export("PDF")
        assert result["routed"] is True
        assert result["format"] == "pdf"
        assert result["tool"] == "pdf_export"


# ---------------------------------------------------------------------------
# test_unknown_format_error
# ---------------------------------------------------------------------------


class TestUnknownFormatError:
    """Error handling for unknown or missing formats."""

    def test_unknown_format(self):
        """Unknown format returns error with list of available formats."""
        result = route_export("mp4_video")

        assert "error" in result
        assert "available_formats" in result
        assert isinstance(result["available_formats"], list)
        assert len(result["available_formats"]) > 0

    def test_empty_format(self):
        """Empty format name returns an error."""
        result = route_export("")
        assert "error" in result

    def test_none_format(self):
        """None format name returns an error."""
        result = route_export(None)
        assert "error" in result


# ---------------------------------------------------------------------------
# test_registry_completeness
# ---------------------------------------------------------------------------


def test_registry_has_expected_formats():
    """FORMAT_REGISTRY contains all expected formats."""
    expected = {"otio", "spine", "rive", "lottie", "live2d", "usdz", "fcpxml", "edl", "pdf"}
    actual = set(FORMAT_REGISTRY.keys())

    for fmt in expected:
        assert fmt in actual, f"Expected format '{fmt}' missing from FORMAT_REGISTRY"


def test_registry_entries_have_required_keys():
    """Every registry entry has tool, dep, and desc keys."""
    for fmt_name, fmt_info in FORMAT_REGISTRY.items():
        assert "tool" in fmt_info, f"'{fmt_name}' missing 'tool'"
        assert "dep" in fmt_info, f"'{fmt_name}' missing 'dep'"
        assert "desc" in fmt_info, f"'{fmt_name}' missing 'desc'"
        assert "extension" in fmt_info, f"'{fmt_name}' missing 'extension'"
        # dep can be None (no dependency) or a string (package name)
        assert fmt_info["dep"] is None or isinstance(fmt_info["dep"], str)
