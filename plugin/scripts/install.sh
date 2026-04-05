#!/usr/bin/env bash
# install.sh — Copy the built IllTool Overlay .aip to the Illustrator plug-ins directory.
#
# Usage:
#   ./plugin/scripts/install.sh           # install from default build location
#   ./plugin/scripts/install.sh /path/to.aip  # install a specific artifact
#
# Target: ~/Library/Application Support/Adobe/Illustrator/Plug-ins/

set -euo pipefail

PLUGIN_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Illustrator 30 (2025) uses versioned path
DEST_DIR="${HOME}/Library/Application Support/Adobe/Adobe Illustrator 30/en_US/Plug-ins"

# Locate the artifact
if [[ -n "${1:-}" && -e "${1}" ]]; then
    ARTIFACT="${1}"
elif [[ -d "${PLUGIN_DIR}/build/Release/IllToolPlugin.bundle" ]]; then
    ARTIFACT="${PLUGIN_DIR}/build/Release/IllToolPlugin.bundle"
elif [[ -f "${PLUGIN_DIR}/build/Release/IllToolPlugin.aip" ]]; then
    ARTIFACT="${PLUGIN_DIR}/build/Release/IllToolPlugin.aip"
elif [[ -f "${PLUGIN_DIR}/build/IllToolPlugin.aip" ]]; then
    ARTIFACT="${PLUGIN_DIR}/build/IllToolPlugin.aip"
else
    echo "[install] ERROR: No plugin artifact found. Run build.sh first."
    exit 1
fi

# Create destination if it doesn't exist
if [[ ! -d "${DEST_DIR}" ]]; then
    echo "[install] Creating plug-ins directory: ${DEST_DIR}"
    mkdir -p "${DEST_DIR}"
fi

# Copy (overwrite existing), rename .bundle to .aip for Illustrator
rm -rf "${DEST_DIR}/IllToolPlugin.aip"
echo "[install] Copying ${ARTIFACT} -> ${DEST_DIR}/IllToolPlugin.aip"
cp -R "${ARTIFACT}" "${DEST_DIR}/IllToolPlugin.aip"

echo "[install] Installed. Restart Illustrator to load the plugin."
