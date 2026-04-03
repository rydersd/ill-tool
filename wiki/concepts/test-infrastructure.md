# Test Infrastructure

> Brief: 163 test files, 3-tier testing (unit/integration/smoke), synthetic image fixtures, JSXMock for Adobe isolation.
> Tags: testing, tests, smoke, fixtures, mock
> Created: 2026-04-03
> Updated: 2026-04-03

## Motivation
Track how the test system works so new tools always get proper test coverage.

## Overview

163 test files covering ~26,360 lines of test code. Tests are organized by tool category with files corresponding to major feature areas.

## Three Tiers

1. **Tier 1 — Unit Tests**: Test tool logic in isolation with mocked Adobe calls. Use JSXMock to intercept ExtendScript execution.
2. **Tier 2 — Integration Tests**: Test tool interactions and pipeline sequencing. Use synthetic images as inputs.
3. **Tier 3 — Smoke Tests**: Test against live Illustrator instance. Verify tools register and core module imports work. Run via `smoke_test.py`.

## Fixtures

Synthetic images generated in `conftest.py`:
- `white_rect_png` — white rectangle on transparent background
- `white_circle_png` — white circle
- `nested_shapes_png` — shapes within shapes
- `red_image_png` — solid red image
- `gradient_png` — gradient fill
- `two_rects_png` — two rectangles for comparison tests

## JSXMock

Intercepts `engine.run_jsx()` calls during testing. Prevents tests from needing a running Adobe application. Returns configurable mock responses.

## Rig Isolation

Character rigging tests use temporary directories (`/tmp/ai_rigs/test_*`) to prevent test pollution across runs.

## See Also
- [[Architecture]]
- [[Tool Inventory]]
