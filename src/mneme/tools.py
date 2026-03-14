from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .db import (
    CaptureRecord,
    create_artifact,
    domain_activity,
    insert_capture,
    recent_captures,
    recent_threads,
    search_captures,
)
from .memory import create_thread, get_thread_bundle, link_evidence, list_threads, record_thread_state


STOPWORDS = {
    "about",
    "after",
    "again",
    "been",
    "from",
    "have",
    "into",
    "just",
    "keep",
    "keeps",
    "that",
    "them",
    "this",
    "what",
    "when",
    "with",
    "would",
    "your",
}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]


TOOL_REGISTRY = {
    "create_capture": ToolSpec(
        name="create_capture",
        description="Store a raw personal capture with optional domains.",
        input_schema={
            "type": "object",
            "properties": {
                "text": {"type": "string"},
                "source": {"type": "string"},
                "modality": {"type": "string"},
                "domains": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["text"],
        },
    ),
    "build_context_packet": ToolSpec(
        name="build_context_packet",
        description="Retrieve a compact evidence packet for a user question.",
        input_schema={
            "type": "object",
            "properties": {
                "question": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
            },
            "required": ["question"],
        },
    ),
    "build_review_summary": ToolSpec(
        name="build_review_summary",
        description="Summarize recent captures into a deterministic review artifact.",
        input_schema={
            "type": "object",
            "properties": {"days": {"type": "integer", "minimum": 1}},
            "required": ["days"],
        },
    ),
    "list_threads": ToolSpec(
        name="list_threads",
        description="List memory threads with optional status or domain filters.",
        input_schema={
            "type": "object",
            "properties": {
                "status": {"type": "string"},
                "domain": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
            },
        },
    ),
    "get_thread_bundle": ToolSpec(
        name="get_thread_bundle",
        description="Get a thread with its current state and supporting evidence.",
        input_schema={
            "type": "object",
            "properties": {"thread_id": {"type": "string"}},
            "required": ["thread_id"],
        },
    ),
    "propose_thread": ToolSpec(
        name="propose_thread",
        description="Create a new thread linked to domains and evidence captures.",
        input_schema={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "kind": {"type": "string"},
                "summary": {"type": "string"},
                "domains": {"type": "array", "items": {"type": "string"}},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
                "status": {"type": "string"},
                "salience": {"type": "number"},
                "confidence": {"type": "number"},
            },
            "required": ["title", "kind"],
        },
    ),
    "record_thread_state": ToolSpec(
        name="record_thread_state",
        description="Record the current state axes for a thread with optional evidence.",
        input_schema={
            "type": "object",
            "properties": {
                "thread_id": {"type": "string"},
                "attention": {"type": "string"},
                "pressure": {"type": "string"},
                "posture": {"type": "string"},
                "momentum": {"type": "string"},
                "affect": {"type": "string"},
                "horizon": {"type": "string"},
                "confidence": {"type": "number"},
                "evidence_ids": {"type": "array", "items": {"type": "string"}},
            },
            "required": [
                "thread_id",
                "attention",
                "pressure",
                "posture",
                "momentum",
                "affect",
                "horizon",
            ],
        },
    ),
    "link_evidence": ToolSpec(
        name="link_evidence",
        description="Link an existing capture as evidence for a thread, state, or artifact.",
        input_schema={
            "type": "object",
            "properties": {
                "subject_type": {"type": "string"},
                "subject_id": {"type": "string"},
                "capture_id": {"type": "string"},
                "relation": {"type": "string"},
                "confidence": {"type": "number"},
                "note": {"type": "string"},
            },
            "required": ["subject_type", "subject_id", "capture_id", "relation"],
        },
    ),
}


def list_tools() -> list[ToolSpec]:
    return [TOOL_REGISTRY[name] for name in sorted(TOOL_REGISTRY)]


