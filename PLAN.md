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
- The built-in retrieval eval corpus now includes wording-gap cases for paraphrase, synonym, alias, and cross-domain phrasing-shift mismatches.
- Alias-style wording mismatches now improve deterministically via nickname expansion with inspectable ranking output.
- Synonym-style wording mismatches now improve deterministically for the physician/checkup retrieval case.
- Paraphrase-style wording mismatches now improve deterministically for the car-papers and vehicle-registration retrieval case.
- Cross-domain reimbursement-versus-expense-report phrasing now improves deterministically with inspectable ranking output.

## Recently Completed

- PR #25: retrieval eval harness landed
- PR #26: `.claude/` is gitignored and `CLAUDE.md` is tracked
- PR #27: retrieval eval corpus expanded with more fixed regression cases
- `ROADMAP.md` was reshaped into a phase roadmap
- `PLAN.md` was introduced as the resumable execution plan
- the first concrete Phase 3 problem was chosen: wording-mismatch recall
- Phase 3 Chunk 1 landed locally: wording-mismatch eval coverage for paraphrase, synonym, and alias gaps
- Phase 3 Chunk 2 landed locally: alias-style wording mismatch retrieval now passes as a fixed regression case
- Phase 3 Chunk 3 landed locally: synonym-style wording mismatch retrieval now passes as a fixed regression case
- Phase 3 Chunk 4 landed locally: paraphrase-style wording mismatch retrieval now passes as a fixed regression case
- Phase 3 Chunk 5 landed locally: cross-domain phrasing-shift eval coverage now captures the reimbursement/expense-report gap
- Phase 3 Chunk 6 landed locally: cross-domain reimbursement/expense-report retrieval now passes as a fixed regression case

## Current Objective

Keep the deterministic retrieval baseline stable while choosing the next measured recall gap beyond the initial alias, synonym, paraphrase, and cross-domain set.

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
- Complete

Goal:

- add fixed retrieval eval cases for wording-mismatch failures before changing retrieval behavior

Definition of done:

- new built-in eval cases cover at least the first chosen wording-mismatch classes
- the cases clearly state expected capture and thread behavior
- `make eval` and `make check` stay green

Completed scope:

- built-in wording-gap cases now cover paraphrase, synonym, and alias mismatches
- each gap case records the current deterministic baseline and the future target retrieval behavior

Guardrails:

- keep existing deterministic retrieval behavior visible as the baseline
- widen candidate generation before replacing ranking logic
- keep provenance, ranking reasons, and citation support inspectable
- do not ship a semantic retrieval change without fixed eval coverage first

## Candidate Next Chunks

### A. Phase 3 Chunk 2: First Wording-Mismatch Candidate Expansion

Recommendation:
- highest-priority next chunk

Status:
- Complete

Completed focus:

- deterministic alias expansion for person-name nicknames as the first wording-mismatch retrieval improvement

Definition of done:

- improve one wording-mismatch class against the new eval corpus
- keep ranking reasons and citation support inspectable
- preserve the existing non-wording regression cases

Completed scope:

- alias-style nickname expansion now widens capture candidate search and retrieval matching
- alias matches remain inspectable in ranking reasons and thread citation output

### B. Phase 3 Chunk 3: Next Wording-Mismatch Expansion

Recommendation:
- highest-priority next chunk

Status:
- Complete

Completed focus:

- deterministic synonym expansion for the physician/checkup wording-gap case

Definition of done:

- improve either the paraphrase or synonym wording-gap case against the eval corpus
- keep alias coverage and existing non-wording regressions green
- keep ranking reasons and citation support inspectable

Completed scope:

- deterministic synonym expansion now covers physician/doctor and checkup/appointment-style retrieval matches
- synonym matches remain inspectable in ranking reasons and thread citation output

### C. Phase 3 Chunk 4: Paraphrase Candidate Expansion

Recommendation:
- highest-priority next chunk

Status:
- Complete

Completed focus:

- deterministic paraphrase expansion for the car-papers and vehicle-registration wording-gap case

Definition of done:

- improve the remaining paraphrase wording-gap case against the eval corpus
- keep alias and synonym coverage plus the existing non-wording regressions green
- keep ranking reasons and citation support inspectable

Completed scope:

- deterministic paraphrase expansion now covers the car-papers and vehicle-registration retrieval case
- paraphrase matches remain inspectable in ranking reasons and thread citation output

### D. Phase 3 Chunk 5: Cross-Domain Eval Coverage

Recommendation:
- highest-priority next chunk

Status:
- Complete

Completed focus:

- add eval-first coverage for the reimbursement-versus-expense-report cross-domain phrasing shift

Definition of done:

- the next recall gap is defined with fixed eval coverage before behavior changes

Completed scope:

- built-in retrieval eval coverage now includes a passing known-gap case for a reimbursement-style query that should eventually retrieve the expense-report thread
- the current deterministic baseline remains visible while the future retrieval target is explicit

### E. Phase 3 Chunk 6: Cross-Domain Candidate Expansion

Recommendation:
- highest-priority next chunk

Status:
- Complete

Completed focus:

- deterministic cross-domain expansion for the reimbursement-versus-expense-report wording-gap case

Definition of done:

- the chosen cross-domain phrasing-shift case is promoted from known gap to fixed regression expectation

Completed scope:

- deterministic query expansion now covers the reimbursement/expense-report retrieval case
- cross-domain matches remain inspectable in ranking reasons and thread citation output

### F. Next Phase 3 Recall Slice

Use this if:
- a new wording-mismatch class is chosen from real misses or a broader semantic need becomes concrete

Definition of done:

- the next recall gap is defined with fixed eval coverage before behavior changes

### G. Retrieval Eval Ergonomics

Use this if:
- the corpus grows enough that review output becomes noisy or hard to diff

Definition of done:

- clearer eval output shape without changing retrieval behavior

### H. Operator Ergonomics Follow-Up

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
