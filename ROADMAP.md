# mneme Roadmap

## Purpose

This document is the high-level phase roadmap for mneme.

It should answer:

- what the product is trying to become
- which major phases or milestones matter next
- what is shipped versus still ahead

It should not be used for day-to-day execution tracking. Use [PLAN.md](/Users/iamce/dev/iamce/mneme/PLAN.md) for the current working plan.

## Product Direction

mneme should remain a personal memory substrate for humans and agents, not a single opinionated assistant.

The core product shape is:

- raw captures stay canonical
- derived structure stays rebuildable
- evidence stays traceable back to source captures
- local tools and MCP remain first-class interfaces
- deterministic behavior stays ahead of opaque heuristics

## Phase Principles

Prefer:

- deterministic behavior first
- explicit artifacts and evidence links
- small vertical increments with local verification
- inspectable ranking, retrieval, and consolidation behavior

Avoid:

- baking in one agent-specific workflow too early
- silent heuristics that cannot be inspected later
- widening schema and behavior at the same time without a narrow verification path
- prompt-driven polish before the substrate is trustworthy

## Phase Roadmap

### Phase 1: Memory Substrate Foundations

Status:
- Shipped

Included:

- SQLite-backed captures, threads, thread states, evidence links, and artifacts
- Core CLI and MCP surfaces
- Deterministic consolidation and merge flows
- Durable artifacts for consolidation and question-answer runs
- Repo-native local and CI checks

### Phase 2: Deterministic Retrieval Baseline

Status:
- Shipped

Included:

- Capture and thread retrieval for `ask`
- State-aware thread ranking
- Coverage-first ranking before salience and recency tie-breaks
- Thread-supported capture ranking
- Deterministic citation rewriting from retrieval provenance
- Ranking-reason inspectability in local output, ask footers, and AI-backed citations
- Built-in retrieval eval corpus with stable `mneme eval-retrieval` and `make eval` commands

### Phase 3: Semantic Recall and Query Quality

Status:
- Current next phase

Intent:

- improve recall beyond deterministic keyword-style matching
- preserve deterministic regression visibility while widening retrieval behavior
- make semantic improvements measurable against the existing eval baseline

First focus:

- wording-mismatch recall where the query and the stored capture refer to the same thing with different vocabulary

Likely scope:

- semantic or hybrid candidate expansion with explicit guardrails
- eval-first coverage for paraphrase, synonym, and alias-style retrieval gaps
- expanded retrieval eval coverage for semantic and hybrid cases
- comparison surfaces that make regressions obvious before rollout

### Phase 4: Agent and Operator Ergonomics

Status:
- Later

Intent:

- make the substrate easier to run, inspect, and integrate repeatedly

Likely scope:

- stronger operator docs and recommended setups
- cleaner recurring workflows around capture, review, consolidation, and inspection
- better usability for humans and agents without changing the core substrate model

### Phase 5: Operational Maturity and Portability

Status:
- Later

Intent:

- make mneme easier to trust as a long-lived personal system

Likely scope:

- backup, export, restore, or migration improvements
- safer long-running operation and maintenance workflows
- clearer boundaries for versioning and rebuildability

## Current Posture

- Phases 1 and 2 are effectively complete.
- Phase 3 is the active next phase.
- Phase 3 should begin with wording-mismatch recall, not a broad semantic rewrite.
- Near-term execution should stay eval-first before implementation widens behavior.

## Current Guardrails

- Treat `mneme eval-retrieval` and `make eval` as the regression gate for retrieval changes.
- Add fixed eval cases before changing retrieval behavior when practical.
- Do not widen into semantic matching without keeping deterministic guardrails visible.
- Do not optimize prompts ahead of substrate quality and inspectability.

## Open Phase Questions

- Which wording-mismatch classes should Phase 3 cover first: paraphrases, synonyms, aliases, or cross-domain phrasing shifts?
- What deterministic guardrails must remain non-negotiable once semantic retrieval exists?
- Which ergonomics improvements belong in a phase versus in ongoing maintenance?
