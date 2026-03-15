from __future__ import annotations

import re
from typing import Any

from .db import domain_activity, recent_captures, search_captures
from .memory import get_thread_bundle, list_threads


STOPWORDS = {
    "about",
    "after",
    "again",
    "are",
    "been",
    "from",
    "have",
    "into",
    "just",
    "keep",
    "keeps",
    "that",
    "the",
    "them",
    "this",
    "what",
    "when",
    "with",
    "would",
    "your",
}


def build_context_packet(conn: Any, question: str, *, days: int = 14) -> dict[str, Any]:
    query_terms = _extract_query_terms(question)
    recent = recent_captures(conn, limit=4, days=days)
    capture_candidates = _merge_capture_candidates(
        search_captures(conn, question, limit=12),
        recent_captures(conn, limit=12, days=days),
    )
    relevant_captures, used_recent_fallback = _rank_relevant_captures(
        capture_candidates,
        query_terms=query_terms,
        days=days,
        conn=conn,
    )
    threads = _rank_relevant_threads(conn, query_terms=query_terms)
    activity = domain_activity(conn, days=days)

    return {
        "question": question,
        "query_terms": query_terms,
        "relevant_captures": relevant_captures,
        "recent_captures": [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "domains": row["domains"] or "",
                "raw_text": row["raw_text"],
            }
            for row in recent
        ],
        "threads": threads,
        "recent_domain_activity": [
            {"name": row["name"], "capture_count": row["capture_count"]}
            for row in activity[:5]
        ],
        "used_recent_fallback": used_recent_fallback,
    }


def render_context_packet(context_packet: dict[str, Any]) -> str:
    lines = [f"Question: {context_packet['question']}"]
    if context_packet.get("query_terms"):
        lines.append(f"Query terms: {', '.join(context_packet['query_terms'])}")
    lines.append("")

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
        lines.append("Relevant threads:")
        for row in threads:
            lines.extend(_render_thread(row))
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


def render_capture(row: Any) -> str:
    payload = dict(row)
    domains = payload["domains"] or "none"
    details = f"- [{payload['id']}] {payload['created_at']} | domains: {domains}"
    matched_terms = payload.get("matched_terms") or []
    if matched_terms:
        details = f"{details} | matched: {', '.join(matched_terms)}"
    return f"{details}\n  {payload['raw_text']}"


def _merge_capture_candidates(*groups: list[Any]) -> list[dict[str, Any]]:
    merged: dict[str, dict[str, Any]] = {}
    for group in groups:
        for row in group:
            merged[row["id"]] = dict(row)
    return list(merged.values())


def _rank_relevant_captures(
    rows: list[dict[str, Any]],
    *,
    query_terms: list[str],
    days: int,
    conn: Any,
) -> tuple[list[dict[str, Any]], bool]:
    scored = []
    for row in rows:
        matched_terms = _matched_terms(query_terms, row["raw_text"], row.get("domains", ""))
        if matched_terms:
            scored.append(
                (
                    len(matched_terms),
                    row["created_at"],
                    row["id"],
                    {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "domains": row.get("domains") or "",
                        "raw_text": row["raw_text"],
                        "matched_terms": matched_terms,
                    },
                )
            )

    if scored:
        scored.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
        return [item[3] for item in scored[:6]], False

    fallback = recent_captures(conn, limit=6, days=days)
    return (
        [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "domains": row["domains"] or "",
                "raw_text": row["raw_text"],
                "matched_terms": [],
            }
            for row in fallback
        ],
        True,
    )


def _rank_relevant_threads(conn: Any, *, query_terms: list[str]) -> list[dict[str, Any]]:
    if not query_terms:
        return []

    scored: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    for thread in list_threads(conn, limit=12):
        bundle = get_thread_bundle(conn, thread["id"])
        current_state = _serialize_current_state(bundle.get("current_state"))
        surface_matches = _matched_terms(
            query_terms,
            thread["title"],
            thread.get("canonical_summary", ""),
            thread.get("domains", ""),
        )
        state_matches = _matched_terms(
            query_terms,
            thread["status"],
            *(_thread_state_terms(current_state) if current_state is not None else ()),
        )
        citations = _select_thread_citations(bundle, query_terms=query_terms)
        evidence_matches = sorted({term for row in citations for term in row["matched_terms"]})
        if not surface_matches and not state_matches and not evidence_matches:
            continue
        matched_term_set = {*surface_matches, *state_matches, *evidence_matches}
        matched_terms = [term for term in query_terms if term in matched_term_set]
        scored.append(
            (
                (
                    len(surface_matches) + len(state_matches) + min(1, len(evidence_matches)),
                    len(state_matches),
                    len(surface_matches),
                    len(evidence_matches),
                    float(thread["salience"]),
                    thread["last_seen_at"],
                    thread["id"],
                ),
                {
                    "id": thread["id"],
                    "title": thread["title"],
                    "kind": thread["kind"],
                    "status": thread["status"],
                    "salience": thread["salience"],
                    "confidence": thread["confidence"],
                    "last_seen_at": thread["last_seen_at"],
                    "domains": thread.get("domains") or "",
                    "summary": thread.get("canonical_summary") or "",
                    "matched_terms": matched_terms,
                    "current_state": current_state,
                    "citations": citations,
                },
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:4]]


