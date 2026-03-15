# mneme Plan

## Purpose

This document is the current executable plan for mneme.

It should be easy for a new context to open this file and answer:

- what is currently true
- what was completed recently
- what should happen next
- what should not be widened right now

Keep it operational. Keep it short. Update it as work moves.

## Current State

- `main` was clean and synced with `origin/main` before this docs split started.
- The deterministic retrieval baseline is in place and protected by `mneme eval-retrieval` and `make eval`.
- The built-in retrieval eval corpus was recently expanded with ranking, citation-shape, and tie-break regression cases.
- Phase 3 is now framed to start with wording-mismatch recall under eval-first guardrails.

## Recently Completed

- PR #25: retrieval eval harness landed
- PR #26: `.claude/` is gitignored and `CLAUDE.md` is tracked
- PR #27: retrieval eval corpus expanded with more fixed regression cases
- `ROADMAP.md` was reshaped into a phase roadmap
- `PLAN.md` was introduced as the resumable execution plan
- the first concrete Phase 3 problem was chosen: wording-mismatch recall

## Current Objective

Keep the deterministic retrieval baseline stable while starting Phase 3 with an eval-first wording-mismatch slice.

## Active Tracks

### 1. Planning Docs Split

Status:
- Complete

Definition of done:

- `ROADMAP.md` is high-level and release-oriented
- `ROADMAP.md` is high-level and phase-oriented
- `PLAN.md` holds current execution state and next actions

### 2. Retrieval Baseline Protection

Status:
- Ongoing maintenance

Rule:

- if retrieval behavior changes, add or update fixed eval cases as part of the same track

Verification:

- `make eval`
- `make check`

### 3. Phase 3 Framing

Status:
- Complete

Recommended next planning chunk:

- none; framing is set tightly enough to begin the first implementation chunk

### 4. Phase 3 Chunk 1: Wording-Mismatch Eval Coverage

Status:
- Ready

Goal:

- add fixed retrieval eval cases for wording-mismatch failures before changing retrieval behavior

Definition of done:

- new built-in eval cases cover at least the first chosen wording-mismatch classes
- the cases clearly state expected capture and thread behavior
- `make eval` and `make check` stay green

Guardrails:

- keep existing deterministic retrieval behavior visible as the baseline
- widen candidate generation before replacing ranking logic
- keep provenance, ranking reasons, and citation support inspectable
- do not ship a semantic retrieval change without fixed eval coverage first

## Candidate Next Chunks

### A. Phase 3 Chunk 1: Wording-Mismatch Eval Coverage

Recommendation:
- highest-priority next chunk

Definition of done:

- built-in eval cases for the first wording-mismatch retrieval gaps
- explicit expected rankings and citation behavior where applicable
- no retrieval behavior changes yet

### B. Retrieval Eval Ergonomics

Use this if:
- the corpus grows enough that review output becomes noisy or hard to diff

Definition of done:

- clearer eval output shape without changing retrieval behavior

### C. Operator Ergonomics Follow-Up

Use this if:
- product priority is smoother real-world operation rather than wider retrieval behavior

Definition of done:

- better recommended docs or workflows for capture hooks, schedules, and routine operation

## Phase 3 Framing

Problem statement:

- current retrieval depends on direct query-term overlap, so same-meaning queries with different wording can miss the right captures and threads or fall back to recency

Success criteria:

- wording-mismatch eval cases exist before retrieval behavior changes
- future hybrid or semantic work improves those cases without regressing the current corpus
- ranking reasons, provenance, and citation support remain inspectable in local and AI-backed output
- exact-match behavior remains stable unless a fixed regression case justifies change

## Out Of Scope For Now

- prompt tuning without a concrete substrate need
- retrieval behavior changes without deterministic regression coverage
- new trigger heuristics without a strong product reason
- broad schema expansion tied to unrelated behavior changes

## Default Verification Commands

- `make eval`
- `make check`
