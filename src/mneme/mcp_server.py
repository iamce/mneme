from __future__ import annotations

import json
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from mcp.server.fastmcp import FastMCP

from .db import connect, default_db_path, initialize
from .tools import (
    build_context_packet,
    consolidate_recent_captures_tool,
    build_review_summary,
    create_capture_tool,
    get_thread_bundle_tool,
    link_evidence_tool,
    list_threads_tool,
    propose_thread_tool,
    record_thread_state_tool,
)


mcp = FastMCP("mneme", json_response=True)
DEFAULT_SERVER_DB_PATH = os.environ.get("MNEME_DB_PATH")


def resolve_server_db_path() -> Path:
    if DEFAULT_SERVER_DB_PATH:
        return Path(DEFAULT_SERVER_DB_PATH)
    return default_db_path()


@contextmanager
def managed_connection() -> Iterator[Any]:
    path = resolve_server_db_path()
    conn = connect(path)
    initialize(conn)
    try:
        yield conn
    finally:
        conn.close()


@mcp.tool()
def create_capture(
    text: str,
    source: str = "mcp",
    modality: str = "text",
    domains: list[str] | None = None,
) -> dict[str, Any]:
    """Store a raw personal capture with optional domains."""
    with managed_connection() as conn:
        record = create_capture_tool(
            conn,
            text=text,
            source=source,
            modality=modality,
            domains=domains or [],
        )
    return {
        "id": record.id,
        "created_at": record.created_at,
        "source": record.source,
        "modality": record.modality,
        "domains": list(record.domains),
        "raw_text": record.raw_text,
    }


@mcp.tool()
def get_context_packet(question: str, days: int = 14) -> dict[str, Any]:
    """Retrieve a compact evidence packet for a question."""
    with managed_connection() as conn:
        return build_context_packet(conn, question, days=days)


@mcp.tool()
def review_memory(days: int = 7) -> dict[str, Any]:
    """Build a deterministic review summary over a recent time window."""
    with managed_connection() as conn:
        text_output, content, artifact_type = build_review_summary(conn, days=days)
    return {
        "artifact_type": artifact_type,
        "summary": text_output,
        "content": content,
    }


@mcp.tool()
def consolidate_recent_captures(
    days: int = 7,
    limit: int = 25,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Consolidate recent unlinked captures into threads, states, and evidence."""
    with managed_connection() as conn:
        return consolidate_recent_captures_tool(conn, days=days, limit=limit, dry_run=dry_run)


@mcp.tool()
def list_threads(
    status: str | None = None,
    domain: str | None = None,
    limit: int = 20,
) -> dict[str, Any]:
    """List current memory threads with optional filters."""
    with managed_connection() as conn:
        rows = list_threads_tool(conn, status=status, domain=domain, limit=limit)
    return {"threads": rows}


@mcp.tool()
def get_thread_bundle(thread_id: str) -> dict[str, Any]:
    """Fetch a thread with its current state and supporting evidence."""
    with managed_connection() as conn:
        return get_thread_bundle_tool(conn, thread_id=thread_id)


@mcp.tool()
def propose_thread(
    title: str,
    kind: str,
    summary: str = "",
    domains: list[str] | None = None,
    evidence_ids: list[str] | None = None,
    status: str = "open",
    salience: float = 0.5,
    confidence: float = 0.5,
) -> dict[str, Any]:
    """Create a new thread linked to domains and evidence captures."""
    with managed_connection() as conn:
        thread_id = propose_thread_tool(
            conn,
            title=title,
            kind=kind,
            summary=summary,
            domains=domains or [],
            evidence_ids=evidence_ids or [],
            status=status,
            salience=salience,
            confidence=confidence,
        )
    return {"thread_id": thread_id}


@mcp.tool()
def record_thread_state(
    thread_id: str,
    attention: str,
    pressure: str,
    posture: str,
    momentum: str,
    affect: str,
    horizon: str,
    confidence: float = 0.5,
    status: str | None = None,
    evidence_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Record a current thread-state snapshot with optional evidence links."""
    with managed_connection() as conn:
        state_id = record_thread_state_tool(
            conn,
            thread_id=thread_id,
            attention=attention,
            pressure=pressure,
            posture=posture,
            momentum=momentum,
            affect=affect,
            horizon=horizon,
            confidence=confidence,
            status=status,
            evidence_ids=evidence_ids or [],
        )
    return {"state_id": state_id}


@mcp.tool()
def link_evidence(
    subject_type: str,
    subject_id: str,
    capture_id: str,
    relation: str,
    confidence: float = 0.5,
    note: str = "",
) -> dict[str, Any]:
    """Link a capture as evidence for a thread, state, or artifact."""
    with managed_connection() as conn:
        link_id = link_evidence_tool(
            conn,
            subject_type=subject_type,
            subject_id=subject_id,
            capture_id=capture_id,
            relation=relation,
            confidence=confidence,
            note=note,
        )
    return {"link_id": link_id}


@mcp.tool()
def get_domains() -> dict[str, Any]:
    """List the seeded memory domains for this mneme database."""
    with managed_connection() as conn:
        rows = conn.execute("SELECT name, sort_order FROM domains ORDER BY sort_order").fetchall()
    return {
        "domains": [{"name": row["name"], "sort_order": row["sort_order"]} for row in rows],
    }


@mcp.tool()
def inspect_schema() -> dict[str, Any]:
    """Return the current table and index definitions for the local mneme database."""
    with managed_connection() as conn:
        rows = conn.execute(
            """
            SELECT type, name, sql
            FROM sqlite_master
            WHERE type IN ('table', 'index')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
    return {
        "objects": [
            {"type": row["type"], "name": row["name"], "sql": row["sql"] or ""}
            for row in rows
        ]
    }


@mcp.prompt()
def memory_reasoning_prompt(question: str) -> str:
    """Provide a compact prompt seed with current memory context."""
    with managed_connection() as conn:
        packet = build_context_packet(conn, question, days=14)
    return json.dumps(packet, indent=2, sort_keys=True)


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
