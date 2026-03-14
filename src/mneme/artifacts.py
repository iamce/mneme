from __future__ import annotations

import json
from typing import Any, Iterable

from .db import create_artifact
from .memory import link_evidence


def list_artifacts(
    conn: Any,
    *,
    target_type: str | None = None,
    artifact_type: str | None = None,
    model: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    conditions: list[str] = []

    if target_type is not None:
        conditions.append("target_type = ?")
        params.append(target_type)
    if artifact_type is not None:
        conditions.append("artifact_type = ?")
        params.append(artifact_type)
    if model is not None:
        conditions.append("model = ?")
        params.append(model)

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
          a.id,
          a.created_at,
          a.artifact_type,
          a.target_type,
          a.target_id,
          a.model,
          a.content_json,
          a.text_output,
          (
            SELECT COUNT(*)
            FROM evidence_links AS el
            WHERE el.subject_type = 'artifact' AND el.subject_id = a.id
          ) AS evidence_count
        FROM artifacts AS a
        {where_clause}
        ORDER BY a.created_at DESC, a.rowid DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [
        {
            **dict(row),
            "content": json.loads(row["content_json"]),
        }
        for row in rows
    ]


def get_artifact(conn: Any, artifact_id: str) -> dict[str, Any]:
    artifact = conn.execute(
        """
        SELECT
          id,
          created_at,
          artifact_type,
          target_type,
          target_id,
          model,
          content_json,
          text_output
        FROM artifacts
        WHERE id = ?
        """,
        (artifact_id,),
    ).fetchone()
    if artifact is None:
        raise ValueError(f"Unknown artifact: {artifact_id}")

    evidence = conn.execute(
        """
        SELECT
          el.id,
          el.relation,
          el.confidence,
          el.note,
          c.id AS capture_id,
          c.created_at,
          c.raw_text
        FROM evidence_links AS el
        JOIN captures AS c ON c.id = el.capture_id
        WHERE el.subject_type = 'artifact' AND el.subject_id = ?
        ORDER BY c.created_at DESC, el.rowid DESC
        LIMIT 20
        """,
        (artifact_id,),
    ).fetchall()

    return {
        **dict(artifact),
        "content": json.loads(artifact["content_json"]),
        "evidence": [dict(row) for row in evidence],
    }


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


def store_consolidation_run_artifact(
    conn: Any,
    *,
    days: int,
    limit: int,
    scanned_capture_count: int,
    eligible_capture_count: int,
    thread_merges: list[dict[str, Any]],
    candidate_count: int,
    created_thread_count: int,
    updated_thread_count: int,
    state_count: int,
    consolidated: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    text_output: str,
    evidence_capture_ids: Iterable[str] = (),
    run_metadata: dict[str, Any] | None = None,
) -> str:
    content = {
        "artifact_kind": "consolidation_run",
        "days": days,
        "limit": limit,
        "scanned_capture_count": scanned_capture_count,
        "eligible_capture_count": eligible_capture_count,
        "thread_merge_count": len(thread_merges),
        "thread_merges": thread_merges,
        "candidate_count": candidate_count,
        "created_thread_count": created_thread_count,
        "updated_thread_count": updated_thread_count,
        "state_count": state_count,
        "consolidated": consolidated,
        "skipped": skipped,
    }
    if run_metadata:
        content.update(run_metadata)
    artifact_id = create_artifact(
        conn,
        artifact_type="summary",
        target_type="system",
        target_id=None,
        model="local-consolidation",
        content=content,
        text_output=text_output,
    )
    for capture_id in evidence_capture_ids:
        link_evidence(
            conn,
            subject_type="artifact",
            subject_id=artifact_id,
            capture_id=capture_id,
            relation="supports",
            confidence=0.6,
        )
    return artifact_id
