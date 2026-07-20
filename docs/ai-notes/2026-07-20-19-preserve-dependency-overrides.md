---
issue: https://github.com/Toilal/fastapi-router-lazy/issues/19
mr:
branch: fix/19-preserve-dependency-overrides
model: GPT-5 Codex
started_at: 2026-07-20T15:16:30Z
completed_at:
---

# Implementation notes : preserve dependency overrides

## Design decisions

- The FastAPI application is used as the effective dependency override provider for flattened HTTP and WebSocket routes, matching the context discarded by `original_route` extraction.
- `reparent_route` is public so callers using `flatten_routes` directly can safely rebuild a flattened route's ASGI handler without duplicating FastAPI internals.

## Tradeoffs

- Rebuilding the route handler relies on the same semi-private FastAPI helpers as route construction; their signatures were verified across every FastAPI version in the compatibility matrix.
