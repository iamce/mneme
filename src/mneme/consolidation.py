from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import re
from typing import Any

from .db import create_artifact
from .memory import create_thread, link_evidence, record_thread_state


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
class ConsolidationCandidate:
    domain: str
    title: str
    kind: str
    summary: str
    capture_ids: tuple[str, ...]
    state: dict[str, Any]
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
    candidates: tuple[ConsolidationCandidate, ...]
    skipped: tuple[dict[str, Any], ...]

    def as_dict(self, *, dry_run: bool) -> dict[str, Any]:
        return {
            "dry_run": dry_run,
            "days": self.days,
            "limit": self.limit,
            "scanned_capture_count": self.scanned_capture_count,
            "eligible_capture_count": self.eligible_capture_count,
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
    if not plan.candidates:
        result.update(
            {
                "created_thread_count": 0,
                "updated_thread_count": 0,
                "state_count": 0,
                "consolidated": [],
                "summary": _render_consolidation_report(plan, [], 0, 0),
            }
        )
        return result

    consolidated: list[dict[str, Any]] = []
    processed_capture_ids: list[str] = []
    created_count = 0
    updated_count = 0

    for candidate in plan.candidates:
        if candidate.match is None:
            thread_id = create_thread(
                conn,
                title=candidate.title,
                kind=candidate.kind,
                summary=candidate.summary,
                domains=[candidate.domain],
                evidence_ids=candidate.capture_ids,
                salience=candidate.salience,
                confidence=candidate.confidence,
            )
            created_count += 1
        else:
            thread_id = candidate.match.id
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
            evidence_ids=candidate.capture_ids,
        )

        processed_capture_ids.extend(candidate.capture_ids)
        consolidated.append(
            {
                "action": candidate.action,
                "thread_id": thread_id,
                "state_id": state_id,
                "title": candidate.title,
                "capture_ids": list(candidate.capture_ids),
            }
        )

    text_output = _render_consolidation_report(plan, consolidated, created_count, updated_count)
    artifact_id = create_artifact(
        conn,
        artifact_type="summary",
        target_type="system",
        target_id=None,
        model="local-consolidation",
        content={
            "days": days,
            "limit": limit,
            "created_thread_count": created_count,
            "updated_thread_count": updated_count,
            "consolidated": consolidated,
            "skipped": [dict(row) for row in plan.skipped],
        },
        text_output=text_output,
    )
    for capture_id in processed_capture_ids:
        link_evidence(
            conn,
            subject_type="artifact",
            subject_id=artifact_id,
            capture_id=capture_id,
            relation="supports",
            confidence=0.6,
        )

    result.update(
        {
            "artifact_id": artifact_id,
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

    for capture in captures:
        primary_domain = capture.primary_domain
        if primary_domain is None:
            skipped.append({"capture_id": capture.id, "reason": "missing_domain"})
            continue
        grouped[primary_domain].append(capture)

    candidates: list[ConsolidationCandidate] = []
    for domain, rows in grouped.items():
        rows = sorted(rows, key=lambda row: row.created_at, reverse=True)
        if len(rows) < 2 and not any(_is_urgent(row.raw_text) for row in rows):
            skipped.append(
                {
                    "domain": domain,
                    "capture_ids": [row.id for row in rows],
                    "reason": "insufficient_signal",
                }
            )
            continue

        topic_terms = _topic_terms(rows, domain=domain)
        kind = _infer_kind(rows, domain=domain)
        title = _build_title(domain, kind=kind, topic_terms=topic_terms)
        summary = _build_summary(rows, domain=domain)
        confidence = round(min(0.9, 0.45 + (len(rows) * 0.1) + (len(topic_terms) * 0.05)), 2)
        salience = _infer_salience(rows)
        match = _match_existing_thread(conn, domain=domain, title=title, topic_terms=topic_terms, kind=kind)
        state = _infer_state(rows, confidence=confidence)
        candidates.append(
            ConsolidationCandidate(
                domain=domain,
                title=title,
                kind=kind,
                summary=summary,
                capture_ids=tuple(row.id for row in rows),
                state=state,
                salience=salience,
                confidence=confidence,
                match=match,
            )
        )

    return ConsolidationPlan(
        days=days,
        limit=limit,
        scanned_capture_count=len(captures),
        eligible_capture_count=sum(len(rows) for rows in grouped.values()),
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
    domain_token = domain.lower()
    for capture in captures:
        for token in _tokens(capture.raw_text):
            if token == domain_token or token in STOPWORDS:
                continue
            counts[token] += 1
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

    return {
        "attention": "active" if urgent or len(captures) >= 3 else "background",
        "pressure": pressure,
        "posture": posture,
        "momentum": momentum,
        "affect": affect,
        "horizon": horizon,
        "confidence": confidence,
    }


def _match_existing_thread(
    conn: Any,
    *,
    domain: str,
    title: str,
    topic_terms: list[str],
    kind: str,
) -> ThreadMatch | None:
    rows = conn.execute(
        """
        SELECT t.id, t.title, t.canonical_summary, t.kind
        FROM threads AS t
        JOIN thread_domains AS td ON td.thread_id = t.id
        JOIN domains AS d ON d.id = td.domain_id
        WHERE LOWER(d.name) = ?
          AND t.status != 'closed'
        ORDER BY t.last_seen_at DESC
        """,
        (domain.lower(),),
    ).fetchall()
    if not rows:
        return None

    lowered_title = title.lower()
    for row in rows:
        if row["title"].lower() == lowered_title:
            return ThreadMatch(id=row["id"], title=row["title"])

    topic_token_set = set(topic_terms)
    best_match: ThreadMatch | None = None
    best_score = 0.0
    for row in rows:
        haystack = set(_tokens(f"{row['title']} {row['canonical_summary']}"))
        score = float(len(topic_token_set & haystack))
        if row["kind"] == kind:
            score += 0.25
        if score >= 1.0 and score > best_score:
            best_score = score
            best_match = ThreadMatch(id=row["id"], title=row["title"])
    return best_match


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


def _render_consolidation_report(
    plan: ConsolidationPlan,
    consolidated: list[dict[str, Any]],
    created_count: int,
    updated_count: int,
) -> str:
    lines = [
        f"Consolidation window: last {plan.days} day(s)",
        f"Scanned captures: {plan.scanned_capture_count}",
        f"Candidates applied: {len(consolidated)}",
        f"Threads created: {created_count}",
        f"Threads updated: {updated_count}",
    ]
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