def list_threads_tool(
    conn: Any,
    *,
    status: str | None = None,
    domain: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return list_threads(conn, status=status, domain=domain, limit=limit)


def get_thread_bundle_tool(conn: Any, *, thread_id: str) -> dict[str, Any]:
    return get_thread_bundle(conn, thread_id)


def propose_thread_tool(
    conn: Any,
    *,
    title: str,
    kind: str,
    summary: str = "",
    domains: list[str] | tuple[str, ...] = (),
    evidence_ids: list[str] | tuple[str, ...] = (),
    status: str = "open",
    salience: float = 0.5,
    confidence: float = 0.5,
) -> str:
    return create_thread(
        conn,
        title=title,
        kind=kind,
        summary=summary,
        domains=domains,
        evidence_ids=evidence_ids,
        status=status,
        salience=salience,
        confidence=confidence,
    )


def record_thread_state_tool(
    conn: Any,
    *,
    thread_id: str,
    attention: str,
    pressure: str,
    posture: str,
    momentum: str,
    affect: str,
    horizon: str,
    confidence: float = 0.5,
    evidence_ids: list[str] | tuple[str, ...] = (),
) -> str:
    return record_thread_state(
        conn,
        thread_id=thread_id,
        attention=attention,
        pressure=pressure,
        posture=posture,
        momentum=momentum,
        affect=affect,
        horizon=horizon,
        confidence=confidence,
        evidence_ids=evidence_ids,
    )


def link_evidence_tool(
    conn: Any,
    *,
    subject_type: str,
    subject_id: str,
    capture_id: str,
    relation: str,
    confidence: float = 0.5,
    note: str = "",
) -> str:
    return link_evidence(
        conn,
        subject_type=subject_type,
        subject_id=subject_id,
        capture_id=capture_id,
        relation=relation,
        confidence=confidence,
        note=note,
    )


def create_capture_tool(
    conn: Any,
    *,
    text: str,
    source: str = "cli",
    modality: str = "text",
    domains: list[str] | tuple[str, ...] = (),
) -> CaptureRecord:
    return insert_capture(
        conn,
        raw_text=text,
        source=source,
        modality=modality,
        domains=domains,
    )


def build_context_packet(conn: Any, question: str, *, days: int = 14) -> dict[str, Any]:
    matches = search_captures(conn, question, limit=6)
    recent = recent_captures(conn, limit=4, days=days)
    used_recent_fallback = False
    if not matches:
        matches = recent_captures(conn, limit=6, days=days)
        used_recent_fallback = True
    threads = recent_threads(conn, limit=5)
    activity = domain_activity(conn, days=days)

    return {
        "question": question,
        "relevant_captures": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "domains": row["domains"] or "",
                "raw_text": row["raw_text"],
            }
            for row in matches
        ],
        "recent_captures": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "domains": row["domains"] or "",
                "raw_text": row["raw_text"],
            }
            for row in recent
        ],
        "threads": [
            {
                "title": row["title"],
                "kind": row["kind"],
                "status": row["status"],
                "salience": row["salience"],
                "last_seen_at": row["last_seen_at"],
            }
            for row in threads
        ],
        "recent_domain_activity": [
            {"name": row["name"], "capture_count": row["capture_count"]}
            for row in activity[:5]
        ],
        "used_recent_fallback": used_recent_fallback,
    }


def render_context_packet(context_packet: dict[str, Any]) -> str:
    lines = [f"Question: {context_packet['question']}", ""]

    matches = context_packet["relevant_captures"]
    if matches:
        title = (
            "Relevant captures (recent fallback):"
            if context_packet["used_recent_fallback"]
            else "Relevant captures:"
        )
        lines.append(title)
        for row in matches:
            lines.append(render_capture(row))
        lines.append("")
    else:
        lines.append("Relevant captures: none")
        lines.append("")

    threads = context_packet["threads"]
    if threads:
        lines.append("Threads:")
        for row in threads:
            lines.append(
                f"- {row['title']} [{row['kind']}] status={row['status']} salience={row['salience']:.2f}"
            )
        lines.append("")

    activity = context_packet["recent_domain_activity"]
    if activity:
        lines.append("Recent domain activity:")
        for row in activity:
            lines.append(f"- {row['name']}: {row['capture_count']} capture(s)")
        lines.append("")

    recent = context_packet["recent_captures"]
    if recent:
        lines.append("Recent captures:")
        for row in recent:
            lines.append(render_capture(row))

    return "\n".join(lines).strip()


def build_review_summary(conn: Any, *, days: int) -> tuple[str, dict[str, Any], str]:
    captures = recent_captures(conn, limit=max(10, days * 5), days=days)
    activity = domain_activity(conn, days=days)
    texts = [row["raw_text"] for row in captures]
    top_terms = extract_top_terms(texts)

    lines = [f"Review window: last {days} day(s)", ""]
    lines.append(f"Capture count: {len(captures)}")

    if activity:
        lines.append("")
        lines.append("Domain activity:")
        for row in activity:
            lines.append(f"- {row['name']}: {row['capture_count']} capture(s)")

    if top_terms:
        lines.append("")
        lines.append("Recurring terms:")
        for term in top_terms:
            lines.append(f"- {term}")

    if captures:
        lines.append("")
        lines.append("Most recent captures:")
        lines.extend(render_capture(row) for row in captures[:5])

    artifact_type = "daily_review" if days <= 1 else "weekly_review"
    content = {
        "days": days,
        "capture_ids": [row["id"] for row in captures],
        "top_terms": top_terms,
    }
    return "\n".join(lines).strip(), content, artifact_type


def store_chat_artifact(
    conn: Any,
    *,
    question: str,
    context_packet: dict[str, Any],
    text_output: str,
    model: str,
    mode: str,
    provider: str,
    agent: str,
) -> str:
    return create_artifact(
        conn,
        artifact_type="chat_turn",
        target_type="system",
        target_id=None,
        model=model,
        content={
            "question": question,
            "context_packet": context_packet,
            "mode": mode,
            "provider": provider,
            "agent": agent,
        },
        text_output=text_output,
    )


def store_review_artifact(
    conn: Any,
    *,
    days: int,
    text_output: str,
    content: dict[str, Any],
    artifact_type: str,
) -> str:
    return create_artifact(
        conn,
        artifact_type=artifact_type,
        target_type="system",
        target_id=None,
        model="local-review",
        content=content,
        text_output=text_output,
    )


def extract_top_terms(texts: list[str], *, limit: int = 8) -> list[str]:
    tokens: list[str] = []
    for text in texts:
        for token in re.findall(r"[a-zA-Z]{4,}", text.lower()):
            if token not in STOPWORDS:
                tokens.append(token)
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(limit)]


def render_capture(row: Any) -> str:
    domains = row["domains"] or "none"
    return f"- [{row['id']}] {row['created_at']} | domains: {domains}\n  {row['raw_text']}"
