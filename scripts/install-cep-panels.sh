#!/usr/bin/env bash
# ──────────────────────────────────────────────────────────────────────
# install-cep-panels.sh — Install Adobe MCP CEP panels for PS, AI, AE
#
# What it does:
#   1. Enables CEP debug mode (required for unsigned extensions)
#   2. Symlinks each plugin directory into the CEP extensions folder
#   3. Symlinks the shared directory for common JS/JSX resources
#   4. Verifies all symlinks were created
#
# Usage:
#   chmod +x scripts/install-cep-panels.sh
#   ./scripts/install-cep-panels.sh
#
# To uninstall:
#   ./scripts/install-cep-panels.sh --uninstall
# ──────────────────────────────────────────────────────────────────────
set -euo pipefail

# ── Platform check ────────────────────────────────────────────────────

if [[ "$(uname)" != "Darwin" ]]; then
    echo "ERROR: This script currently supports macOS only."
    echo "Windows support is planned for a future release."
    exit 1
fi

# ── Paths ─────────────────────────────────────────────────────────────

# Resolve the project root (parent of scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PLUGINS_DIR="$PROJECT_ROOT/plugins"

# CEP extensions directory (macOS)
CEP_EXTENSIONS_DIR="$HOME/Library/Application Support/Adobe/CEP/extensions"

# MCP relay panels (in plugins/)
PANELS=("adobe-mcp-ps" "adobe-mcp-ai" "adobe-mcp-ae")
SHARED_NAME="adobe-mcp-shared"

# Standalone CEP tool panels (in cep/)
CEP_DIR="$PROJECT_ROOT/cep"
CEP_PANELS=("com.illtool.shapeaverager" "com.illtool.pathrefine" "com.illtool.smartmerge")

# ── Uninstall mode ────────────────────────────────────────────────────

if [[ "${1:-}" == "--uninstall" ]]; then
    echo "Uninstalling Adobe MCP CEP panels..."
    echo ""

    for panel in "${PANELS[@]}"; do
        target="$CEP_EXTENSIONS_DIR/$panel"
        if [[ -L "$target" ]]; then
            rm "$target"
            echo "  Removed: $target"
        elif [[ -e "$target" ]]; then
            echo "  WARNING: $target exists but is not a symlink. Skipping."
        else
            echo "  Already removed: $target"
        fi
    done

    # Remove standalone CEP panels
    for panel in "${CEP_PANELS[@]}"; do
        target="$CEP_EXTENSIONS_DIR/$panel"
        if [[ -L "$target" ]]; then
            rm "$target"
            echo "  Removed: $target"
        elif [[ -e "$target" ]]; then
            echo "  WARNING: $target exists but is not a symlink. Skipping."
        else
            echo "  Already removed: $target"
        fi
    done

    # Remove shared symlink
    shared_target="$CEP_EXTENSIONS_DIR/$SHARED_NAME"
    if [[ -L "$shared_target" ]]; then
        rm "$shared_target"
        echo "  Removed: $shared_target"
    elif [[ -e "$shared_target" ]]; then
        echo "  WARNING: $shared_target exists but is not a symlink. Skipping."
    else
        echo "  Already removed: $shared_target"
    fi

    # Remove PlayerDebugMode (only needed for unsigned dev extensions)
    defaults delete com.adobe.CSXS.12 PlayerDebugMode 2>/dev/null && \
        echo "  Removed: PlayerDebugMode for CSXS.12" || true
    defaults delete com.adobe.CSXS.11 PlayerDebugMode 2>/dev/null && \
        echo "  Removed: PlayerDebugMode for CSXS.11" || true

    echo ""
    echo "Uninstall complete. Restart Adobe apps to remove panels from menus."
    exit 0
fi

# ── Install ───────────────────────────────────────────────────────────

echo "=========================================="
echo "  Adobe MCP — CEP Panel Installer"
echo "=========================================="
echo ""

# Step 1: Enable CEP debug mode
echo "Step 1: Enabling CEP debug mode..."
# CSXS.12 covers CEP 12 (Adobe CC 2025+)
# Also set CSXS.11 for older versions
defaults write com.adobe.CSXS.12 PlayerDebugMode 1
defaults write com.adobe.CSXS.11 PlayerDebugMode 1
echo "  PlayerDebugMode enabled for CSXS 11 and 12"
echo ""

# Step 2: Ensure extensions directory exists
echo "Step 2: Ensuring extensions directory exists..."
mkdir -p "$CEP_EXTENSIONS_DIR"
echo "  Directory: $CEP_EXTENSIONS_DIR"
echo ""

