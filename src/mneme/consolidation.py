from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any

from .artifacts import store_consolidation_run_artifact
from .db import create_artifact
from .memory import create_thread, link_evidence, record_thread_state, update_thread
from .thread_merges import (
    ExistingThread,
    ThreadMergePlan,
    apply_thread_merges,
    build_thread_merge_plans,
    load_active_threads_by_domain,
    project_threads_after_merge,
)


STOPWORDS = {
    "and",
    "about",
    "are",
    "after",
    "again",
    "been",
    "few",
    "for",
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
    "still",
    "need",
    "needs",
    "thing",
    "things",
    "really",
    "getting",
}

KIND_CUES = {
    "decision": {"decide", "decision", "choose", "chose", "option", "options", "pick"},
    "obligation": {
        "book",
        "call",
        "file",
        "finish",
        "fix",
        "must",
        "need",
        "pay",
        "renew",
        "schedule",
        "send",
        "submit",
    },
    "concern": {
        "afraid",
        "anxious",
        "behind",
        "issue",
        "late",
        "overwhelmed",
        "problem",
        "risk",
        "stress",
        "stuck",
        "worry",
    },
    "relationship": {
        "coworker",
        "dad",
        "family",
        "friend",
        "manager",
        "mom",
        "partner",
        "team",
    },
    "workstream": {
        "build",
        "client",
        "launch",
        "milestone",
        "plan",
        "project",
        "roadmap",
        "ship",
        "work",
    },
    "idea": {"could", "draft", "experiment", "explore", "idea", "maybe"},
}

PRESSURE_CUES = {
    "acute": {"asap", "deadline", "immediately", "overdue", "today", "urgent"},
    "high": {"behind", "late", "soon", "tomorrow", "week"},
}
POSTURE_CUES = {
    "blocked": {"blocked", "cannot", "cant", "stuck"},
    "avoided": {"avoid", "avoiding", "delay", "delaying", "procrastinating"},
    "waiting": {"awaiting", "pending", "wait", "waiting"},
    "decided": {"decide", "decided", "picked"},
    "unclear": {"maybe", "unclear", "unsure"},
}
MOMENTUM_CUES = {
    "progressing": {"done", "finished", "moving", "progress", "shipped"},
    "drifting": {"avoid", "behind", "delay", "delaying", "drifting", "procrastinating", "stuck"},
}
AFFECT_CUES = {
    "draining": {"anxious", "drained", "overwhelmed", "stress", "stressed", "tired", "worry"},
    "energizing": {"energized", "excited", "fun", "looking", "momentum"},
}
NOW_CUES = {"deadline", "overdue", "today", "tomorrow", "urgent"}
SOON_CUES = {"next", "soon", "week"}
CLOSED_CUES = {"booked", "done", "filed", "finished", "paid", "resolved", "sent", "shipped", "submitted"}
DORMANT_CUES = {"backburner", "defer", "deferred", "eventually", "later", "parked", "paused", "someday"}
MATCH_NOISE = (
    STOPWORDS
    | NOW_CUES
    | SOON_CUES
    | {token for tokens in KIND_CUES.values() for token in tokens}
    | {token for tokens in PRESSURE_CUES.values() for token in tokens}
    | {token for tokens in POSTURE_CUES.values() for token in tokens}
    | {token for tokens in MOMENTUM_CUES.values() for token in tokens}
    | {token for tokens in AFFECT_CUES.values() for token in tokens}
    | {"due", "latest", "missing", "note", "notes", "recent"}
)


@dataclass(frozen=True)
class CaptureInput:
    id: str
    created_at: str
    raw_text: str
    domains: tuple[str, ...]

    @property
    def primary_domain(self) -> str | None:
        return self.domains[0] if self.domains else None


@dataclass(frozen=True)
class ThreadMatch:
    id: str
    title: str


@dataclass(frozen=True)
class ThreadMatchResult:
    match: ThreadMatch | None = None
    reason: str | None = None


