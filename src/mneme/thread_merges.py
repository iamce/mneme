from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
import json
import re
from typing import Any, Callable

from .db import new_id, now_utc


STATUS_PRIORITY = {"open": 2, "dormant": 1, "closed": 0}


@dataclass(frozen=True)
class ExistingThread:
    id: str
    title: str
    kind: str
    status: str
    canonical_summary: str
    first_seen_at: str
    last_seen_at: str
    salience: float
    confidence: float
    domain: str
    evidence_text: str

    @property
    def search_text(self) -> str:
        return f"{self.title} {self.canonical_summary} {self.evidence_text}".strip()


@dataclass(frozen=True)
class ThreadMergePlan:
    domain: str
    canonical_id: str
    canonical_title: str
    duplicate_id: str
    duplicate_title: str
    reason: str
    score: float
    overlap: float
    shared_terms: tuple[str, ...]
    same_kind: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "domain": self.domain,
            "canonical_thread_id": self.canonical_id,
            "canonical_thread_title": self.canonical_title,
            "duplicate_thread_id": self.duplicate_id,
            "duplicate_thread_title": self.duplicate_title,
            "reason": self.reason,
            "score": round(self.score, 2),
            "overlap": round(self.overlap, 2),
            "shared_terms": list(self.shared_terms),
            "same_kind": self.same_kind,
        }


@dataclass(frozen=True)
class _MergeOption:
    canonical: ExistingThread
    duplicate: ExistingThread
    reason: str
    score: float
    overlap: float
    shared_terms: tuple[str, ...]
    same_kind: bool

    def to_plan(self) -> ThreadMergePlan:
        return ThreadMergePlan(
            domain=self.canonical.domain,
            canonical_id=self.canonical.id,
            canonical_title=self.canonical.title,
            duplicate_id=self.duplicate.id,
            duplicate_title=self.duplicate.title,
            reason=self.reason,
            score=self.score,
            overlap=self.overlap,
            shared_terms=self.shared_terms,
            same_kind=self.same_kind,
        )


def load_active_threads_by_domain(conn: Any) -> dict[str, tuple[ExistingThread, ...]]:
    rows = conn.execute(
        """
        SELECT
          t.id,
          t.title,
          t.kind,
          t.status,
          t.canonical_summary,
          t.first_seen_at,
          t.last_seen_at,
          t.salience,
          t.confidence,
          d.name AS domain,
          GROUP_CONCAT(c.raw_text, ' ') AS evidence_text
        FROM threads AS t
        JOIN thread_domains AS td
          ON td.thread_id = t.id AND td.is_primary = 1
        JOIN domains AS d ON d.id = td.domain_id
        LEFT JOIN evidence_links AS el
          ON el.subject_type = 'thread' AND el.subject_id = t.id
        LEFT JOIN captures AS c ON c.id = el.capture_id
        WHERE t.status != 'closed'
        GROUP BY
          t.id,
          t.title,
          t.kind,
          t.status,
          t.canonical_summary,
          t.first_seen_at,
          t.last_seen_at,
          t.salience,
          t.confidence,
          d.name
        ORDER BY LOWER(d.name), t.last_seen_at DESC, t.id
        """
    ).fetchall()

    grouped: dict[str, list[ExistingThread]] = defaultdict(list)
    for row in rows:
        thread = ExistingThread(
            id=row["id"],
            title=row["title"],
            kind=row["kind"],
            status=row["status"],
            canonical_summary=row["canonical_summary"],
            first_seen_at=row["first_seen_at"],
            last_seen_at=row["last_seen_at"],
            salience=row["salience"],
            confidence=row["confidence"],
            domain=row["domain"],
            evidence_text=row["evidence_text"] or "",
        )
        grouped[thread.domain].append(thread)

    return {domain: tuple(rows) for domain, rows in grouped.items()}


