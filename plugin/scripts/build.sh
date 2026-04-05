#!/usr/bin/env bash
# build.sh — Configure and build the IllTool Overlay plugin as a universal .aip bundle.
#
# Usage:
#   ./plugin/scripts/build.sh          # Xcode generator (default)
#   ./plugin/scripts/build.sh --ninja  # Ninja generator (faster iteration)
#
# Output: plugin/build/Release/IllToolPlugin.aip

set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BUILD_DIR="${PLUGIN_DIR}/build"

GENERATOR="Xcode"
BUILD_TYPE="Release"

if [[ "${1:-}" == "--ninja" ]]; then
    GENERATOR="Ninja"
    shift
fi

echo "[build] Configuring with ${GENERATOR} generator..."
cmake -S "${PLUGIN_DIR}" \
      -B "${BUILD_DIR}" \
      -G "${GENERATOR}" \
      -DCMAKE_OSX_ARCHITECTURES="arm64;x86_64"

echo "[build] Building ${BUILD_TYPE}..."
cmake --build "${BUILD_DIR}" --config "${BUILD_TYPE}"

# Find the built artifact — location varies by generator
if [[ -f "${BUILD_DIR}/${BUILD_TYPE}/IllToolPlugin.aip" ]]; then
    ARTIFACT="${BUILD_DIR}/${BUILD_TYPE}/IllToolPlugin.aip"
elif [[ -f "${BUILD_DIR}/IllToolPlugin.aip" ]]; then
    ARTIFACT="${BUILD_DIR}/IllToolPlugin.aip"
else
    echo "[build] ERROR: Could not find built .aip bundle."
    exit 1
fi

echo "[build] Built: ${ARTIFACT}"