@dataclass(frozen=True)
class ConsolidationCandidate:
    domain: str
    title: str
    kind: str
    summary: str
    capture_ids: tuple[str, ...]
    state: dict[str, Any]
    status: str
    salience: float
    confidence: float
    match: ThreadMatch | None

    @property
    def action(self) -> str:
        return "update_thread" if self.match is not None else "create_thread"

    def as_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "domain": self.domain,
            "title": self.title,
            "kind": self.kind,
            "summary": self.summary,
            "capture_ids": list(self.capture_ids),
            "state": dict(self.state),
            "status": self.status,
            "salience": self.salience,
            "confidence": self.confidence,
            "matched_thread_id": self.match.id if self.match else None,
            "matched_thread_title": self.match.title if self.match else None,
        }


@dataclass(frozen=True)
class ConsolidationPlan:
    days: int
    limit: int
    scanned_capture_count: int
    eligible_capture_count: int
    thread_merges: tuple[ThreadMergePlan, ...]
    candidates: tuple[ConsolidationCandidate, ...]
    skipped: tuple[dict[str, Any], ...]

    def as_dict(self, *, dry_run: bool) -> dict[str, Any]:
        return {
            "dry_run": dry_run,
            "days": self.days,
            "limit": self.limit,
            "scanned_capture_count": self.scanned_capture_count,
            "eligible_capture_count": self.eligible_capture_count,
            "thread_merge_count": len(self.thread_merges),
            "thread_merges": [plan.as_dict() for plan in self.thread_merges],
            "candidate_count": len(self.candidates),
            "candidates": [candidate.as_dict() for candidate in self.candidates],
            "skipped": [dict(row) for row in self.skipped],
        }


def consolidate_recent_captures(
    conn: Any,
    *,
    days: int = 7,
    limit: int = 25,
    dry_run: bool = False,
) -> dict[str, Any]:
    plan = build_consolidation_plan(conn, days=days, limit=limit)
    result = plan.as_dict(dry_run=dry_run)
    if dry_run:
        return result
    merged_threads = apply_thread_merges(
        conn,
        plan.thread_merges,
        merge_summary=_merge_thread_summary,
    )
    if not plan.candidates:
        text_output = _render_consolidation_report(plan, merged_threads, [], 0, 0)
        artifact_id = store_consolidation_run_artifact(
            conn,
            days=days,
            limit=limit,
            scanned_capture_count=plan.scanned_capture_count,
            eligible_capture_count=plan.eligible_capture_count,
            thread_merges=merged_threads,
            candidate_count=len(plan.candidates),
            created_thread_count=0,
            updated_thread_count=0,
            state_count=0,
            consolidated=[],
            skipped=[dict(row) for row in plan.skipped],
            text_output=text_output,
        )
        result.update(
            {
                "artifact_id": artifact_id,
                "merged_thread_count": len(merged_threads),
                "thread_merges": merged_threads,
                "created_thread_count": 0,
                "updated_thread_count": 0,
                "state_count": 0,
                "consolidated": [],
                "summary": text_output,
            }
        )
        return result

    consolidated: list[dict[str, Any]] = []
    processed_capture_ids: list[str] = []
    created_count = 0
    updated_count = 0

    for candidate in plan.candidates:
        previous_thread: dict[str, Any] | None = None
        if candidate.match is None:
            thread_id = create_thread(
                conn,
                title=candidate.title,
                kind=candidate.kind,
                summary=candidate.summary,
                domains=[candidate.domain],
                status=candidate.status,
                evidence_ids=candidate.capture_ids,
                salience=candidate.salience,
                confidence=candidate.confidence,
            )
            created_count += 1
        else:
            thread_id = candidate.match.id
            previous_thread = _load_thread_snapshot(conn, thread_id)
            update_thread(
                conn,
                thread_id=thread_id,
                title=candidate.title,
                kind=candidate.kind,
                summary=_merge_thread_summary(previous_thread["canonical_summary"], candidate.summary),
                status=candidate.status,
                salience=max(candidate.salience, previous_thread["salience"]),
                confidence=max(candidate.confidence, previous_thread["confidence"]),
            )
            _attach_new_thread_evidence(conn, thread_id=thread_id, capture_ids=candidate.capture_ids)
            updated_count += 1

        state_id = record_thread_state(
            conn,
            thread_id=thread_id,
            attention=candidate.state["attention"],
            pressure=candidate.state["pressure"],
            posture=candidate.state["posture"],
            momentum=candidate.state["momentum"],
            affect=candidate.state["affect"],
            horizon=candidate.state["horizon"],
            confidence=candidate.state["confidence"],
            status=candidate.status,
            evidence_ids=candidate.capture_ids,
        )
        thread_artifact_id = _store_thread_lifecycle_artifact(
            conn,
            candidate=candidate,
            thread_id=thread_id,
            state_id=state_id,
            previous_thread=previous_thread,
        )

        processed_capture_ids.extend(candidate.capture_ids)
        consolidated.append(
            {
                "action": candidate.action,
                "thread_id": thread_id,
                "state_id": state_id,
                "artifact_id": thread_artifact_id,
                "title": candidate.title,
                "status": candidate.status,
                "capture_ids": list(candidate.capture_ids),
            }
        )

    text_output = _render_consolidation_report(
        plan,
        merged_threads,
        consolidated,
        created_count,
        updated_count,
    )
    artifact_id = store_consolidation_run_artifact(
        conn,
        days=days,
        limit=limit,
        scanned_capture_count=plan.scanned_capture_count,
        eligible_capture_count=plan.eligible_capture_count,
        thread_merges=merged_threads,
        candidate_count=len(plan.candidates),
        created_thread_count=created_count,
        updated_thread_count=updated_count,
        state_count=len(consolidated),
        consolidated=consolidated,
        skipped=[dict(row) for row in plan.skipped],
        text_output=text_output,
        evidence_capture_ids=processed_capture_ids,
    )

    result.update(
        {
            "artifact_id": artifact_id,
            "merged_thread_count": len(merged_threads),
            "thread_merges": merged_threads,
            "created_thread_count": created_count,
            "updated_thread_count": updated_count,
            "state_count": len(consolidated),
            "consolidated": consolidated,
            "summary": text_output,
        }
    )
    return result


