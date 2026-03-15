from __future__ import annotations

import re
from typing import Any

from .db import domain_activity, recent_captures, search_captures_for_terms
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

QUERY_TERM_EQUIVALENTS = {
    "bob": ("robert", "bobby"),
    "bobby": ("bob", "robert"),
    "car": ("vehicle",),
    "checkup": ("appointment", "visit"),
    "doctor": ("physician",),
    "paper": ("registration", "paperwork"),
    "physician": ("doctor",),
    "robert": ("bob", "bobby"),
    "visit": ("appointment", "checkup"),
    "vehicle": ("car",),
    "appointment": ("visit", "checkup"),
    "registration": ("paper", "paperwork"),
}


def build_context_packet(conn: Any, question: str, *, days: int = 14) -> dict[str, Any]:
    query_terms = _extract_query_terms(question)
    candidate_terms = _candidate_search_terms(query_terms)
    recent = recent_captures(conn, limit=4, days=days)
    threads = _rank_relevant_threads(conn, query_terms=query_terms)
    capture_candidates = _merge_capture_candidates(
        search_captures_for_terms(conn, tokens=candidate_terms, limit=12),
        recent_captures(conn, limit=12, days=days),
        _capture_candidates_from_threads(threads),
    )
    relevant_captures, used_recent_fallback = _rank_relevant_captures(
        capture_candidates,
        query_terms=query_terms,
        days=days,
        conn=conn,
        threads=threads,
    )
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


