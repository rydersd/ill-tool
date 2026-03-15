# Auto-configure adobe-mcp for Claude Code CLI, Codex CLI, and Gemini CLI (Windows)
$ErrorActionPreference = "Stop"

Write-Host "Adobe MCP Server — CLI Auto-Configuration" -ForegroundColor Cyan
Write-Host ""

# Find Python
$python = $null
foreach ($cmd in @("python3", "python")) {
    try {
        $ver = & $cmd -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>$null
        if ($ver) {
            $parts = $ver -split '\.'
            if ([int]$parts[0] -ge 3 -and [int]$parts[1] -ge 10) {
                $python = $cmd
                break
            }
        }
    } catch {}
}

if (-not $python) {
    Write-Host "Error: Python 3.10+ required but not found" -ForegroundColor Red
    exit 1
}
Write-Host "Found Python: $python ($ver)" -ForegroundColor Green

# ── Claude Code CLI ──────────────────────────────────────────────────────
Write-Host "Configuring Claude Code CLI..." -ForegroundColor Yellow
try {
    $null = Get-Command claude -ErrorAction Stop
    & claude mcp add adobe-mcp -- $python -m adobe_mcp 2>$null
    Write-Host "  Added adobe-mcp to Claude Code" -ForegroundColor Green
} catch {
    Write-Host "  Claude Code CLI not found, skipping"
}

# ── Codex CLI ────────────────────────────────────────────────────────────
Write-Host "Configuring Codex CLI..." -ForegroundColor Yellow
$codexConfig = Join-Path $env:USERPROFILE ".codex\config.json"
try {
    $null = Get-Command codex -ErrorAction Stop
    $codexDir = Split-Path $codexConfig
    if (-not (Test-Path $codexDir)) { New-Item -ItemType Directory -Path $codexDir -Force | Out-Null }

    if (Test-Path $codexConfig) {
        $config = Get-Content $codexConfig -Raw | ConvertFrom-Json
    } else {
        $config = [PSCustomObject]@{}
    }

    if (-not $config.PSObject.Properties['mcpServers']) {
        $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
    }
    if (-not $config.mcpServers.PSObject.Properties['adobe-mcp']) {
        $config.mcpServers | Add-Member -NotePropertyName "adobe-mcp" -NotePropertyValue ([PSCustomObject]@{
            command = $python
            args = @("-m", "adobe_mcp")
        })
        $config | ConvertTo-Json -Depth 10 | Set-Content $codexConfig -Encoding UTF8
        Write-Host "  Added adobe-mcp to Codex CLI" -ForegroundColor Green
    } else {
        Write-Host "  adobe-mcp already configured in Codex CLI"
    }
} catch {
    Write-Host "  Codex CLI not found, skipping"
}

# ── Gemini CLI ───────────────────────────────────────────────────────────
Write-Host "Configuring Gemini CLI..." -ForegroundColor Yellow
$geminiConfig = Join-Path $env:USERPROFILE ".gemini\settings.json"
try {
    $null = Get-Command gemini -ErrorAction Stop
    $geminiDir = Split-Path $geminiConfig
    if (-not (Test-Path $geminiDir)) { New-Item -ItemType Directory -Path $geminiDir -Force | Out-Null }

    if (Test-Path $geminiConfig) {
        $config = Get-Content $geminiConfig -Raw | ConvertFrom-Json
    } else {
        $config = [PSCustomObject]@{}
    }

    if (-not $config.PSObject.Properties['mcpServers']) {
        $config | Add-Member -NotePropertyName "mcpServers" -NotePropertyValue ([PSCustomObject]@{})
    }
    if (-not $config.mcpServers.PSObject.Properties['adobe-mcp']) {
        $config.mcpServers | Add-Member -NotePropertyName "adobe-mcp" -NotePropertyValue ([PSCustomObject]@{
            command = $python
            args = @("-m", "adobe_mcp")
        })
        $config | ConvertTo-Json -Depth 10 | Set-Content $geminiConfig -Encoding UTF8
        Write-Host "  Added adobe-mcp to Gemini CLI" -ForegroundColor Green
    } else {
        Write-Host "  adobe-mcp already configured in Gemini CLI"
    }
} catch {
    Write-Host "  Gemini CLI not found, skipping"
}

Write-Host ""
Write-Host "Done! adobe-mcp is now available in all detected CLI tools." -ForegroundColor Green
Write-Host ""
Write-Host "Manual configuration (if needed):"
Write-Host "  Claude Code:  claude mcp add adobe-mcp -- $python -m adobe_mcp"
Write-Host "  Codex CLI:    Add to ~/.codex/config.json mcpServers"
Write-Host "  Gemini CLI:   Add to ~/.gemini/settings.json mcpServers"
