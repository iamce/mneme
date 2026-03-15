from __future__ import annotations

import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .artifacts import summarize_answer_citations, summarize_question_answer_provenance
from .db import connect, initialize, insert_capture
from .memory import create_thread, record_thread_state, update_thread
from .retrieval import build_context_packet
from .retrieval_eval_cases import (
    RetrievalEvalCase,
    built_in_retrieval_eval_cases,
)


@dataclass(frozen=True)
class RetrievalEvalResult:
    name: str
    passed: bool
    errors: tuple[str, ...] = ()


def run_retrieval_eval_cases(
    cases: tuple[RetrievalEvalCase, ...] | None = None,
) -> list[RetrievalEvalResult]:
    selected_cases = cases or built_in_retrieval_eval_cases()
    return [_run_retrieval_eval_case(case) for case in selected_cases]


def render_retrieval_eval_report(results: list[RetrievalEvalResult]) -> str:
    passed = sum(1 for result in results if result.passed)
    failed = len(results) - passed
    lines = [
        f"retrieval_eval_cases: {len(results)}",
        f"passed: {passed}",
        f"failed: {failed}",
    ]
    for result in results:
        lines.append(f"- {result.name}: {'ok' if result.passed else 'fail'}")
        for error in result.errors:
            lines.append(f"  {error}")
    return "\n".join(lines)


