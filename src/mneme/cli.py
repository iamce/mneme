from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agents import default_agent_name
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
    create_capture_tool,
    render_context_packet,
    store_chat_artifact,
    store_review_artifact,
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

    consolidate_parser = subparsers.add_parser(
        "consolidate",
        help="Consolidate recent captures into threads, states, and evidence.",
    )
    consolidate_parser.add_argument("--days", type=int, default=7)
    consolidate_parser.add_argument("--limit", type=int, default=25)
    consolidate_parser.add_argument("--dry-run", action="store_true")
    consolidate_parser.set_defaults(handler=handle_consolidate)

    return parser


def ensure_db(db_path: Path | None) -> tuple[Path, object]:
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
    record = create_capture_tool(conn, text=text, source=args.source, modality=args.modality, domains=args.domain)
    conn.close()

    domain_part = ", ".join(record.domains) if record.domains else "none"
    print(f"[{record.id}] stored in {path}")
    print(f"domains: {domain_part}")
    return 0


def handle_ask(args: argparse.Namespace) -> int:
    _, conn = ensure_db(args.db)
    context_packet = build_context_packet(conn, args.question)
    text_output = render_context_packet(context_packet)
    model_name = "local-retrieval"
    provider_name = "local"
    agent_name = "local"

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
                if result.request_id:
                    context_packet["request_id"] = result.request_id
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
        days=args.days,
        text_output=text_output,
        content=content,
        artifact_type=artifact_type,
    )
    conn.close()
    print(text_output)
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
    print(f"candidate_count: {result['candidate_count']}")

    for candidate in result["candidates"]:
        print(
            f"- {candidate['action']}: {candidate['title']} "
            f"({len(candidate['capture_ids'])} capture(s))"
        )

    if not args.dry_run:
        print(f"created_threads: {result['created_thread_count']}")
        print(f"updated_threads: {result['updated_thread_count']}")
        if result.get("artifact_id"):
            print(f"artifact_id: {result['artifact_id']}")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