def build_consolidation_plan(conn: Any, *, days: int = 7, limit: int = 25) -> ConsolidationPlan:
    captures = _load_recent_unlinked_captures(conn, days=days, limit=limit)
    skipped: list[dict[str, Any]] = []
    grouped: dict[str, list[CaptureInput]] = defaultdict(list)
    active_threads = load_active_threads_by_domain(conn)
    thread_merges = build_thread_merge_plans(
        active_threads,
        tokenize=lambda text, current_domain: _normalized_signal_tokens(text, domain=current_domain),
    )
    projected_threads = project_threads_after_merge(
        active_threads,
        thread_merges,
        merge_summary=_merge_thread_summary,
    )

    for capture in captures:
        primary_domain = capture.primary_domain
        if primary_domain is None:
            skipped.append({"capture_id": capture.id, "reason": "missing_domain"})
            continue
        grouped[primary_domain].append(capture)

    candidates: list[ConsolidationCandidate] = []
    for domain, rows in grouped.items():
        rows = sorted(rows, key=lambda row: row.created_at, reverse=True)
        clusters, cluster_skips = _cluster_domain_captures(rows, domain=domain)
        skipped.extend(cluster_skips)

        for cluster in clusters:
            topic_terms = _topic_terms(cluster, domain=domain)
            match_terms = _match_terms(cluster, domain=domain)
            if not topic_terms:
                skipped.append(
                    {
                        "domain": domain,
                        "capture_ids": [row.id for row in cluster],
                        "reason": "ambiguous_topic",
                    }
                )
                continue

            kind = _infer_kind(cluster, domain=domain)
            title = _build_title(domain, kind=kind, topic_terms=topic_terms)
            summary = _build_summary(cluster, domain=domain)
            confidence = round(min(0.9, 0.45 + (len(cluster) * 0.1) + (len(topic_terms) * 0.05)), 2)
            salience = _infer_salience(cluster)
            match_result = _match_existing_thread(
                projected_threads.get(domain, ()),
                domain=domain,
                title=title,
                topic_terms=match_terms,
                kind=kind,
            )
            if match_result.reason is not None:
                skipped.append(
                    {
                        "domain": domain,
                        "capture_ids": [row.id for row in cluster],
                        "reason": match_result.reason,
                    }
                )
                continue
            if len(cluster) == 1 and match_result.match is None and not _is_urgent(cluster[0].raw_text):
                skipped.append(
                    {
                        "domain": domain,
                        "capture_ids": [row.id for row in cluster],
                        "reason": "low_overlap" if len(rows) > 1 else "insufficient_signal",
                    }
                )
                continue

            state = _infer_state(cluster, confidence=confidence)
            status = _infer_thread_status(cluster, state=state)
            candidates.append(
                ConsolidationCandidate(
                    domain=domain,
                    title=title,
                    kind=kind,
                    summary=summary,
                    capture_ids=tuple(row.id for row in cluster),
                    state=state,
                    status=status,
                    salience=salience,
                    confidence=confidence,
                    match=match_result.match,
                )
            )

    return ConsolidationPlan(
        days=days,
        limit=limit,
        scanned_capture_count=len(captures),
        eligible_capture_count=sum(len(rows) for rows in grouped.values()),
        thread_merges=thread_merges,
        candidates=tuple(candidates),
        skipped=tuple(skipped),
    )


