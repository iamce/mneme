from __future__ import annotations

from typing import Any, Iterable

from .db import domain_ids_by_name, new_id, now_utc


THREAD_KINDS = ("workstream", "obligation", "concern", "relationship", "decision", "idea")
THREAD_STATUSES = ("open", "dormant", "closed")
ATTENTION_VALUES = ("active", "background", "dormant")
PRESSURE_VALUES = ("low", "medium", "high", "acute")
POSTURE_VALUES = ("clear", "unclear", "avoided", "blocked", "waiting", "decided")
MOMENTUM_VALUES = ("drifting", "stable", "progressing")
AFFECT_VALUES = ("draining", "neutral", "energizing")
HORIZON_VALUES = ("now", "soon", "later")
EVIDENCE_RELATIONS = ("supports", "mentions", "contradicts", "updates")
SUBJECT_TYPES = ("thread", "thread_state", "artifact")


def normalize_domains(names: Iterable[str]) -> tuple[str, ...]:
    seen: list[str] = []
    lowered: set[str] = set()
    for name in names:
        cleaned = name.strip()
        key = cleaned.lower()
        if cleaned and key not in lowered:
            seen.append(cleaned)
            lowered.add(key)
    return tuple(seen)


def _validate_choice(name: str, value: str, allowed: tuple[str, ...]) -> None:
    if value not in allowed:
        valid = ", ".join(allowed)
        raise ValueError(f"Invalid {name} '{value}'. Valid values: {valid}")


def _resolve_domain_rows(conn: Any, names: Iterable[str]) -> list[tuple[str, str]]:
    lookup = domain_ids_by_name(conn)
    rows: list[tuple[str, str]] = []
    for name in normalize_domains(names):
        domain_id = lookup.get(name.lower())
        if domain_id is None:
            raise ValueError(f"Unknown domain: {name}")
        rows.append((domain_id, name))
    return rows


def create_thread(
    conn: Any,
    *,
    title: str,
    kind: str,
    summary: str = "",
    domains: Iterable[str] = (),
    status: str = "open",
    salience: float = 0.5,
    confidence: float = 0.5,
    evidence_ids: Iterable[str] = (),
) -> str:
    _validate_choice("kind", kind, THREAD_KINDS)
    _validate_choice("status", status, THREAD_STATUSES)

    thread_id = new_id("thr")
    timestamp = now_utc()
    conn.execute(
        """
        INSERT INTO threads (
          id, created_at, updated_at, title, kind, status, canonical_summary,
          first_seen_at, last_seen_at, salience, confidence, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '{}')
        """,
        (
            thread_id,
            timestamp,
            timestamp,
            title,
            kind,
            status,
            summary,
            timestamp,
            timestamp,
            salience,
            confidence,
        ),
    )

    domain_rows = _resolve_domain_rows(conn, domains)
    for index, (domain_id, _name) in enumerate(domain_rows):
        conn.execute(
            """
            INSERT INTO thread_domains (thread_id, domain_id, weight, is_primary)
            VALUES (?, ?, ?, ?)
            """,
            (thread_id, domain_id, 1.0, 1 if index == 0 else 0),
        )

    for capture_id in evidence_ids:
        link_evidence(
            conn,
            subject_type="thread",
            subject_id=thread_id,
            capture_id=capture_id,
            relation="supports",
            confidence=confidence,
        )

    conn.commit()
    return thread_id


