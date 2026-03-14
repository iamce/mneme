# mneme Roadmap

## Purpose

This document keeps the project pointed at the next useful layers of the memory substrate without hard-coding a single agent workflow too early.

## Current State

Shipped now:

- SQLite-backed memory store with captures, threads, thread states, evidence links, and artifacts
- Local CLI commands for `init`, `capture`, `ask`, `review`, `mcp`, `consolidate`, artifact inspection, and triggered consolidation
- MCP tools for capture, retrieval, review, thread operations, schema inspection, artifact inspection, and consolidation
- Provider and agent abstractions for model-backed `ask`
- Deterministic consolidation of recent unlinked captures into threads, current states, and evidence
- Deterministic overlap-based existing-thread merges with inspectable merge artifacts
- Durable consolidation run artifacts for apply, preview, no-op, and merge-only runs
- Triggered consolidation policy with capture-preview behavior and schedule-safe apply behavior
- Real capture-time hook and fixed scheduled entrypoint via the existing trigger policy surface
- Repo-native local and CI checks with `make check`
- Local test coverage for consolidation, lifecycle, artifact, and trigger flows

Current shape:

- `src/mneme/db.py`: storage bootstrap and query helpers
- `src/mneme/memory.py`: thread, state, and evidence operations
- `src/mneme/consolidation.py`: recent-capture consolidation logic
- `src/mneme/triggered_consolidation.py`: trigger policy and execution mode selection
- `src/mneme/artifacts.py`: durable artifact storage and inspection helpers
- `src/mneme/tools.py`: agent-facing tool surface
- `src/mneme/mcp_server.py`: MCP server
- `src/mneme/cli.py`: human-facing CLI

## Product Direction

mneme should remain a personal memory substrate for agents and humans, not a single opinionated assistant. The system should:

- keep raw captures canonical
- make derived structure rebuildable
- keep evidence traceable back to source captures
- expose the substrate through local tools and MCP, not only through one UI or one agent policy

## Completed Milestones

### 1. Consolidation Hardening

Status:
- Complete

Delivered:
- Stronger deterministic thread matching and overlap-based clustering
- Explicit ambiguous and low-overlap skips
- Deterministic existing-thread overlap merges with inspectable output
- Tests for matching edge cases, ambiguous inputs, and merge behavior

### 2. Thread Lifecycle Quality

Status:
- Complete

Delivered:
- Better update behavior for existing threads
- Explicit dormant vs closed handling
- Stronger evidence and artifact views for thread and state evolution
- Safer merge and dedupe behavior for obviously overlapping threads

### 3. Local Developer Tooling

Status:
- Complete

Delivered:
- Stable local commands for test, lint, typecheck, and combined checks
- Repo-native `Makefile` targets and CI wired to the same local contract

### 4. Triggered Consolidation

Status:
- Complete for the core product slice

Delivered:
- Clear trigger model for capture, schedule, and manual execution
- Safe preview behavior where needed and bounded apply behavior where safe
- Durable audit trail for each triggered run
- Real capture-time hook and fixed scheduled entrypoint through the shared policy layer

Follow-up still worth doing:
- Lightweight operator docs for recommended capture-hook and scheduled-run setups

## Current Milestone

### 5. Retrieval and Reasoning Quality

Goal:
- Improve how memory is turned into useful context packets and answers.

Definition of done:
- Better selection and ranking of relevant captures and threads
- Clearer artifact storage for question-answer runs
- Better citation or evidence presentation in local and MCP flows

Out of scope:
- optimizing prompts before the retrieval substrate is trustworthy

## Next Supporting Slice

### 6. Operator Ergonomics For Triggered Runs

Goal:
- Make the shipped trigger surfaces easy to run consistently without inventing new runtime behavior.

Definition of done:
- Minimal docs for the capture hook and the scheduled trigger entrypoint
- Clear examples for local/manual operation
- No new trigger heuristics outside `src/mneme/triggered_consolidation.py`

Out of scope:
- background daemons or service management baked into the repo

## Sequencing

Recommended order:

1. Retrieval and reasoning quality
2. Operator ergonomics for triggered runs
3. Future semantic matching only after retrieval quality is trustworthy

Reasoning:

- the storage, consolidation, lifecycle, and trigger foundations are now in place
- the highest-value next product work is improving how the substrate turns memory into useful context and answers
- trigger behavior should stay deterministic, so the remaining trigger work is operational clarity rather than more heuristics

## Guardrails

Avoid:

- baking in one agent-specific worldview
- silent heuristics that cannot be inspected later
- one-off shortcuts that break rebuildability
- widening schema and behavior at the same time without a narrow verification path

Prefer:

- deterministic behavior first
- explicit artifacts and evidence links
- small vertical increments with local verification
- splits when a module starts carrying unrelated responsibilities

## Open Questions

- What is the next retrieval ranking step that improves usefulness without hiding evidence provenance?
- How should thread/state evidence be presented inside context packets so downstream agents can use it without losing inspectability?
- When semantic matching is introduced later, what deterministic guardrails must remain non-negotiable?