def _load_recent_unlinked_captures(conn: Any, *, days: int, limit: int) -> list[CaptureInput]:
    rows = conn.execute(
        """
        WITH recent AS (
          SELECT c.id, c.created_at, c.raw_text
          FROM captures AS c
          WHERE datetime(c.created_at) >= datetime('now', ?)
            AND NOT EXISTS (
              SELECT 1
              FROM evidence_links AS el
              WHERE el.capture_id = c.id
            )
          ORDER BY c.created_at DESC
          LIMIT ?
        )
        SELECT
          recent.id,
          recent.created_at,
          recent.raw_text,
          d.name AS domain_name
        FROM recent
        LEFT JOIN capture_domains AS cd ON cd.capture_id = recent.id
        LEFT JOIN domains AS d ON d.id = cd.domain_id
        ORDER BY recent.created_at DESC, d.sort_order ASC
        """,
        (f"-{days} days", limit),
    ).fetchall()

    captures: dict[str, CaptureInput] = {}
    domains_by_capture: dict[str, list[str]] = defaultdict(list)
    for row in rows:
        capture_id = row["id"]
        if capture_id not in captures:
            captures[capture_id] = CaptureInput(
                id=capture_id,
                created_at=row["created_at"],
                raw_text=row["raw_text"],
                domains=(),
            )
        if row["domain_name"]:
            domains_by_capture[capture_id].append(row["domain_name"])

    result: list[CaptureInput] = []
    for capture_id, capture in captures.items():
        result.append(
            CaptureInput(
                id=capture.id,
                created_at=capture.created_at,
                raw_text=capture.raw_text,
                domains=tuple(domains_by_capture.get(capture_id, [])),
            )
        )
    return result


def _topic_terms(captures: list[CaptureInput], *, domain: str, limit: int = 3) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    first_seen: dict[str, int] = {}
    index = 0
    for capture in captures:
        for token in _signal_token_list(capture.raw_text, domain=domain):
            counts[token] += 1
            first_seen.setdefault(token, index)
            index += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], first_seen[item[0]], item[0]))
    return [term for term, _count in ordered[:limit]]


def _match_terms(captures: list[CaptureInput], *, domain: str, limit: int = 6) -> list[str]:
    counts: dict[str, int] = defaultdict(int)
    for capture in captures:
        for token in _signal_token_list(capture.raw_text, domain=domain):
            counts[_normalize_match_token(token)] += 1
    ordered = sorted(counts.items(), key=lambda item: (-item[1], item[0]))
    return [term for term, _count in ordered[:limit]]


def _infer_kind(captures: list[CaptureInput], *, domain: str) -> str:
    tokens = _combined_tokens(captures)
    scores = {kind: 0 for kind in KIND_CUES}
    for kind, cues in KIND_CUES.items():
        scores[kind] = sum(1 for token in tokens if token in cues)

    if domain == "Work":
        scores["workstream"] += 1
    if domain in {"Money", "Home", "Body", "Family", "Stability"}:
        scores["obligation"] += 1

    kind, score = max(scores.items(), key=lambda item: item[1])
    if score > 0:
        return kind
    if domain == "Work":
        return "workstream"
    if _contains_any(tokens, PRESSURE_CUES["acute"] | PRESSURE_CUES["high"]):
        return "obligation"
    return "concern"