def render_ranking_highlights(context_packet: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    capture = _top_ranked_row(context_packet.get("relevant_captures", []))
    if capture is not None:
        lines.append(
            "top_capture_ranking: "
            f"{capture['id']} | {render_capture_ranking_reason(capture['ranking_reason'])}"
        )

    thread = _top_ranked_row(context_packet.get("threads", []))
    if thread is not None:
        lines.append(
            "top_thread_ranking: "
            f"{thread['id']} | {render_thread_ranking_reason(thread['ranking_reason'])}"
        )

    return lines


def render_capture(row: Any) -> str:
    payload = dict(row)
    domains = payload["domains"] or "none"
    details = f"- [{payload['id']}] {payload['created_at']} | domains: {domains}"
    matched_terms = payload.get("matched_terms") or []
    thread_matched_terms = payload.get("thread_matched_terms") or []
    if matched_terms:
        details = f"{details} | matched: {', '.join(matched_terms)}"
    lines = [details]
    if thread_matched_terms:
        supporting_thread_ids = payload.get("supporting_thread_ids") or []
        support = f"thread support: {', '.join(thread_matched_terms)}"
        if supporting_thread_ids:
            support = f"{support} via {', '.join(supporting_thread_ids)}"
        lines.append(f"  {support}")
    ranking_reason = payload.get("ranking_reason")
    if ranking_reason:
        lines.append(f"  ranking: {render_capture_ranking_reason(ranking_reason)}")
    lines.append(f"  {payload['raw_text']}")
    return "\n".join(lines)


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
    threads: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], bool]:
    scored = []
    capture_thread_support = _capture_thread_support(threads)
    for row in rows:
        direct_matches = _term_matches(query_terms, row["raw_text"], row.get("domains", ""))
        matched_terms = _matched_terms_from_matches(direct_matches)
        expanded_matches = _expanded_matches_from_matches(direct_matches)
        thread_support = capture_thread_support.get(
            row["id"],
            {"matched_terms": [], "thread_ids": []},
        )
        thread_matched_terms = [
            term for term in query_terms if term in thread_support["matched_terms"] and term not in matched_terms
        ]
        combined_matched_terms = [term for term in query_terms if term in {*matched_terms, *thread_matched_terms}]
        if combined_matched_terms:
            scored.append(
                (
                    len(combined_matched_terms),
                    len(matched_terms),
                    len(thread_matched_terms),
                    row["created_at"],
                    row["id"],
                    {
                        "id": row["id"],
                        "created_at": row["created_at"],
                        "domains": row.get("domains") or "",
                        "raw_text": row["raw_text"],
                        "matched_terms": matched_terms,
                        "thread_matched_terms": thread_matched_terms,
                        "supporting_thread_ids": thread_support["thread_ids"],
                        "ranking_reason": {
                            "matched_term_count": len(combined_matched_terms),
                            "direct_match_count": len(matched_terms),
                            "thread_support_count": len(thread_matched_terms),
                            "matched_terms": combined_matched_terms,
                            **(
                                {"expanded_matches": expanded_matches}
                                if expanded_matches
                                else {}
                            ),
                        },
                    },
                )
            )

    if scored:
        scored.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]), reverse=True)
        return [item[5] for item in scored[:6]], False

    fallback = recent_captures(conn, limit=6, days=days)
    return (
        [
            {
                "id": row["id"],
                "created_at": row["created_at"],
                "domains": row["domains"] or "",
                "raw_text": row["raw_text"],
                "matched_terms": [],
                "thread_matched_terms": [],
                "supporting_thread_ids": [],
                "ranking_reason": {
                    "matched_term_count": 0,
                    "direct_match_count": 0,
                    "thread_support_count": 0,
                    "matched_terms": [],
                    "fallback": "recent",
                },
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
        surface_term_matches = _term_matches(
            query_terms,
            thread["title"],
            thread.get("canonical_summary", ""),
            thread.get("domains", ""),
        )
        surface_matches = _matched_terms_from_matches(surface_term_matches)
        surface_expanded_matches = _expanded_matches_from_matches(surface_term_matches)
        state_term_matches = _term_matches(
            query_terms,
            thread["status"],
            *(_thread_state_terms(current_state) if current_state is not None else ()),
        )
        state_matches = _matched_terms_from_matches(state_term_matches)
        state_expanded_matches = _expanded_matches_from_matches(state_term_matches)
        citations = _select_thread_citations(bundle, query_terms=query_terms)
        evidence_matches = sorted({term for row in citations for term in row["matched_terms"]})
        evidence_expanded_matches = _ordered_unique(
            [
                expanded_match
                for row in citations
                for expanded_match in row.get("expanded_matches", [])
            ]
        )
        if not surface_matches and not state_matches and not evidence_matches:
            continue
        matched_term_set = {*surface_matches, *state_matches, *evidence_matches}
        matched_terms = [term for term in query_terms if term in matched_term_set]
        expanded_matches = _ordered_unique(
            [
                *surface_expanded_matches,
                *state_expanded_matches,
                *evidence_expanded_matches,
            ]
        )
        scored.append(
            (
                (
                    len(matched_terms),
                    len(surface_matches) + len(state_matches),
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
                    "expanded_matches": expanded_matches,
                    "ranking_reason": {
                        "matched_term_count": len(matched_terms),
                        "surface_match_count": len(surface_matches),
                        "state_match_count": len(state_matches),
                        "evidence_match_count": len(evidence_matches),
                        "matched_terms": matched_terms,
                        **(
                            {"expanded_matches": expanded_matches}
                            if expanded_matches
                            else {}
                        ),
                    },
                },
            )
        )

    scored.sort(key=lambda item: item[0], reverse=True)
    return [item[1] for item in scored[:4]]


def _capture_candidates_from_threads(threads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for thread in threads:
        for citation in thread.get("citations", []):
            rows.append(
                {
                    "id": citation["capture_id"],
                    "created_at": citation["created_at"],
                    "domains": thread.get("domains") or "",
                    "raw_text": citation["raw_text"],
                }
            )
    return rows


def _capture_thread_support(threads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    support: dict[str, dict[str, Any]] = {}
    for thread in threads:
        matched_terms = list(thread.get("matched_terms", []))
        for citation in thread.get("citations", []):
            capture_support = support.setdefault(
                citation["capture_id"],
                {"matched_terms": [], "thread_ids": []},
            )
            for term in matched_terms:
                if term not in capture_support["matched_terms"]:
                    capture_support["matched_terms"].append(term)
            if thread["id"] not in capture_support["thread_ids"]:
                capture_support["thread_ids"].append(thread["id"])
    return support


def _select_thread_citations(bundle: dict[str, Any], *, query_terms: list[str]) -> list[dict[str, Any]]:
    scored = []
    for row in bundle.get("thread_evidence", []):
        term_matches = _term_matches(query_terms, row["raw_text"])
        matched_terms = _matched_terms_from_matches(term_matches)
        expanded_matches = _expanded_matches_from_matches(term_matches)
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
                    "expanded_matches": expanded_matches,
                },
            )
        )
    for row in bundle.get("state_evidence", []):
        term_matches = _term_matches(query_terms, row["raw_text"])
        matched_terms = _matched_terms_from_matches(term_matches)
        expanded_matches = _expanded_matches_from_matches(term_matches)
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
                    "expanded_matches": expanded_matches,
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
    ranking_reason = row.get("ranking_reason")
    if ranking_reason:
        lines.append(f"  ranking: {render_thread_ranking_reason(ranking_reason)}")
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
            if citation.get("expanded_matches"):
                matched_suffix = (
                    f"{matched_suffix} | expanded: "
                    f"{', '.join(citation['expanded_matches'])}"
                )
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


def _term_matches(query_terms: list[str], *texts: str) -> list[tuple[str, str]]:
    if not query_terms:
        return []
    haystack = set()
    for text in texts:
        haystack.update(_extract_query_terms(text or ""))
    matches: list[tuple[str, str]] = []
    for term in query_terms:
        matched_variant = next(
            (candidate for candidate in _query_term_variants(term) if candidate in haystack),
            None,
        )
        if matched_variant is not None:
            matches.append((term, matched_variant))
    return matches


def _matched_terms_from_matches(matches: list[tuple[str, str]]) -> list[str]:
    return [term for term, _ in matches]


def _expanded_matches_from_matches(matches: list[tuple[str, str]]) -> list[str]:
    return [
        f"{term}->{matched_variant}"
        for term, matched_variant in matches
        if term != matched_variant
    ]


def _normalize_token(token: str) -> str:
    if len(token) > 4 and token.endswith("ies"):
        return f"{token[:-3]}y"
    if len(token) > 4 and token.endswith(("ses", "xes", "zes", "ches", "shes")):
        return token[:-2]
    if len(token) > 4 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
        return token[:-1]
    return token


def _candidate_search_terms(query_terms: list[str]) -> list[str]:
    return _ordered_unique(
        [
            candidate
            for term in query_terms
            for candidate in _query_term_variants(term)
        ]
    )


def _query_term_variants(term: str) -> tuple[str, ...]:
    return (term, *QUERY_TERM_EQUIVALENTS.get(term, ()))


def _ordered_unique(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _top_ranked_row(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    for row in rows:
        if row.get("ranking_reason"):
            return row
    return None


def render_capture_ranking_reason(reason: dict[str, Any]) -> str:
    if reason.get("fallback"):
        return f"fallback={reason['fallback']}"
    matched_terms = ", ".join(reason.get("matched_terms", [])) or "none"
    rendered = (
        f"matched_terms={matched_terms}; "
        f"direct={reason.get('direct_match_count', 0)}; "
        f"thread_support={reason.get('thread_support_count', 0)}"
    )
    expanded_matches = reason.get("expanded_matches") or []
    if expanded_matches:
        rendered = f"{rendered}; expanded={', '.join(expanded_matches)}"
    return rendered


def render_thread_ranking_reason(reason: dict[str, Any]) -> str:
    matched_terms = ", ".join(reason.get("matched_terms", [])) or "none"
    rendered = (
        f"matched_terms={matched_terms}; "
        f"surface={reason.get('surface_match_count', 0)}; "
        f"state={reason.get('state_match_count', 0)}; "
        f"evidence={reason.get('evidence_match_count', 0)}"
    )
    expanded_matches = reason.get("expanded_matches") or []
    if expanded_matches:
        rendered = f"{rendered}; expanded={', '.join(expanded_matches)}"
    return rendered
