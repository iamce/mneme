# mneme

A personal memory system for capture, retrieval, and AI-assisted reflection.

`mneme` starts with a local SQLite memory store and a small CLI. The first pass
focuses on the durable parts of the system:

- raw captures
- stable domains
- derived threads and states
- review artifacts

The repo is split so other agents can use the memory system without going
through the CLI:

- `mneme.db`: storage and schema bootstrap
- `mneme.tools`: agent-facing tool surface
- `mneme.ai`: provider adapters
- `mneme.agents`: agent behavior profiles
- `mneme.mcp_server`: MCP server over the tool surface
- `mneme.cli`: human-facing command line

The base model stays simple:

- raw captures are canonical
- derived memory is rebuildable
- evidence should point back to source captures

`ask` supports two modes:

- local retrieval only
- local retrieval plus an OpenAI model for cited synthesis

The AI layer is configured separately from retrieval:

- `provider`: which backend answers the question
- `model`: which model to use within that backend
- `agent`: which instruction profile shapes the answer

Built-in agents:

- `memory`: default memory reasoning
- `reflect`: pattern and blind-spot oriented
- `plan`: next-step and tradeoff oriented

See [ROADMAP.md](ROADMAP.md) for current milestones and sequencing.

## Current Commands

Install the package in editable mode:

```bash
python3 -m pip install -e .
```

Install the local check toolchain:

```bash
make install-dev
```

Export your API key if you want model-backed `ask` responses:

```bash
export OPENAI_API_KEY="your_api_key_here"
```

Initialize the local database:

```bash
mneme init
```

Capture a note:

```bash
mneme capture "I keep putting off taxes" --domain Money --domain Stability
```

Ask a question against local memory:

```bash
mneme ask "What am I neglecting right now?"
```

Pick a different agent profile:

```bash
mneme ask "What am I neglecting right now?" --agent reflect
```

Pick a specific backend/model:

```bash
mneme ask "What should I do next?" --provider openai --model gpt-5.4 --agent plan
```

Force local-only output:

```bash
mneme ask "What am I neglecting right now?" --local-only
```

Run the MCP server over stdio:

```bash
mneme mcp
```

Or via the dedicated entrypoint:

```bash
mneme-mcp
```

Current MCP tools:

- `create_capture`
- `get_context_packet`
- `consolidate_recent_captures`
- `list_artifacts`
- `get_artifact`
- `list_threads`
- `get_thread_bundle`
- `propose_thread`
- `record_thread_state`
- `link_evidence`
- `review_memory`
- `get_domains`
- `inspect_schema`

Run a deterministic review summary:

```bash
mneme review --days 7
```

Inspect recent artifacts, including consolidation runs:

```bash
mneme artifacts --target-type system --model local-consolidation
mneme artifact art_123456789abc
```

Consolidate recent unlinked captures into threads and states:

```bash
mneme consolidate --days 7
```

## Triggered Consolidation

`mneme` already ships two operator-facing trigger entrypoints:

- a capture-time preview hook via `mneme capture --trigger-consolidation`
- a scheduled trigger via `mneme consolidate-trigger --trigger schedule`

The trigger policy stays deterministic:

- capture-triggered runs preview only and never mutate threads
- scheduled runs apply automatically only when the plan has no review-required skips
- both paths store an artifact so you can inspect what happened

Preview triggered consolidation during capture:

```bash
mneme capture "Still missing tax receipts for filing." --domain Money --trigger-consolidation
```

That prints:

- `trigger_execution_mode`
- `trigger_decision_reason`
- `trigger_artifact_id`

Inspect the resulting artifact:

```bash
mneme artifact art_123456789abc
```

Run the scheduled trigger entrypoint directly:

```bash
mneme consolidate-trigger --trigger schedule --days 7 --limit 25
```

Use the same command from `cron` or another scheduler:

```cron
0 * * * * cd /path/to/mneme && /usr/bin/env mneme consolidate-trigger --trigger schedule --days 7 --limit 25 >> /tmp/mneme-consolidate.log 2>&1
```

Recommended operator pattern:

- use `mneme capture --trigger-consolidation` in interactive capture flows when you want immediate preview artifacts
- use `mneme consolidate-trigger --trigger schedule` from a scheduler for bounded automatic applies
- inspect the printed `artifact_id` whenever the trigger previews instead of applying
- use `mneme artifacts --model local-consolidation` to review recent trigger outcomes

There is no separate daemon in the repo. The supported automation surface is the existing CLI entrypoint plus your scheduler of choice.

## Local Checks

Run the repo-native checks with:

```bash
make test
make lint
make typecheck
make check
```

These same commands back the GitHub Actions CI workflow.

## Seeded Domains

- Work
- Money
- Home
- Body
- Family
- Social
- Self
- Stability