def _build_title(domain: str, *, kind: str, topic_terms: list[str]) -> str:
    if not topic_terms:
        return f"{domain}: recent {kind}"
    if len(topic_terms) == 1:
        return f"{domain}: {topic_terms[0]}"
    return f"{domain}: {topic_terms[0]} and {topic_terms[1]}"


def _build_summary(captures: list[CaptureInput], *, domain: str) -> str:
    lead = captures[0]
    snippets = ", ".join(_snippet(row.raw_text) for row in captures[:3])
    count = len(captures)
    suffix = "capture" if count == 1 else "captures"
    return f"{domain} consolidation from {count} recent {suffix}. Latest note: {_snippet(lead.raw_text)}. Notes: {snippets}."


def _infer_salience(captures: list[CaptureInput]) -> float:
    tokens = _combined_tokens(captures)
    value = 0.45 + (len(captures) * 0.1)
    if _contains_any(tokens, PRESSURE_CUES["acute"]):
        value += 0.15
    elif _contains_any(tokens, PRESSURE_CUES["high"]):
        value += 0.05
    return round(min(0.95, value), 2)


def _infer_state(captures: list[CaptureInput], *, confidence: float) -> dict[str, Any]:
    tokens = _combined_tokens(captures)
    urgent = _contains_any(tokens, PRESSURE_CUES["acute"])
    high_pressure = urgent or _contains_any(tokens, PRESSURE_CUES["high"])

    if urgent:
        pressure = "acute"
    elif high_pressure or len(captures) >= 3:
        pressure = "high"
    elif len(captures) >= 2:
        pressure = "medium"
    else:
        pressure = "low"

    posture = "clear"
    for candidate in ("blocked", "avoided", "waiting", "decided", "unclear"):
        if _contains_any(tokens, POSTURE_CUES[candidate]):
            posture = candidate
            break
    if posture == "clear" and any("?" in capture.raw_text for capture in captures):
        posture = "unclear"

    if _contains_any(tokens, MOMENTUM_CUES["progressing"]):
        momentum = "progressing"
    elif _contains_any(tokens, MOMENTUM_CUES["drifting"]):
        momentum = "drifting"
    else:
        momentum = "stable"

    if _contains_any(tokens, AFFECT_CUES["draining"]):
        affect = "draining"
    elif _contains_any(tokens, AFFECT_CUES["energizing"]):
        affect = "energizing"
    else:
        affect = "neutral"

    if urgent or _contains_any(tokens, NOW_CUES):
        horizon = "now"
    elif _contains_any(tokens, SOON_CUES) or len(captures) >= 2:
        horizon = "soon"
    else:
        horizon = "later"

    if urgent or len(captures) >= 3:
        attention = "active"
    elif _contains_any(tokens, DORMANT_CUES):
        attention = "dormant"
    else:
        attention = "background"

    return {
        "attention": attention,
        "pressure": pressure,
        "posture": posture,
        "momentum": momentum,
        "affect": affect,
        "horizon": horizon,
        "confidence": confidence,
    }


def _infer_thread_status(captures: list[CaptureInput], *, state: dict[str, Any]) -> str:
    tokens = _combined_tokens(captures)
    if _contains_any(tokens, CLOSED_CUES) and not _contains_any(tokens, PRESSURE_CUES["acute"]):
        return "closed"
    if state["attention"] == "dormant":
        return "dormant"
    if state["horizon"] == "later" and state["pressure"] == "low" and state["posture"] in {"clear", "waiting"}:
        return "dormant"
    return "open"