# Step 3: Verify plugin source directories exist
echo "Step 3: Verifying plugin source files..."
MISSING=0
for panel in "${PANELS[@]}"; do
    manifest="$PLUGINS_DIR/$panel/CSXS/manifest.xml"
    if [[ ! -f "$manifest" ]]; then
        echo "  ERROR: Missing $manifest"
        MISSING=1
    else
        echo "  Found: $panel/CSXS/manifest.xml"
    fi
done

for panel in "${CEP_PANELS[@]}"; do
    manifest="$CEP_DIR/$panel/CSXS/manifest.xml"
    if [[ ! -f "$manifest" ]]; then
        echo "  WARNING: Missing $manifest (standalone panel)"
    else
        echo "  Found: $panel/CSXS/manifest.xml"
    fi
done

if [[ ! -d "$PLUGINS_DIR/shared" ]]; then
    echo "  ERROR: Missing $PLUGINS_DIR/shared/"
    MISSING=1
else
    echo "  Found: shared/"
fi

if [[ $MISSING -eq 1 ]]; then
    echo ""
    echo "ERROR: Required plugin files are missing. Build the project first."
    exit 1
fi
echo ""

# Step 4: Create symlinks
echo "Step 4: Creating symlinks..."

# Symlink shared directory first (panels reference it via relative paths)
shared_target="$CEP_EXTENSIONS_DIR/$SHARED_NAME"
if [[ -L "$shared_target" ]]; then
    rm "$shared_target"
    echo "  Replaced existing symlink: $SHARED_NAME"
fi
ln -s "$PLUGINS_DIR/shared" "$shared_target"
echo "  Linked: shared -> $shared_target"

# Symlink each panel
for panel in "${PANELS[@]}"; do
    target="$CEP_EXTENSIONS_DIR/$panel"
    source="$PLUGINS_DIR/$panel"

    if [[ -L "$target" ]]; then
        rm "$target"
        echo "  Replaced existing symlink: $panel"
    elif [[ -e "$target" ]]; then
        echo "  WARNING: $target already exists (not a symlink). Skipping."
        continue
    fi

    ln -s "$source" "$target"
    echo "  Linked: $panel -> $target"
done

# Symlink standalone CEP tool panels (from cep/ directory)
for panel in "${CEP_PANELS[@]}"; do
    target="$CEP_EXTENSIONS_DIR/$panel"
    source="$CEP_DIR/$panel"

    if [[ ! -d "$source" ]]; then
        echo "  SKIP: $panel (source not found)"
        continue
    fi

    if [[ -L "$target" ]]; then
        rm "$target"
        echo "  Replaced existing symlink: $panel"
    elif [[ -e "$target" ]]; then
        echo "  WARNING: $target already exists (not a symlink). Skipping."
        continue
    fi

    ln -s "$source" "$target"
    echo "  Linked: $panel -> $target"
done
echo ""

# Step 5: Verify symlinks
echo "Step 5: Verifying installation..."
ALL_OK=1

for panel in "${PANELS[@]}" "${CEP_PANELS[@]}" "$SHARED_NAME"; do
    target="$CEP_EXTENSIONS_DIR/$panel"
    if [[ -L "$target" ]]; then
        resolved=$(readlink "$target")
        echo "  OK: $panel -> $resolved"
    else
        echo "  FAIL: $panel symlink not found"
        ALL_OK=0
    fi
done
echo ""

if [[ $ALL_OK -eq 1 ]]; then
    echo "=========================================="
    echo "  Installation successful!"
    echo "=========================================="
    echo ""
    echo "Next steps:"
    echo ""
    echo "  1. Start the MCP server:  uv run adobe-mcp"
    echo "     (WebSocket relay listens on ws://localhost:8765)"
    echo ""
    echo "  2. Open each Adobe app and find the panel:"
    echo "     Photoshop:     Window > Extensions > Adobe MCP"
    echo "     Illustrator:   Window > Extensions > Adobe MCP"
    echo "     After Effects: Window > Extensions > Adobe MCP"
    echo ""
    echo "  3. Panel should show 'MCP Relay: connected' when"
    echo "     the MCP server is running."
    echo ""
    echo "  Debug access (Chrome DevTools):"
    echo "     Photoshop:     http://localhost:8088"
    echo "     Illustrator:   http://localhost:8089"
    echo "     After Effects: http://localhost:8090"
    echo ""
else
    echo "WARNING: Some symlinks failed. Check errors above."
    exit 1
fi
