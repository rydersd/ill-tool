# Adding Tools Guide

> Brief: Step-by-step process for extending ill_tool with new MCP tools — Pydantic model, tool implementation, registration.
> Tags: guide, tools, development, pydantic, how-to
> Created: 2026-04-03
> Updated: 2026-04-03
> Source: docs/adding-tools.md

## Summary

The guide covers the standard pattern for adding new tools:

1. Define a Pydantic input model in `models.py`
2. Create tool implementation file in the app's tools directory
3. Implement `register(mcp)` function with FastMCP tool decorator
4. Add import to app's `__init__.py`
5. Write tests following the three-tier pattern

## Full Source
`docs/adding-tools.md`

## See Also
- [[Architecture]]
- [[Test Infrastructure]]
