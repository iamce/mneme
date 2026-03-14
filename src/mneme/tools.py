from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass
from typing import Any

from .artifacts import (
    get_artifact,
    list_artifacts,
)
from .consolidation import consolidate_recent_captures
from .db import (
    CaptureRecord,
    domain_activity,
    insert_capture,
    recent_captures,
)
from .memory import create_thread, get_thread_bundle, link_evidence, list_threads, record_thread_state
from .retrieval import (
    STOPWORDS,
    build_context_packet as build_context_packet_impl,
    render_capture,
    render_context_packet as render_context_packet_impl,
)
from .triggered_consolidation import run_triggered_consolidation


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
                "run_consolidation": {"type": "boolean"},
                "consolidation_days": {"type": "integer", "minimum": 1},
                "consolidation_limit": {"type": "integer", "minimum": 1},
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
    "consolidate_recent_captures": ToolSpec(
        name="consolidate_recent_captures",
        description="Consolidate recent unlinked captures into threads, states, and evidence.",
        input_schema={
            "type": "object",
            "properties": {
                "days": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
                "dry_run": {"type": "boolean"},
            },
        },
    ),
    "run_triggered_consolidation": ToolSpec(
        name="run_triggered_consolidation",
        description="Apply the deterministic trigger policy for capture- or schedule-driven consolidation.",
        input_schema={
            "type": "object",
            "properties": {
                "trigger": {"type": "string"},
                "days": {"type": "integer", "minimum": 1},
                "limit": {"type": "integer", "minimum": 1},
            },
            "required": ["trigger"],
        },
    ),
    "list_artifacts": ToolSpec(
        name="list_artifacts",
        description="List recent stored artifacts with optional filters.",
        input_schema={
            "type": "object",
            "properties": {
                "target_type": {"type": "string"},
                "artifact_type": {"type": "string"},
                "model": {"type": "string"},
                "limit": {"type": "integer", "minimum": 1},
            },
        },
    ),
    "get_artifact": ToolSpec(
        name="get_artifact",
        description="Fetch one artifact with parsed content and linked evidence.",
        input_schema={
            "type": "object",
            "properties": {"artifact_id": {"type": "string"}},
            "required": ["artifact_id"],
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
                "status": {"type": "string"},
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
    status: str | None = None,
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
        status=status,
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


def create_capture_with_trigger_tool(
    conn: Any,
    *,
    text: str,
    source: str = "cli",
    modality: str = "text",
    domains: list[str] | tuple[str, ...] = (),
    run_consolidation: bool = False,
    consolidation_days: int = 7,
    consolidation_limit: int = 25,
) -> tuple[CaptureRecord, dict[str, Any] | None]:
    record = create_capture_tool(
        conn,
        text=text,
        source=source,
        modality=modality,
        domains=domains,
    )
    triggered_result: dict[str, Any] | None = None
    if run_consolidation:
        triggered_result = run_triggered_consolidation(
            conn,
            trigger="capture",
            days=consolidation_days,
            limit=consolidation_limit,
        )
    return record, triggered_result


def consolidate_recent_captures_tool(
    conn: Any,
    *,
    days: int = 7,
    limit: int = 25,
    dry_run: bool = False,
) -> dict[str, Any]:
    return consolidate_recent_captures(conn, days=days, limit=limit, dry_run=dry_run)


def run_triggered_consolidation_tool(
    conn: Any,
    *,
    trigger: str,
    days: int = 7,
    limit: int = 25,
) -> dict[str, Any]:
    return run_triggered_consolidation(conn, trigger=trigger, days=days, limit=limit)


def list_artifacts_tool(
    conn: Any,
    *,
    target_type: str | None = None,
    artifact_type: str | None = None,
    model: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    return list_artifacts(
        conn,
        target_type=target_type,
        artifact_type=artifact_type,
        model=model,
        limit=limit,
    )


def get_artifact_tool(conn: Any, *, artifact_id: str) -> dict[str, Any]:
    return get_artifact(conn, artifact_id)


def build_context_packet(conn: Any, question: str, *, days: int = 14) -> dict[str, Any]:
    return build_context_packet_impl(conn, question, days=days)


def render_context_packet(context_packet: dict[str, Any]) -> str:
    return render_context_packet_impl(context_packet)


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


def extract_top_terms(texts: list[str], *, limit: int = 8) -> list[str]:
    tokens: list[str] = []
    for text in texts:
        for token in re.findall(r"[a-zA-Z]{4,}", text.lower()):
            if token not in STOPWORDS:
                tokens.append(token)
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(limit)]