def _run_retrieval_eval_case(case: RetrievalEvalCase) -> RetrievalEvalResult:
    errors: list[str] = []
    with tempfile.TemporaryDirectory() as tempdir:
        conn = connect(Path(tempdir) / "mneme.db")
        initialize(conn)

        capture_ids: dict[str, str] = {}
        capture_refs_by_id: dict[str, str] = {}
        for capture_seed in case.captures:
            capture = insert_capture(
                conn,
                raw_text=capture_seed.raw_text,
                domains=list(capture_seed.domains),
            )
            if capture_seed.age_minutes:
                conn.execute(
                    "UPDATE captures SET created_at = ? WHERE id = ?",
                    (_timestamp_for_age(capture_seed.age_minutes), capture.id),
                )
            capture_ids[capture_seed.ref] = capture.id
            capture_refs_by_id[capture.id] = capture_seed.ref
        conn.commit()

        thread_ids: dict[str, str] = {}
        thread_refs_by_id: dict[str, str] = {}
        for thread_seed in case.threads:
            thread_id = create_thread(
                conn,
                title=thread_seed.title,
                kind=thread_seed.kind,
                summary=thread_seed.summary,
                domains=thread_seed.domains,
                status=thread_seed.status,
                salience=thread_seed.salience,
                confidence=thread_seed.confidence,
                evidence_ids=[capture_ids[ref] for ref in thread_seed.evidence_capture_refs],
            )
            thread_ids[thread_seed.ref] = thread_id
            thread_refs_by_id[thread_id] = thread_seed.ref
        conn.commit()

        state_ids: dict[str, str] = {}
        state_refs_by_id: dict[str, str] = {}
        for state_seed in case.thread_states:
            state_id = record_thread_state(
                conn,
                thread_id=thread_ids[state_seed.thread_ref],
                attention=state_seed.attention,
                pressure=state_seed.pressure,
                posture=state_seed.posture,
                momentum=state_seed.momentum,
                affect=state_seed.affect,
                horizon=state_seed.horizon,
                confidence=state_seed.confidence,
                evidence_ids=[capture_ids[ref] for ref in state_seed.evidence_capture_refs],
            )
            state_ids[state_seed.ref] = state_id
            state_refs_by_id[state_id] = state_seed.ref
            if state_seed.age_minutes:
                conn.execute(
                    "UPDATE thread_states SET observed_at = ? WHERE id = ?",
                    (_timestamp_for_age(state_seed.age_minutes), state_id),
                )
        conn.commit()
        for thread_seed in case.threads:
            if not thread_seed.age_minutes:
                continue
            timestamp = _timestamp_for_age(thread_seed.age_minutes)
            thread_id = thread_ids[thread_seed.ref]
            update_thread(conn, thread_id=thread_id, last_seen_at=timestamp)
            conn.execute(
                """
                UPDATE threads
                SET created_at = ?, updated_at = ?, first_seen_at = ?
                WHERE id = ?
                """,
                (timestamp, timestamp, timestamp, thread_id),
            )
        conn.commit()

        packet = build_context_packet(conn, case.question, days=30)
        retrieval_summary, _ = summarize_question_answer_provenance(packet)

        actual_capture_refs = tuple(
            capture_refs_by_id[row["id"]] for row in packet.get("relevant_captures", [])
        )
        actual_thread_refs = tuple(
            thread_refs_by_id[row["id"]] for row in packet.get("threads", [])
        )
        _append_mismatch(
            errors,
            label="relevant captures",
            actual=actual_capture_refs,
            expected=case.expected_relevant_capture_refs,
        )
        _append_mismatch(
            errors,
            label="threads",
            actual=actual_thread_refs,
            expected=case.expected_thread_refs,
        )
        if bool(packet.get("used_recent_fallback")) != case.used_recent_fallback:
            errors.append(
                "used_recent_fallback: "
                f"expected {str(case.used_recent_fallback).lower()}; "
                f"got {str(bool(packet.get('used_recent_fallback'))).lower()}"
            )

        if case.citation is not None:
            cited_capture_ids = [
                *[capture_ids[ref] for ref in case.citation.ai_cited_capture_refs],
                *case.citation.ai_unsupported_capture_ids,
            ]
            citation_summary = summarize_answer_citations(
                text_output=_render_ai_citation_text(cited_capture_ids),
                retrieval_summary=retrieval_summary,
                provider="openai",
            )
            expected_cited_capture_ids = tuple(
                _ordered_unique(
                    [
                        *[capture_ids[ref] for ref in case.citation.ai_cited_capture_refs],
                        *case.citation.ai_unsupported_capture_ids,
                    ]
                )
            )
            expected_supported_capture_refs = (
                case.citation.supported_capture_refs or case.citation.ai_cited_capture_refs
            )
            actual_supported_capture_refs = tuple(
                capture_refs_by_id[capture_id]
                for capture_id in citation_summary.get("supported_capture_ids", [])
            )
            if citation_summary["status"] != case.citation.status:
                errors.append(
                    f"citation status: expected {case.citation.status}; "
                    f"got {citation_summary['status']}"
                )
            _append_mismatch(
                errors,
                label="cited captures",
                actual=tuple(citation_summary.get("cited_capture_ids", [])),
                expected=expected_cited_capture_ids,
            )
            _append_mismatch(
                errors,
                label="supported cited captures",
                actual=actual_supported_capture_refs,
                expected=expected_supported_capture_refs,
            )
            actual_cited_thread_refs = tuple(
                thread_refs_by_id[thread_id]
                for thread_id in citation_summary.get("cited_thread_ids", [])
            )
            actual_cited_state_refs = tuple(
                state_refs_by_id[state_id]
                for state_id in citation_summary.get("cited_state_ids", [])
            )
            _append_mismatch(
                errors,
                label="cited threads",
                actual=actual_cited_thread_refs,
                expected=case.citation.cited_thread_refs,
            )
            _append_mismatch(
                errors,
                label="cited states",
                actual=actual_cited_state_refs,
                expected=case.citation.cited_state_refs,
            )
            _append_mismatch(
                errors,
                label="unsupported cited captures",
                actual=tuple(citation_summary.get("unsupported_capture_ids", [])),
                expected=case.citation.unsupported_capture_ids,
            )

        conn.close()

    return RetrievalEvalResult(
        name=case.name,
        passed=not errors,
        errors=tuple(errors),
    )


def _append_mismatch(
    errors: list[str],
    *,
    label: str,
    actual: tuple[str, ...],
    expected: tuple[str, ...],
) -> None:
    if actual == expected:
        return
    errors.append(
        f"{label}: expected {_render_values(expected)}; got {_render_values(actual)}"
    )


def _render_ai_citation_text(capture_ids: list[str]) -> str:
    citations = "\n".join(f"- {capture_id}" for capture_id in capture_ids)
    return (
        "Answer\nEvaluation placeholder.\n\n"
        "Observations\n- Placeholder.\n\n"
        "Uncertainties\n- Placeholder.\n\n"
        f"Citations\n{citations}"
    )


def _render_values(values: tuple[str, ...]) -> str:
    return ", ".join(values) if values else "none"


def _ordered_unique(values: list[str]) -> list[str]:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        ordered.append(value)
    return ordered


def _timestamp_for_age(age_minutes: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).replace(
        microsecond=0
    ).isoformat()