def _select_thread_citations(bundle: dict[str, Any], *, query_terms: list[str]) -> list[dict[str, Any]]:
    scored = []
    for row in bundle.get("thread_evidence", []):
        matched_terms = _matched_terms(query_terms, row["raw_text"])
        scored.append(
            (
                (1 if matched_terms else 0, len(matched_terms), row["created_at"], row["capture_id"]),
                {
                    "capture_id": row["capture_id"],
                    "created_at": row["created_at"],
                    "raw_text": row["raw_text"],
                    "relation": row["relation"],
                    "subject_type": "thread",
                    "matched_terms": matched_terms,
                },
            )
        )
    for row in bundle.get("state_evidence", []):
        matched_terms = _matched_terms(query_terms, row["raw_text"])
        scored.append(
            (
                (1 if matched_terms else 0, len(matched_terms), row["created_at"], row["capture_id"]),
                {
                    "capture_id": row["capture_id"],
                    "created_at": row["created_at"],
                    "raw_text": row["raw_text"],
                    "relation": row["relation"],
                    "subject_type": "thread_state",
                    "state_id": row["state_id"],
                    "matched_terms": matched_terms,
                },
            )
        )
    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:3]]


def _serialize_current_state(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {
        "id": row["id"],
        "observed_at": row["observed_at"],
        "attention": row["attention"],
        "pressure": row["pressure"],
        "posture": row["posture"],
        "momentum": row["momentum"],
        "affect": row["affect"],
        "horizon": row["horizon"],
        "confidence": row["confidence"],
    }


def _thread_state_terms(current_state: dict[str, Any]) -> tuple[str, ...]:
    return (
        current_state["attention"],
        current_state["pressure"],
        current_state["posture"],
        current_state["momentum"],
        current_state["affect"],
        current_state["horizon"],
    )


def _render_thread(row: dict[str, Any]) -> list[str]:
    lines = [
        f"- [{row['id']}] {row['title']} [{row['kind']}] status={row['status']} "
        f"salience={float(row['salience']):.2f}"
    ]
    if row.get("domains"):
        lines.append(f"  domains: {row['domains']}")
    if row.get("matched_terms"):
        lines.append(f"  matched: {', '.join(row['matched_terms'])}")
    if row.get("summary"):
        lines.append(f"  summary: {row['summary']}")
    state = row.get("current_state")
    if state is not None:
        lines.append(
            "  state: "
            f"attention={state['attention']} pressure={state['pressure']} posture={state['posture']} "
            f"momentum={state['momentum']} horizon={state['horizon']}"
        )
    citations = row.get("citations") or []
    if citations:
        lines.append("  citations:")
        for citation in citations:
            matched_suffix = ""
            if citation["matched_terms"]:
                matched_suffix = f" | matched: {', '.join(citation['matched_terms'])}"
            lines.append(
                f"  - [{citation['capture_id']}] {citation['subject_type']} {citation['relation']} "
                f"| {citation['created_at']}{matched_suffix}"
            )
            lines.append(f"    {citation['raw_text']}")
    return lines


def _extract_query_terms(text: str) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for token in re.findall(r"[a-zA-Z]{3,}", text.lower()):
        normalized = _normalize_token(token)
        if normalized in STOPWORDS or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ordered


def _matched_terms(query_terms: list[str], *texts: str) -> list[str]:
    if not query_terms:
        return []
    haystack = set()
    for text in texts:
        haystack.update(_extract_query_terms(text or ""))
    return [term for term in query_terms if term in haystack]


def _normalize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token