def _match_existing_thread(
    threads: tuple[ExistingThread, ...],
    *,
    domain: str,
    title: str,
    topic_terms: list[str],
    kind: str,
) -> ThreadMatchResult:
    if not threads:
        return ThreadMatchResult()

    lowered_title = title.lower()
    for thread in threads:
        if thread.title.lower() == lowered_title:
            return ThreadMatchResult(match=ThreadMatch(id=thread.id, title=thread.title))

    topic_token_set = {_normalize_match_token(term) for term in topic_terms}
    if not topic_token_set:
        return ThreadMatchResult()

    scored_matches: list[tuple[float, ThreadMatch]] = []
    for thread in threads:
        haystack = _normalized_signal_tokens(
            thread.search_text,
            domain=domain,
        )
        shared = topic_token_set & haystack
        if not shared:
            continue

        overlap = len(shared) / len(topic_token_set)
        if len(shared) < 2 and overlap < 0.6:
            continue

        score = overlap + min(0.25, len(shared) * 0.1)
        if thread.kind == kind:
            score += 0.15
        scored_matches.append((score, ThreadMatch(id=thread.id, title=thread.title)))

    if not scored_matches:
        return ThreadMatchResult()

    scored_matches.sort(key=lambda item: item[0], reverse=True)
    if len(scored_matches) > 1 and abs(scored_matches[0][0] - scored_matches[1][0]) < 0.15:
        return ThreadMatchResult(reason="ambiguous_match")
    return ThreadMatchResult(match=scored_matches[0][1])


def _cluster_domain_captures(
    captures: list[CaptureInput],
    *,
    domain: str,
) -> tuple[list[list[CaptureInput]], list[dict[str, Any]]]:
    if len(captures) <= 1:
        return [captures] if captures else [], []

    adjacency: dict[int, set[int]] = {index: set() for index in range(len(captures))}
    for left_index, left in enumerate(captures):
        left_tokens = _normalized_signal_tokens(left.raw_text, domain=domain)
        for right_index in range(left_index + 1, len(captures)):
            right_tokens = _normalized_signal_tokens(captures[right_index].raw_text, domain=domain)
            shared = left_tokens & right_tokens
            if not shared:
                continue
            overlap = len(shared) / max(1, min(len(left_tokens), len(right_tokens)))
            if len(shared) >= 2 or overlap >= 0.5:
                adjacency[left_index].add(right_index)
                adjacency[right_index].add(left_index)

    visited: set[int] = set()
    clusters: list[list[CaptureInput]] = []
    skipped: list[dict[str, Any]] = []

    for index in range(len(captures)):
        if index in visited:
            continue

        stack = [index]
        component: list[CaptureInput] = []
        while stack:
            current = stack.pop()
            if current in visited:
                continue
            visited.add(current)
            component.append(captures[current])
            stack.extend(sorted(adjacency[current] - visited))

        component.sort(key=lambda row: row.created_at, reverse=True)
        clusters.append(component)

    return clusters, skipped


def _attach_new_thread_evidence(conn: Any, *, thread_id: str, capture_ids: tuple[str, ...]) -> None:
    existing = {
        row["capture_id"]
        for row in conn.execute(
            """
            SELECT capture_id
            FROM evidence_links
            WHERE subject_type = 'thread' AND subject_id = ?
            """,
            (thread_id,),
        ).fetchall()
    }
    for capture_id in capture_ids:
        if capture_id in existing:
            continue
        link_evidence(
            conn,
            subject_type="thread",
            subject_id=thread_id,
            capture_id=capture_id,
            relation="updates",
            confidence=0.65,
        )


