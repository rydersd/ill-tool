# WebSocket Relay

> Brief: Persistent CEP panel connections replace fragile subprocess-per-call osascript — ws://localhost:8765 with graceful fallback.
> Tags: websocket, cep, relay, execution
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
The original execution model spawned a new osascript subprocess for every JSX call. This was slow, fragile, and created temp file pollution. The WebSocket relay provides persistent, low-latency bidirectional communication.

## How It Works

1. CEP (Common Extensibility Platform) panels installed inside Adobe apps
2. Panels connect to `ws://localhost:8765` on startup
3. MCP server sends JSX through WebSocket, panel evaluates it, returns result
4. Connection persists across calls — no subprocess overhead

## Fallback

If no CEP panel is connected, the engine gracefully falls back to osascript subprocess execution. Zero breaking changes — tools work either way, just faster with the relay.

## Installation

```bash
scripts/install-cep-panels.sh
```

Installs panels for Photoshop, Illustrator, and After Effects.

## See Also
- [[Architecture]]
- [[ExtendScript Guide]]
