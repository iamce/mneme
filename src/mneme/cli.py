from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path

from .agents import default_agent_name
from .artifacts import store_chat_artifact, store_review_artifact
from .ai import answer_question, default_model_name, default_provider_name, provider_ready, resolve_ai_config
from .db import (
    connect,
    default_db_path,
    initialize,
)
from .tools import (
    build_context_packet,
    build_review_summary,
    consolidate_recent_captures_tool,
    create_capture_with_trigger_tool,
    get_artifact_tool,
    list_artifacts_tool,
    render_context_packet,
    run_triggered_consolidation_tool,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mneme")
    parser.add_argument("--db", type=Path, default=None, help="Path to the SQLite database.")

    subparsers = parser.add_subparsers(dest="command", required=True)

    init_parser = subparsers.add_parser("init", help="Initialize the local database.")
    init_parser.set_defaults(handler=handle_init)

    capture_parser = subparsers.add_parser("capture", help="Store a raw capture.")
    capture_parser.add_argument("text", nargs="?", help="Capture text. Reads stdin when omitted.")
    capture_parser.add_argument("--source", default="cli")
    capture_parser.add_argument("--modality", default="text")
    capture_parser.add_argument("--domain", action="append", default=[])
    capture_parser.add_argument("--trigger-consolidation", action="store_true")
    capture_parser.add_argument("--consolidation-days", type=int, default=7)
    capture_parser.add_argument("--consolidation-limit", type=int, default=25)
    capture_parser.set_defaults(handler=handle_capture)

    ask_parser = subparsers.add_parser("ask", help="Run a local retrieval pass.")
    ask_parser.add_argument("question")
    ask_parser.add_argument("--local-only", action="store_true")
    ask_parser.add_argument("--provider", default=default_provider_name())
    ask_parser.add_argument("--model", default=default_model_name())
    ask_parser.add_argument("--agent", default=default_agent_name())
    ask_parser.set_defaults(handler=handle_ask)

    mcp_parser = subparsers.add_parser("mcp", help="Run the mneme MCP server over stdio.")
    mcp_parser.set_defaults(handler=handle_mcp)

    review_parser = subparsers.add_parser("review", help="Create a deterministic review summary.")
    review_parser.add_argument("--days", type=int, default=7)
    review_parser.set_defaults(handler=handle_review)

    artifacts_parser = subparsers.add_parser("artifacts", help="List recent stored artifacts.")
    artifacts_parser.add_argument("--target-type", default=None)
    artifacts_parser.add_argument("--artifact-type", default=None)
    artifacts_parser.add_argument("--model", default=None)
    artifacts_parser.add_argument("--limit", type=int, default=10)
    artifacts_parser.set_defaults(handler=handle_artifacts)

    artifact_parser = subparsers.add_parser("artifact", help="Inspect one stored artifact.")
    artifact_parser.add_argument("artifact_id")
    artifact_parser.set_defaults(handler=handle_artifact)

    consolidate_parser = subparsers.add_parser(
        "consolidate",
        help="Consolidate recent captures into threads, states, and evidence.",
    )
    consolidate_parser.add_argument("--days", type=int, default=7)
    consolidate_parser.add_argument("--limit", type=int, default=25)
    consolidate_parser.add_argument("--dry-run", action="store_true")
    consolidate_parser.set_defaults(handler=handle_consolidate)

    consolidate_trigger_parser = subparsers.add_parser(
        "consolidate-trigger",
        help="Run the deterministic consolidation policy for a capture or schedule trigger.",
    )
    consolidate_trigger_parser.add_argument("--trigger", choices=("capture", "schedule"), required=True)
    consolidate_trigger_parser.add_argument("--days", type=int, default=7)
    consolidate_trigger_parser.add_argument("--limit", type=int, default=25)
    consolidate_trigger_parser.set_defaults(handler=handle_consolidate_trigger)

    return parser


def ensure_db(db_path: Path | None) -> tuple[Path, sqlite3.Connection]:
    path = db_path or default_db_path()
    conn = connect(path)
    initialize(conn)
    return path, conn


def handle_init(args: argparse.Namespace) -> int:
    path, conn = ensure_db(args.db)
    conn.close()
    print(f"Initialized mneme at {path}")
    return 0


def read_capture_text(args: argparse.Namespace) -> str:
    if args.text:
        return args.text.strip()
    if not sys.stdin.isatty():
        return sys.stdin.read().strip()
    raise SystemExit("capture requires text or stdin input")


def handle_capture(args: argparse.Namespace) -> int:
    text = read_capture_text(args)
    path, conn = ensure_db(args.db)
    record, triggered_result = create_capture_with_trigger_tool(
        conn,
        text=text,
        source=args.source,
        modality=args.modality,
        domains=args.domain,
        run_consolidation=args.trigger_consolidation,
        consolidation_days=args.consolidation_days,
        consolidation_limit=args.consolidation_limit,
    )
    conn.close()

    domain_part = ", ".join(record.domains) if record.domains else "none"
    print(f"[{record.id}] stored in {path}")
    print(f"domains: {domain_part}")
    if triggered_result is not None:
        print(f"trigger_execution_mode: {triggered_result['execution_mode']}")
        print(f"trigger_decision_reason: {triggered_result['decision_reason']}")
        print(f"trigger_artifact_id: {triggered_result['artifact_id']}")
    return 0


def handle_ask(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    context_packet = build_context_packet(conn, args.question)
    text_output = render_context_packet(context_packet)
    model_name = "local-retrieval"
    provider_name = "local"
    agent_name = "local"
    request_id = None

    if not args.local_only:
        try:
            config = resolve_ai_config(provider=args.provider, model=args.model, agent=args.agent)
        except ValueError as exc:
            conn.close()
            raise SystemExit(str(exc)) from exc
        ready, reason = provider_ready(config.provider)
        if ready:
            try:
                result = answer_question(context_packet=context_packet, config=config)
            except Exception as exc:
                text_output = f"{text_output}\n\nAI error: {exc}"
            else:
                text_output = result.text
                model_name = result.model
                provider_name = result.provider
                agent_name = result.agent
                request_id = result.request_id
        else:
            text_output = f"{text_output}\n\nAI unavailable: {reason}"

    store_chat_artifact(
        conn,
        question=args.question,
        context_packet=context_packet,
        text_output=text_output,
        model=model_name,
        mode="local-only" if args.local_only else "ai-if-available",
        provider=provider_name,
        agent=agent_name,
        request_id=request_id,
    )
    conn.close()
    print(text_output)
    return 0


def handle_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import main as run_mcp_server

    run_mcp_server()
    return 0


def handle_review(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    text_output, content, artifact_type = build_review_summary(conn, days=args.days)
    store_review_artifact(
        conn,
        text_output=text_output,
        content=content,
        artifact_type=artifact_type,
    )
    conn.close()
    print(text_output)
    return 0


def handle_artifacts(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    rows = list_artifacts_tool(
        conn,
        target_type=args.target_type,
        artifact_type=args.artifact_type,
        model=args.model,
        limit=args.limit,
    )
    conn.close()

    for row in rows:
        print(
            f"[{row['id']}] {row['created_at']} "
            f"type={row['artifact_type']} target={row['target_type']} "
            f"model={row['model']} evidence={row['evidence_count']}"
        )
    return 0


def handle_artifact(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    try:
        artifact = get_artifact_tool(conn, artifact_id=args.artifact_id)
    except ValueError as exc:
        conn.close()
        raise SystemExit(str(exc)) from exc
    conn.close()

    print(f"id: {artifact['id']}")
    print(f"created_at: {artifact['created_at']}")
    print(f"artifact_type: {artifact['artifact_type']}")
    print(f"target_type: {artifact['target_type']}")
    print(f"target_id: {artifact['target_id'] or 'none'}")
    print(f"model: {artifact['model']}")
    print("content:")
    print(json.dumps(artifact["content"], indent=2, sort_keys=True))
    if artifact["text_output"]:
        print("text_output:")
        print(artifact["text_output"])
    if artifact["evidence"]:
        print("evidence:")
        for row in artifact["evidence"]:
            print(f"- [{row['capture_id']}] {row['created_at']} | relation: {row['relation']}")
            print(f"  {row['raw_text']}")
    return 0


def handle_consolidate(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    result = consolidate_recent_captures_tool(
        conn,
        days=args.days,
        limit=args.limit,
        dry_run=args.dry_run,
    )
    conn.close()

    print(f"dry_run: {str(result['dry_run']).lower()}")
    print(f"scanned_captures: {result['scanned_capture_count']}")
    print(f"thread_merge_count: {result['thread_merge_count']}")
    print(f"candidate_count: {result['candidate_count']}")

    for merge in result["thread_merges"]:
        shared_terms = ", ".join(merge["shared_terms"]) if merge["shared_terms"] else "none"
        print(
            f"- merge_thread: {merge['duplicate_thread_title']} -> {merge['canonical_thread_title']} "
            f"({merge['reason']}; shared: {shared_terms})"
        )

    for candidate in result["candidates"]:
        print(
            f"- {candidate['action']}: {candidate['title']} "
            f"({len(candidate['capture_ids'])} capture(s))"
        )

    if not args.dry_run:
        print(f"merged_threads: {result['merged_thread_count']}")
        print(f"created_threads: {result['created_thread_count']}")
        print(f"updated_threads: {result['updated_thread_count']}")
        if result.get("artifact_id"):
            print(f"artifact_id: {result['artifact_id']}")

    return 0


def handle_consolidate_trigger(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    result = run_triggered_consolidation_tool(
        conn,
        trigger=args.trigger,
        days=args.days,
        limit=args.limit,
    )
    conn.close()

    print(f"trigger: {result['trigger']}")
    print(f"execution_mode: {result['execution_mode']}")
    print(f"decision_reason: {result['decision_reason']}")
    print(f"dry_run: {str(result['dry_run']).lower()}")
    print(f"scanned_captures: {result['scanned_capture_count']}")
    print(f"thread_merge_count: {result['thread_merge_count']}")
    print(f"candidate_count: {result['candidate_count']}")

    for merge in result["thread_merges"]:
        shared_terms = ", ".join(merge["shared_terms"]) if merge["shared_terms"] else "none"
        print(
            f"- merge_thread: {merge['duplicate_thread_title']} -> {merge['canonical_thread_title']} "
            f"({merge['reason']}; shared: {shared_terms})"
        )

    for candidate in result["candidates"]:
        print(
            f"- {candidate['action']}: {candidate['title']} "
            f"({len(candidate['capture_ids'])} capture(s))"
        )

    print(f"artifact_id: {result['artifact_id']}")
    if result.get("summary"):
        print("summary:")
        print(result["summary"])

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