def _load_thread_snapshot(conn: Any, thread_id: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT id, title, kind, status, canonical_summary, salience, confidence
        FROM threads
        WHERE id = ?
        """,
        (thread_id,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Unknown thread: {thread_id}")
    return dict(row)


def _store_thread_lifecycle_artifact(
    conn: Any,
    *,
    candidate: ConsolidationCandidate,
    thread_id: str,
    state_id: str,
    previous_thread: dict[str, Any] | None,
) -> str:
    current_thread = _load_thread_snapshot(conn, thread_id)
    content = {
        "action": candidate.action,
        "thread_id": thread_id,
        "state_id": state_id,
        "capture_ids": list(candidate.capture_ids),
        "status_before": previous_thread["status"] if previous_thread else None,
        "status_after": current_thread["status"],
        "summary_before": previous_thread["canonical_summary"] if previous_thread else None,
        "summary_after": current_thread["canonical_summary"],
        "title_before": previous_thread["title"] if previous_thread else None,
        "title_after": current_thread["title"],
    }
    artifact_id = create_artifact(
        conn,
        artifact_type="summary",
        target_type="thread",
        target_id=thread_id,
        model="local-consolidation",
        content=content,
        text_output=_render_thread_lifecycle_note(content),
    )
    for capture_id in candidate.capture_ids:
        link_evidence(
            conn,
            subject_type="artifact",
            subject_id=artifact_id,
            capture_id=capture_id,
            relation="updates" if candidate.action == "update_thread" else "supports",
            confidence=candidate.confidence,
        )
    return artifact_id


def _render_thread_lifecycle_note(content: dict[str, Any]) -> str:
    lines = [
        f"Thread action: {content['action']}",
        f"Status: {content['status_before'] or 'none'} -> {content['status_after']}",
        f"Title: {content['title_after']}",
    ]
    if content["summary_after"]:
        lines.append(f"Summary: {content['summary_after']}")
    return "\n".join(lines)


def _merge_thread_summary(previous_summary: str, new_summary: str) -> str:
    if not previous_summary or previous_summary == new_summary:
        return new_summary
    earlier = _snippet(previous_summary, limit=140)
    if earlier in new_summary:
        return new_summary
    return f"{new_summary} Earlier context: {earlier}"


def _render_consolidation_report(
    plan: ConsolidationPlan,
    merged_threads: list[dict[str, Any]],
    consolidated: list[dict[str, Any]],
    created_count: int,
    updated_count: int,
) -> str:
    lines = [
        f"Consolidation window: last {plan.days} day(s)",
        f"Scanned captures: {plan.scanned_capture_count}",
        f"Existing thread merges: {len(merged_threads)}",
        f"Candidates applied: {len(consolidated)}",
        f"Threads created: {created_count}",
        f"Threads updated: {updated_count}",
    ]
    if plan.thread_merges:
        lines.append("")
        lines.append("Thread merges:")
        merge_rows = merged_threads or [merge.as_dict() for merge in plan.thread_merges]
        for row in merge_rows:
            terms = ", ".join(row["shared_terms"]) if row["shared_terms"] else "none"
            lines.append(
                f"- {row['duplicate_thread_title']} -> {row['canonical_thread_title']} "
                f"({row['reason']}, shared: {terms})"
            )
    if consolidated:
        lines.append("")
        lines.append("Applied:")
        for row in consolidated:
            lines.append(f"- {row['action']}: {row['title']} ({len(row['capture_ids'])} capture(s))")
    if plan.skipped:
        lines.append("")
        lines.append("Skipped:")
        for row in plan.skipped:
            if "capture_id" in row:
                lines.append(f"- {row['capture_id']}: {row['reason']}")
            else:
                lines.append(f"- {row['domain']}: {row['reason']}")
    return "\n".join(lines)


def _combined_tokens(captures: list[CaptureInput]) -> list[str]:
    tokens: list[str] = []
    for capture in captures:
        tokens.extend(_tokens(capture.raw_text))
    return tokens


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z]{3,}", text.lower())


def _signal_tokens(text: str, *, domain: str) -> set[str]:
    return set(_signal_token_list(text, domain=domain))


def _normalized_signal_tokens(text: str, *, domain: str) -> set[str]:
    return {_normalize_match_token(token) for token in _signal_token_list(text, domain=domain)}


def _signal_token_list(text: str, *, domain: str) -> list[str]:
    domain_token = domain.lower()
    return [token for token in _tokens(text) if token != domain_token and token not in MATCH_NOISE]


def _normalize_match_token(token: str) -> str:
    if token.endswith("ies") and len(token) > 4:
        return f"{token[:-3]}y"
    if token.endswith("es") and len(token) > 4 and token[-3] not in {"a", "e", "i", "o", "u"}:
        return token[:-2]
    if token.endswith("s") and len(token) > 4 and not token.endswith("ss"):
        return token[:-1]
    return token


def _contains_any(tokens: list[str], choices: set[str]) -> bool:
    token_set = set(tokens)
    return any(choice in token_set for choice in choices)


def _snippet(text: str, *, limit: int = 72) -> str:
    collapsed = " ".join(text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3].rstrip()}..."


def _is_urgent(text: str) -> bool:
    tokens = _tokens(text)
    return _contains_any(tokens, PRESSURE_CUES["acute"] | PRESSURE_CUES["high"])