def build_thread_merge_plans(
    threads_by_domain: dict[str, tuple[ExistingThread, ...]],
    *,
    tokenize: Callable[[str, str], set[str]],
) -> tuple[ThreadMergePlan, ...]:
    proposals: list[ThreadMergePlan] = []

    for domain, threads in sorted(threads_by_domain.items()):
        options_by_duplicate: dict[str, list[_MergeOption]] = defaultdict(list)
        duplicate_candidates: set[str] = set()
        for option in _merge_options_for_domain(domain, threads, tokenize=tokenize):
            options_by_duplicate[option.duplicate.id].append(option)
            duplicate_candidates.add(option.duplicate.id)

        for duplicate_id in sorted(duplicate_candidates):
            options = sorted(
                options_by_duplicate[duplicate_id],
                key=lambda option: (
                    -option.score,
                    option.canonical.last_seen_at,
                    option.canonical.id,
                ),
            )
            if len(options) > 1 and abs(options[0].score - options[1].score) < 0.12:
                continue

            proposals.append(options[0].to_plan())

    duplicate_ids = {plan.duplicate_id for plan in proposals}
    plans = [plan for plan in proposals if plan.canonical_id not in duplicate_ids]

    return tuple(
        sorted(
            plans,
            key=lambda plan: (
                plan.domain.lower(),
                plan.canonical_title.lower(),
                plan.duplicate_title.lower(),
            ),
        )
    )


def project_threads_after_merge(
    threads_by_domain: dict[str, tuple[ExistingThread, ...]],
    merge_plans: tuple[ThreadMergePlan, ...],
    *,
    merge_summary: Callable[[str, str], str],
) -> dict[str, tuple[ExistingThread, ...]]:
    if not merge_plans:
        return threads_by_domain

    plans_by_canonical: dict[str, list[ThreadMergePlan]] = defaultdict(list)
    merge_lookup = {plan.duplicate_id: plan for plan in merge_plans}
    threads_by_id = {
        thread.id: thread
        for rows in threads_by_domain.values()
        for thread in rows
    }

    for plan in merge_plans:
        plans_by_canonical[plan.canonical_id].append(plan)

    projected: dict[str, tuple[ExistingThread, ...]] = {}
    for domain, rows in threads_by_domain.items():
        next_rows: list[ExistingThread] = []
        for thread in rows:
            if thread.id in merge_lookup:
                continue

            merged_thread = thread
            for plan in plans_by_canonical.get(thread.id, []):
                duplicate = threads_by_id.get(plan.duplicate_id)
                if duplicate is None:
                    continue
                merged_thread = replace(
                    merged_thread,
                    canonical_summary=merge_summary(
                        merged_thread.canonical_summary,
                        duplicate.canonical_summary,
                    ),
                    first_seen_at=min(merged_thread.first_seen_at, duplicate.first_seen_at),
                    last_seen_at=max(merged_thread.last_seen_at, duplicate.last_seen_at),
                    salience=max(merged_thread.salience, duplicate.salience),
                    confidence=max(merged_thread.confidence, duplicate.confidence),
                    status=_higher_status(merged_thread.status, duplicate.status),
                    evidence_text=" ".join(
                        part
                        for part in (merged_thread.evidence_text, duplicate.evidence_text)
                        if part
                    ),
                )

            next_rows.append(merged_thread)

        projected[domain] = tuple(next_rows)

    return projected


def apply_thread_merges(
    conn: Any,
    merge_plans: tuple[ThreadMergePlan, ...],
    *,
    merge_summary: Callable[[str, str], str],
) -> list[dict[str, Any]]:
    applied: list[dict[str, Any]] = []
    for plan in merge_plans:
        canonical = conn.execute(
            """
            SELECT id, title, kind, status, canonical_summary, first_seen_at, last_seen_at, salience, confidence
            FROM threads
            WHERE id = ?
            """,
            (plan.canonical_id,),
        ).fetchone()
        duplicate = conn.execute(
            """
            SELECT id, title, kind, status, canonical_summary, first_seen_at, last_seen_at, salience, confidence
            FROM threads
            WHERE id = ?
            """,
            (plan.duplicate_id,),
        ).fetchone()
        if canonical is None or duplicate is None:
            continue

        duplicate_capture_ids = _move_thread_evidence(
            conn,
            canonical_id=plan.canonical_id,
            duplicate_id=plan.duplicate_id,
        )
        _merge_thread_domains(
            conn,
            canonical_id=plan.canonical_id,
            duplicate_id=plan.duplicate_id,
        )
        _move_thread_states(
            conn,
            canonical_id=plan.canonical_id,
            duplicate_id=plan.duplicate_id,
        )
        conn.execute(
            """
            UPDATE artifacts
            SET target_id = ?
            WHERE target_type = 'thread' AND target_id = ?
            """,
            (plan.canonical_id, plan.duplicate_id),
        )
        conn.execute(
            """
            UPDATE threads
            SET
              updated_at = ?,
              status = ?,
              canonical_summary = ?,
              first_seen_at = ?,
              last_seen_at = ?,
              salience = ?,
              confidence = ?
            WHERE id = ?
            """,
            (
                now_utc(),
                _higher_status(canonical["status"], duplicate["status"]),
                merge_summary(canonical["canonical_summary"], duplicate["canonical_summary"]),
                min(canonical["first_seen_at"], duplicate["first_seen_at"]),
                max(canonical["last_seen_at"], duplicate["last_seen_at"]),
                max(canonical["salience"], duplicate["salience"]),
                max(canonical["confidence"], duplicate["confidence"]),
                plan.canonical_id,
            ),
        )

        artifact_id = _create_merge_artifact(
            conn,
            plan=plan,
            duplicate_capture_ids=duplicate_capture_ids,
        )

        conn.execute("DELETE FROM threads WHERE id = ?", (plan.duplicate_id,))
        conn.commit()

        applied.append({**plan.as_dict(), "artifact_id": artifact_id})

    return applied