def list_threads(
    conn: Any,
    *,
    status: str | None = None,
    domain: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    joins = [
        "LEFT JOIN thread_domains AS td ON td.thread_id = t.id",
        "LEFT JOIN domains AS d ON d.id = td.domain_id",
    ]
    conditions: list[str] = []

    if status is not None:
        _validate_choice("status", status, THREAD_STATUSES)
        conditions.append("t.status = ?")
        params.append(status)

    if domain is not None:
        conditions.append(
            """
            EXISTS (
              SELECT 1
              FROM thread_domains AS td_filter
              JOIN domains AS d_filter ON d_filter.id = td_filter.domain_id
              WHERE td_filter.thread_id = t.id
                AND LOWER(d_filter.name) = ?
            )
            """
        )
        params.append(domain.lower())

    where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
          t.id,
          t.title,
          t.kind,
          t.status,
          t.canonical_summary,
          t.salience,
          t.confidence,
          t.last_seen_at,
          GROUP_CONCAT(d.name, ', ') AS domains
        FROM threads AS t
        {' '.join(joins)}
        {where_clause}
        GROUP BY t.id
        ORDER BY t.salience DESC, t.last_seen_at DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def get_thread_bundle(conn: Any, thread_id: str) -> dict[str, Any]:
    thread = conn.execute(
        """
        SELECT
          t.*,
          GROUP_CONCAT(d.name, ', ') AS domains
        FROM threads AS t
        LEFT JOIN thread_domains AS td ON td.thread_id = t.id
        LEFT JOIN domains AS d ON d.id = td.domain_id
        WHERE t.id = ?
        GROUP BY t.id
        """,
        (thread_id,),
    ).fetchone()
    if thread is None:
        raise ValueError(f"Unknown thread: {thread_id}")

    state = conn.execute(
        """
        SELECT *
        FROM thread_states
        WHERE thread_id = ? AND is_current = 1
        ORDER BY observed_at DESC
        LIMIT 1
        """,
        (thread_id,),
    ).fetchone()

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
        WHERE el.subject_type = 'thread' AND el.subject_id = ?
        ORDER BY c.created_at DESC
        LIMIT 10
        """,
        (thread_id,),
    ).fetchall()

    return {
        "thread": dict(thread),
        "current_state": dict(state) if state is not None else None,
        "evidence": [dict(row) for row in evidence],
    }


def record_thread_state(
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
    evidence_ids: Iterable[str] = (),
) -> str:
    _validate_choice("attention", attention, ATTENTION_VALUES)
    _validate_choice("pressure", pressure, PRESSURE_VALUES)
    _validate_choice("posture", posture, POSTURE_VALUES)
    _validate_choice("momentum", momentum, MOMENTUM_VALUES)
    _validate_choice("affect", affect, AFFECT_VALUES)
    _validate_choice("horizon", horizon, HORIZON_VALUES)

    existing = conn.execute("SELECT id FROM threads WHERE id = ?", (thread_id,)).fetchone()
    if existing is None:
        raise ValueError(f"Unknown thread: {thread_id}")

    conn.execute(
        "UPDATE thread_states SET is_current = 0 WHERE thread_id = ? AND is_current = 1",
        (thread_id,),
    )

    state_id = new_id("state")
    timestamp = now_utc()
    conn.execute(
        """
        INSERT INTO thread_states (
          id, thread_id, observed_at, attention, pressure, posture,
          momentum, affect, horizon, confidence, is_current
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
        """,
        (
            state_id,
            thread_id,
            timestamp,
            attention,
            pressure,
            posture,
            momentum,
            affect,
            horizon,
            confidence,
        ),
    )
    conn.execute(
        "UPDATE threads SET updated_at = ?, last_seen_at = ? WHERE id = ?",
        (timestamp, timestamp, thread_id),
    )

    for capture_id in evidence_ids:
        link_evidence(
            conn,
            subject_type="thread_state",
            subject_id=state_id,
            capture_id=capture_id,
            relation="supports",
            confidence=confidence,
        )

    conn.commit()
    return state_id


def link_evidence(
    conn: Any,
    *,
    subject_type: str,
    subject_id: str,
    capture_id: str,
    relation: str,
    confidence: float = 0.5,
    note: str = "",
) -> str:
    _validate_choice("subject_type", subject_type, SUBJECT_TYPES)
    _validate_choice("relation", relation, EVIDENCE_RELATIONS)

    capture = conn.execute("SELECT id FROM captures WHERE id = ?", (capture_id,)).fetchone()
    if capture is None:
        raise ValueError(f"Unknown capture: {capture_id}")

    link_id = new_id("ev")
    conn.execute(
        """
        INSERT INTO evidence_links (
          id, subject_type, subject_id, capture_id, relation, confidence, note
        ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (link_id, subject_type, subject_id, capture_id, relation, confidence, note),
    )
    conn.commit()
    return link_id
