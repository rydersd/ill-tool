#!/usr/bin/env bash
# Auto-configure adobe-mcp for Claude Code CLI, Codex CLI, and Gemini CLI
set -euo pipefail

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

echo -e "${CYAN}Adobe MCP Server — CLI Auto-Configuration${NC}"
echo ""

# Detect OS
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" || "$OSTYPE" == "win32" ]]; then
    IS_WINDOWS=true
else
    IS_WINDOWS=false
fi

# Find python
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        ver=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [[ -n "$ver" ]]; then
            major=$(echo "$ver" | cut -d. -f1)
            minor=$(echo "$ver" | cut -d. -f2)
            if [[ "$major" -ge 3 && "$minor" -ge 10 ]]; then
                PYTHON="$cmd"
                break
            fi
        fi
    fi
done

if [[ -z "$PYTHON" ]]; then
    echo "Error: Python 3.10+ required but not found"
    exit 1
fi

echo -e "${GREEN}Found Python: $PYTHON ($ver)${NC}"

# ── Claude Code CLI ──────────────────────────────────────────────────────
configure_claude_code() {
    local config_file="$HOME/.claude.json"
    echo -e "${YELLOW}Configuring Claude Code CLI...${NC}"

    if ! command -v claude &>/dev/null; then
        echo "  Claude Code CLI not found, skipping"
        return
    fi

    # Use claude CLI to add MCP server
    claude mcp add adobe-mcp -- "$PYTHON" -m adobe_mcp 2>/dev/null && \
        echo -e "  ${GREEN}Added adobe-mcp to Claude Code${NC}" || \
        echo "  Already configured or failed — check manually with: claude mcp list"
}

# ── Codex CLI ────────────────────────────────────────────────────────────
configure_codex() {
    local config_dir="$HOME/.codex"
    local config_file="$config_dir/config.json"
    echo -e "${YELLOW}Configuring Codex CLI...${NC}"

    if ! command -v codex &>/dev/null; then
        echo "  Codex CLI not found, skipping"
        return
    fi

    mkdir -p "$config_dir"

    # Codex uses MCP config in .codex/config.json under mcpServers
    if [[ -f "$config_file" ]]; then
        # Add to existing config
        "$PYTHON" -c "
import json, sys
with open('$config_file', 'r') as f:
    config = json.load(f)
if 'mcpServers' not in config:
    config['mcpServers'] = {}
if 'adobe-mcp' not in config['mcpServers']:
    config['mcpServers']['adobe-mcp'] = {
        'command': '$PYTHON',
        'args': ['-m', 'adobe_mcp']
    }
    with open('$config_file', 'w') as f:
        json.dump(config, f, indent=2)
    print('  Added adobe-mcp to Codex CLI')
else:
    print('  adobe-mcp already configured in Codex CLI')
"
    else
        cat > "$config_file" << EOJSON
{
  "mcpServers": {
    "adobe-mcp": {
      "command": "$PYTHON",
      "args": ["-m", "adobe_mcp"]
    }
  }
}
EOJSON
        echo -e "  ${GREEN}Created Codex config with adobe-mcp${NC}"
    fi
}

# ── Gemini CLI ───────────────────────────────────────────────────────────
configure_gemini() {
    local config_dir="$HOME/.gemini"
    local config_file="$HOME/.gemini/settings.json"
    echo -e "${YELLOW}Configuring Gemini CLI...${NC}"

    if ! command -v gemini &>/dev/null; then
        echo "  Gemini CLI not found, skipping"
        return
    fi

    mkdir -p "$config_dir"

    if [[ -f "$config_file" ]]; then
        "$PYTHON" -c "
import json
with open('$config_file', 'r') as f:
    config = json.load(f)
if 'mcpServers' not in config:
    config['mcpServers'] = {}
if 'adobe-mcp' not in config['mcpServers']:
    config['mcpServers']['adobe-mcp'] = {
        'command': '$PYTHON',
        'args': ['-m', 'adobe_mcp']
    }
    with open('$config_file', 'w') as f:
        json.dump(config, f, indent=2)
    print('  Added adobe-mcp to Gemini CLI')
else:
    print('  adobe-mcp already configured in Gemini CLI')
"
    else
        cat > "$config_file" << EOJSON
{
  "mcpServers": {
    "adobe-mcp": {
      "command": "$PYTHON",
      "args": ["-m", "adobe_mcp"]
    }
  }
}
EOJSON
        echo -e "  ${GREEN}Created Gemini config with adobe-mcp${NC}"
    fi
}

# ── Run all ──────────────────────────────────────────────────────────────
configure_claude_code
configure_codex
configure_gemini

echo ""
echo -e "${GREEN}Done! adobe-mcp is now available in all detected CLI tools.${NC}"
echo ""
echo "Manual configuration (if needed):"
echo "  Claude Code:  claude mcp add adobe-mcp -- $PYTHON -m adobe_mcp"
echo "  Claude Desktop: Add to claude_desktop_config.json"
echo "  Codex CLI:    Add to ~/.codex/config.json mcpServers"
echo "  Gemini CLI:   Add to ~/.gemini/settings.json mcpServers"