def _merge_options_for_domain(
    domain: str,
    threads: tuple[ExistingThread, ...],
    *,
    tokenize: Callable[[str, str], set[str]],
) -> list[_MergeOption]:
    options: list[_MergeOption] = []
    for left_index, left in enumerate(threads):
        left_tokens = tokenize(left.search_text, domain)
        if not left_tokens:
            continue
        for right in threads[left_index + 1 :]:
            right_tokens = tokenize(right.search_text, domain)
            if not right_tokens:
                continue

            shared_terms = tuple(sorted(left_tokens & right_tokens))
            if not shared_terms:
                continue

            overlap = len(shared_terms) / max(1, min(len(left_tokens), len(right_tokens)))
            same_kind = left.kind == right.kind
            normalized_left_title = _normalize_title(left.title)
            normalized_right_title = _normalize_title(right.title)
            if normalized_left_title == normalized_right_title:
                reason = "exact_title"
            elif same_kind and len(shared_terms) >= 3 and overlap >= 0.6:
                reason = "high_overlap"
            else:
                continue

            canonical, duplicate = _choose_keeper(left, right)
            score = overlap + min(0.35, len(shared_terms) * 0.08)
            if same_kind:
                score += 0.15
            if reason == "exact_title":
                score += 0.35
            options.append(
                _MergeOption(
                    canonical=canonical,
                    duplicate=duplicate,
                    reason=reason,
                    score=score,
                    overlap=overlap,
                    shared_terms=shared_terms[:5],
                    same_kind=same_kind,
                )
            )
    return options


def _choose_keeper(left: ExistingThread, right: ExistingThread) -> tuple[ExistingThread, ExistingThread]:
    left_rank = (left.salience, left.last_seen_at, left.confidence, left.id)
    right_rank = (right.salience, right.last_seen_at, right.confidence, right.id)
    if left_rank >= right_rank:
        return left, right
    return right, left


def _merge_thread_domains(conn: Any, *, canonical_id: str, duplicate_id: str) -> None:
    rows = conn.execute(
        """
        SELECT domain_id, weight, is_primary
        FROM thread_domains
        WHERE thread_id = ?
        """,
        (duplicate_id,),
    ).fetchall()
    canonical_has_primary = (
        conn.execute(
            """
            SELECT 1
            FROM thread_domains
            WHERE thread_id = ? AND is_primary = 1
            LIMIT 1
            """,
            (canonical_id,),
        ).fetchone()
        is not None
    )

    for row in rows:
        existing = conn.execute(
            """
            SELECT weight, is_primary
            FROM thread_domains
            WHERE thread_id = ? AND domain_id = ?
            """,
            (canonical_id, row["domain_id"]),
        ).fetchone()
        if existing is None:
            conn.execute(
                """
                INSERT INTO thread_domains (thread_id, domain_id, weight, is_primary)
                VALUES (?, ?, ?, ?)
                """,
                (
                    canonical_id,
                    row["domain_id"],
                    row["weight"],
                    0 if canonical_has_primary else row["is_primary"],
                ),
            )
            canonical_has_primary = canonical_has_primary or bool(row["is_primary"])
            continue

        conn.execute(
            """
            UPDATE thread_domains
            SET weight = ?, is_primary = ?
            WHERE thread_id = ? AND domain_id = ?
            """,
            (
                max(existing["weight"], row["weight"]),
                1 if existing["is_primary"] or (row["is_primary"] and not canonical_has_primary) else 0,
                canonical_id,
                row["domain_id"],
            ),
        )


