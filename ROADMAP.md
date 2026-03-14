# mneme Roadmap

## Purpose

This document keeps the project pointed at the next useful layers of the memory substrate without hard-coding a single agent workflow too early.

## Current State

Shipped now:

- SQLite-backed memory store with captures, threads, thread states, evidence links, and artifacts
- Local CLI commands for `init`, `capture`, `ask`, `review`, `mcp`, and `consolidate`
- MCP tools for capture, retrieval, review, thread operations, schema inspection, and consolidation
- Provider and agent abstractions for model-backed `ask`
- Deterministic consolidation of recent unlinked captures into threads, current states, and evidence
- Local test coverage for the consolidation path

Current shape:

- `src/mneme/db.py`: storage bootstrap and query helpers
- `src/mneme/memory.py`: thread, state, and evidence operations
- `src/mneme/consolidation.py`: recent-capture consolidation logic
- `src/mneme/tools.py`: agent-facing tool surface
- `src/mneme/mcp_server.py`: MCP server
- `src/mneme/cli.py`: human-facing CLI

## Product Direction

mneme should remain a personal memory substrate for agents and humans, not a single opinionated assistant. The system should:

- keep raw captures canonical
- make derived structure rebuildable
- keep evidence traceable back to source captures
- expose the substrate through local tools and MCP, not only through one UI or one agent policy

## Near-Term Milestones

### 1. Consolidation Hardening

Goal:
- Make consolidation less brittle while staying deterministic and inspectable.

Definition of done:
- Better thread matching than current domain-plus-keyword heuristics
- Clearer handling for ambiguous captures and low-signal groups
- Fewer duplicate threads on reruns
- Tests for matching edge cases and ambiguous inputs

Out of scope:
- Embedding-based clustering
- fully automatic background consolidation

### 2. Thread Lifecycle Quality

Goal:
- Make threads feel stable over time instead of disposable snapshots.

Definition of done:
- Better update behavior for existing threads
- Explicit handling for dormant vs closed threads
- Stronger evidence and artifact views for inspecting how a thread changed
- Safer merge or dedupe story for obviously overlapping threads

Out of scope:
- broad data migrations for old threads unless required by a concrete bug

### 3. Local Developer Tooling

Goal:
- Give the repo real local commands for the checks that should gate changes.

Definition of done:
- Documented local commands for test, lint, and typecheck
- Commands wired into the repo in a stable, repeatable way
- CI can map cleanly to those same commands

Out of scope:
- heavyweight infra before there is a minimal command set

### 4. Triggered Consolidation

Goal:
- Reduce manual upkeep by running consolidation at the right times.

Definition of done:
- Clear trigger model for when consolidation runs
- Safe dry-run or preview mode where needed
- No duplicate thread churn from repeated runs
- Explicit audit trail for what each run changed

Out of scope:
- always-on automation without visibility into what changed

### 5. Retrieval and Reasoning Quality

Goal:
- Improve how memory is turned into useful context packets and answers.

Definition of done:
- Better selection and ranking of relevant captures and threads
- Clearer artifact storage for question-answer runs
- Better citation or evidence presentation in local and MCP flows

Out of scope:
- optimizing prompts before the retrieval substrate is trustworthy

## Sequencing

Recommended order:

1. Consolidation hardening
2. Local developer tooling
3. Thread lifecycle quality
4. Triggered consolidation
5. Retrieval and reasoning quality

Reasoning:

- consolidation is the newest and weakest layer, so it should be stabilized before more automation is built on top
- local checks should exist before the repo grows much further
- thread lifecycle work depends on more confidence in consolidation output

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

- Should ambiguous consolidation results produce only artifacts first, or should they create low-confidence threads?
- How much of consolidation should remain deterministic before introducing semantic matching?
- What is the minimal local tooling set for this repo: `unittest`, `ruff`, `mypy`, something else?
- When automation is added, should it run on capture, on schedule, or only by explicit command?
