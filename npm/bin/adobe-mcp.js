#!/usr/bin/env node
"use strict";

/**
 * adobe-mcp — npm/npx wrapper for the Adobe MCP Python server.
 *
 * Zero-config launcher:
 *   1. Locates python3 / python on PATH (>= 3.10)
 *   2. Creates a virtual-env in ~/.cache/adobe-mcp/venv (once)
 *   3. Installs pip dependencies into the venv (once)
 *   4. Runs the bundled adobe_mcp.py with stdio inherited (MCP transport)
 *
 * Usage:
 *   npx adobe-mcp          # run the MCP server (stdio)
 *   npx adobe-mcp --help   # show this help
 *   npx adobe-mcp --version
 */

const { execFileSync, spawn } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// ── Paths ────────────────────────────────────────────────────────────────

const CACHE_DIR = path.join(os.homedir(), ".cache", "adobe-mcp");
const VENV_DIR = path.join(CACHE_DIR, "venv");
const SERVER_PY = path.join(__dirname, "..", "server", "adobe_mcp.py");
const PIP_DEPS = ["mcp>=1.0.0", "pydantic>=2.0.0", "httpx>=0.25.0"];
const MIN_PYTHON = [3, 10];

const isWindows = process.platform === "win32";

// ── Helpers ──────────────────────────────────────────────────────────────

function die(msg) {
  process.stderr.write(`adobe-mcp: ${msg}\n`);
  process.exit(1);
}

function log(msg) {
  process.stderr.write(`adobe-mcp: ${msg}\n`);
}

/**
 * Try to run a command and return trimmed stdout, or null on failure.
 */
function tryExec(cmd, args) {
  try {
    return execFileSync(cmd, args, {
      encoding: "utf-8",
      timeout: 30_000,
      stdio: ["pipe", "pipe", "pipe"],
    }).trim();
  } catch {
    return null;
  }
}

// ── Find Python ──────────────────────────────────────────────────────────

function findPython() {
  // Prefer python3, fall back to python (Windows often only has `python`)
  const candidates = isWindows
    ? ["python3", "python", "py"]
    : ["python3", "python"];

  for (const cmd of candidates) {
    const version = tryExec(cmd, ["--version"]);
    if (version) {
      // "Python 3.12.1" -> [3, 12, 1]
      const match = version.match(/Python\s+(\d+)\.(\d+)/);
      if (match) {
        const major = parseInt(match[1], 10);
        const minor = parseInt(match[2], 10);
        if (
          major > MIN_PYTHON[0] ||
          (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1])
        ) {
          return { cmd, major, minor };
        }
      }
    }
  }
  return null;
}

// ── Virtual Environment ──────────────────────────────────────────────────

function venvPython() {
  return isWindows
    ? path.join(VENV_DIR, "Scripts", "python.exe")
    : path.join(VENV_DIR, "bin", "python");
}

function venvPip() {
  return isWindows
    ? path.join(VENV_DIR, "Scripts", "pip.exe")
    : path.join(VENV_DIR, "bin", "pip");
}

/**
 * Marker file to track installed dependency versions.
 * Re-installs only when the dep list changes.
 */
function markerPath() {
  return path.join(VENV_DIR, ".adobe-mcp-deps");
}

function depsFingerprint() {
  return PIP_DEPS.sort().join("\n");
}

