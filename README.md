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

## Current Commands

Install the package in editable mode:

```bash
python3 -m pip install -e .
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

Consolidate recent unlinked captures into threads and states:

```bash
mneme consolidate --days 7
```

## Seeded Domains

- Work
- Money
- Home
- Body
- Family
- Social
- Self
- Stability