def _move_thread_states(conn: Any, *, canonical_id: str, duplicate_id: str) -> None:
    conn.execute(
        """
        UPDATE thread_states
        SET thread_id = ?, is_current = 0
        WHERE thread_id = ?
        """,
        (canonical_id, duplicate_id),
    )
    newest_state = conn.execute(
        """
        SELECT id
        FROM thread_states
        WHERE thread_id = ?
        ORDER BY observed_at DESC, rowid DESC
        LIMIT 1
        """,
        (canonical_id,),
    ).fetchone()
    if newest_state is None:
        return

    conn.execute("UPDATE thread_states SET is_current = 0 WHERE thread_id = ?", (canonical_id,))
    conn.execute(
        "UPDATE thread_states SET is_current = 1 WHERE id = ?",
        (newest_state["id"],),
    )


def _move_thread_evidence(conn: Any, *, canonical_id: str, duplicate_id: str) -> list[str]:
    existing_capture_ids = {
        row["capture_id"]
        for row in conn.execute(
            """
            SELECT capture_id
            FROM evidence_links
            WHERE subject_type = 'thread' AND subject_id = ?
            """,
            (canonical_id,),
        ).fetchall()
    }
    duplicate_links = conn.execute(
        """
        SELECT id, capture_id
        FROM evidence_links
        WHERE subject_type = 'thread' AND subject_id = ?
        ORDER BY rowid
        """,
        (duplicate_id,),
    ).fetchall()

    moved_capture_ids: list[str] = []
    for row in duplicate_links:
        if row["capture_id"] in existing_capture_ids:
            conn.execute("DELETE FROM evidence_links WHERE id = ?", (row["id"],))
            continue
        conn.execute(
            """
            UPDATE evidence_links
            SET subject_id = ?
            WHERE id = ?
            """,
            (canonical_id, row["id"]),
        )
        existing_capture_ids.add(row["capture_id"])
        moved_capture_ids.append(row["capture_id"])
    return moved_capture_ids


def _create_merge_artifact(
    conn: Any,
    *,
    plan: ThreadMergePlan,
    duplicate_capture_ids: list[str],
) -> str:
    content = {
        "action": "merge_thread",
        "canonical_thread_id": plan.canonical_id,
        "canonical_thread_title": plan.canonical_title,
        "duplicate_thread_id": plan.duplicate_id,
        "duplicate_thread_title": plan.duplicate_title,
        "reason": plan.reason,
        "score": round(plan.score, 2),
        "overlap": round(plan.overlap, 2),
        "shared_terms": list(plan.shared_terms),
        "capture_ids": duplicate_capture_ids,
    }
    artifact_id = new_id("art")
    conn.execute(
        """
        INSERT INTO artifacts (
          id, created_at, artifact_type, target_type, target_id, model, content_json, text_output
        ) VALUES (?, ?, 'summary', 'thread', ?, 'local-consolidation', ?, ?)
        """,
        (
            artifact_id,
            now_utc(),
            plan.canonical_id,
            json.dumps(content, sort_keys=True),
            _render_merge_note(content),
        ),
    )
    for capture_id in duplicate_capture_ids:
        conn.execute(
            """
            INSERT INTO evidence_links (
              id, subject_type, subject_id, capture_id, relation, confidence, note
            ) VALUES (?, 'artifact', ?, ?, 'updates', ?, '')
            """,
            (new_id("ev"), artifact_id, capture_id, min(0.95, round(plan.score / 2, 2))),
        )
    return artifact_id


def _render_merge_note(content: dict[str, Any]) -> str:
    terms = ", ".join(content["shared_terms"]) if content["shared_terms"] else "none"
    return "\n".join(
        [
            "Thread action: merge_thread",
            f"Canonical: {content['canonical_thread_title']}",
            f"Merged duplicate: {content['duplicate_thread_title']}",
            f"Reason: {content['reason']} ({content['overlap']:.2f} overlap, shared: {terms})",
        ]
    )


def _higher_status(left: str, right: str) -> str:
    return left if STATUS_PRIORITY[left] >= STATUS_PRIORITY[right] else right


def _normalize_title(title: str) -> str:
    return re.sub(r"\s+", " ", title.strip().lower())