function ensureVenv(systemPython) {
  const vpython = venvPython();

  // Create venv if missing
  if (!fs.existsSync(vpython)) {
    log("creating virtual environment ...");
    fs.mkdirSync(CACHE_DIR, { recursive: true });
    try {
      execFileSync(systemPython, ["-m", "venv", VENV_DIR], {
        stdio: ["pipe", "pipe", "pipe"],
        timeout: 120_000,
      });
    } catch (e) {
      die(
        `failed to create virtual environment:\n${e.stderr || e.message}\n\n` +
          "Ensure the 'venv' module is installed (e.g. apt install python3-venv)."
      );
    }
  }

  // Install / update deps if needed
  const marker = markerPath();
  const fingerprint = depsFingerprint();
  let needInstall = true;

  if (fs.existsSync(marker)) {
    try {
      if (fs.readFileSync(marker, "utf-8").trim() === fingerprint) {
        needInstall = false;
      }
    } catch {
      // corrupt marker — reinstall
    }
  }

  if (needInstall) {
    log("installing Python dependencies ...");
    try {
      execFileSync(
        vpython,
        ["-m", "pip", "install", "--upgrade", "pip"],
        { stdio: ["pipe", "pipe", "pipe"], timeout: 120_000 }
      );
    } catch {
      // non-fatal — pip may already be recent enough
    }

    try {
      execFileSync(
        vpython,
        ["-m", "pip", "install", ...PIP_DEPS],
        { stdio: ["pipe", "pipe", "pipe"], timeout: 300_000 }
      );
    } catch (e) {
      die(
        `failed to install dependencies:\n${e.stderr || e.message}`
      );
    }

    fs.writeFileSync(marker, fingerprint, "utf-8");
    log("dependencies installed.");
  }

  return vpython;
}

// ── CLI flags ────────────────────────────────────────────────────────────

function handleFlags() {
  const args = process.argv.slice(2);

  if (args.includes("--help") || args.includes("-h")) {
    const pkg = require("../package.json");
    process.stderr.write(
      [
        `adobe-mcp v${pkg.version}`,
        "",
        pkg.description,
        "",
        "Usage:",
        "  npx adobe-mcp           Start the MCP server (stdio transport)",
        "  npx adobe-mcp --help    Show this help",
        "  npx adobe-mcp --version Show version",
        "",
        "The server communicates via stdio (stdin/stdout) using the MCP protocol.",
        "Configure your Claude client to launch this command as an MCP server.",
        "",
        "Claude Code (~/.claude/settings.json):",
        '  { "mcpServers": { "adobe": { "command": "npx", "args": ["-y", "adobe-mcp"] } } }',
        "",
        "Claude Desktop (claude_desktop_config.json):",
        '  { "mcpServers": { "adobe": { "command": "npx", "args": ["-y", "adobe-mcp"] } } }',
        "",
        "Requirements:",
        "  - Python 3.10+ in PATH",
        "  - Windows 10/11 (COM automation for Adobe apps)",
        "  - One or more Adobe Creative Cloud applications",
        "",
      ].join("\n")
    );
    process.exit(0);
  }

  if (args.includes("--version") || args.includes("-v")) {
    const pkg = require("../package.json");
    process.stdout.write(`${pkg.version}\n`);
    process.exit(0);
  }
}

// ── Main ─────────────────────────────────────────────────────────────────

function main() {
  handleFlags();

  // 1. Find system Python
  const py = findPython();
  if (!py) {
    die(
      `Python ${MIN_PYTHON.join(".")}+ is required but was not found on PATH.\n` +
        "Install from https://python.org and ensure it is added to PATH."
    );
  }

  // 2. Verify server script exists
  if (!fs.existsSync(SERVER_PY)) {
    die(
      `bundled server not found at ${SERVER_PY}\n` +
        "The npm package may be corrupted. Try reinstalling: npm install -g adobe-mcp"
    );
  }

  // 3. Set up venv and install deps
  const vpython = ensureVenv(py.cmd);

  // 4. Launch the MCP server — inherit stdio so MCP transport works
  log(`starting server (Python ${py.major}.${py.minor}) ...`);

  const child = spawn(vpython, [SERVER_PY], {
    stdio: "inherit",
    env: { ...process.env },
    windowsHide: true,
  });

  // Forward signals
  for (const sig of ["SIGINT", "SIGTERM", "SIGHUP"]) {
    process.on(sig, () => {
      child.kill(sig);
    });
  }

  child.on("error", (err) => {
    die(`failed to start Python process: ${err.message}`);
  });

  child.on("exit", (code, signal) => {
    if (signal) {
      process.exit(128 + (os.constants.signals[signal] || 1));
    }
    process.exit(code ?? 1);
  });
}

main();
