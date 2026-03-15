# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What is mneme?

A personal memory system for capture, retrieval, and AI-assisted reflection. Raw captures are stored as immutable truth; threads, states, and evidence are derived layers that can be rebuilt. All inferences are traceable back to source captures via evidence links.

## Commands

```bash
make install-dev          # Install in editable mode with dev deps
make test                 # Run all tests
make lint                 # Ruff linting
make typecheck            # Mypy strict checking on src/
make check                # All three: test + lint + typecheck

# Single test
python3 -m unittest tests.test_consolidation.ConsolidationTests.test_dry_run_and_apply_create_thread_state_and_artifact
```

CI runs `make check` on Python 3.11 (ubuntu-latest).

## Architecture

**Two interfaces, one tool layer:** Both the CLI (`cli.py`) and MCP server (`mcp_server.py`) call into `tools.py`, which wraps core modules. Agent-facing tools are defined as `ToolSpec` entries in `TOOL_REGISTRY`.

**Core data flow:**
- `db.py` — SQLite connection, schema bootstrap from `schema.sql`, CRUD for captures/threads/states/evidence/artifacts. IDs are `{prefix}_{hex12}` format.
- `memory.py` — Thread lifecycle (create/update/list), thread state snapshots (attention, pressure, posture, momentum, affect, horizon), evidence linking.
- `consolidation.py` — Groups unlinked captures by domain, matches to existing threads via deterministic keyword/topic scoring, creates or updates threads, produces consolidation artifacts. Supports dry-run mode.
- `thread_merges.py` — Detects overlapping threads via overlap scoring, generates merge plans with confidence, applies deterministic merges.
- `triggered_consolidation.py` — Trigger policy: capture triggers are preview-only, schedule triggers auto-apply unless reviewable skips exist, manual triggers always apply.
- `retrieval.py` — Keyword extraction, search across captures and threads, relevance ranking, context packet building with evidence-backed citations.
- `artifacts.py` — Durable audit trail for consolidation runs, Q&A results, reviews, merges.
- `ai.py` / `agents.py` — Optional OpenAI integration with agent profiles (memory, reflect, plan).

**Domain model:** Eight seeded life domains (Work, Money, Home, Body, Family, Social, Self, Stability) are first-class entities. Captures and threads associate with domains via junction tables with confidence scores.

## Code conventions

- Keep files around 500 lines when possible (see AGENTS.md).
- Tests use `unittest` with `tempfile.TemporaryDirectory()` for isolated DB instances.
- Some test files use `E402` ignores for late imports after path setup.
- `from __future__ import annotations` is used throughout for forward references.

## Environment

- `MNEME_DB_PATH` — Override default DB location (default: `.mneme/mneme.db` relative to repo root)
- `OPENAI_API_KEY` — Required for AI-backed `ask` queries
- `MNEME_AI_PROVIDER`, `MNEME_AI_MODEL`, `MNEME_AGENT` — AI configuration overrides

## Entrypoints

- `mneme` CLI → `mneme.cli:main`
- `mneme-mcp` server → `mneme.mcp_server:main`
