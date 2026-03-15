from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from .artifacts import summarize_answer_citations, summarize_question_answer_provenance
from .db import connect, initialize, insert_capture
from .memory import create_thread, record_thread_state
from .retrieval import build_context_packet


@dataclass(frozen=True)
class CaptureSeed:
    ref: str
    raw_text: str
    domains: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadSeed:
    ref: str
    title: str
    kind: str
    summary: str = ""
    domains: tuple[str, ...] = ()
    status: str = "open"
    salience: float = 0.5
    confidence: float = 0.5
    evidence_capture_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class ThreadStateSeed:
    ref: str
    thread_ref: str
    attention: str
    pressure: str
    posture: str
    momentum: str
    affect: str
    horizon: str
    confidence: float = 0.5
    evidence_capture_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class CitationExpectation:
    ai_cited_capture_refs: tuple[str, ...] = ()
    ai_unsupported_capture_ids: tuple[str, ...] = ()
    status: str = "ok"
    cited_thread_refs: tuple[str, ...] = ()
    cited_state_refs: tuple[str, ...] = ()
    unsupported_capture_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class RetrievalEvalCase:
    name: str
    question: str
    captures: tuple[CaptureSeed, ...]
    expected_relevant_capture_refs: tuple[str, ...]
    used_recent_fallback: bool
    threads: tuple[ThreadSeed, ...] = ()
    thread_states: tuple[ThreadStateSeed, ...] = ()
    expected_thread_refs: tuple[str, ...] = ()
    citation: CitationExpectation | None = None


@dataclass(frozen=True)
class RetrievalEvalResult:
    name: str
    passed: bool
    errors: tuple[str, ...] = ()


def built_in_retrieval_eval_cases() -> tuple[RetrievalEvalCase, ...]:
    return (
        RetrievalEvalCase(
            name="tax_receipts_direct_match",
            question="What is the status of my tax receipts?",
            captures=(
                CaptureSeed(
                    ref="tax_note",
                    raw_text="Taxes are overdue and I need to file them this weekend.",
                    domains=("Money",),
                ),
                CaptureSeed(
                    ref="receipt_note",
                    raw_text="I am still missing tax receipts needed for filing.",
                    domains=("Money",),
                ),
                CaptureSeed(
                    ref="groceries_note",
                    raw_text="Need to buy groceries and refill soap.",
                    domains=("Home",),
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="tax_thread",
                    title="File overdue taxes",
                    kind="obligation",
                    summary="Finish tax filing and gather missing receipts.",
                    domains=("Money",),
                    salience=0.9,
                    evidence_capture_refs=("tax_note",),
                ),
            ),
            thread_states=(
                ThreadStateSeed(
                    ref="tax_state",
                    thread_ref="tax_thread",
                    attention="active",
                    pressure="high",
                    posture="blocked",
                    momentum="stable",
                    affect="draining",
                    horizon="now",
                    evidence_capture_refs=("receipt_note",),
                ),
            ),
            expected_relevant_capture_refs=("receipt_note", "tax_note"),
            expected_thread_refs=("tax_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("receipt_note",),
                status="ok",
                cited_thread_refs=("tax_thread",),
                cited_state_refs=("tax_state",),
            ),
        ),
        RetrievalEvalCase(
            name="blocked_now_thread_support",
            question="What is blocked right now?",
            captures=(
                CaptureSeed(
                    ref="stalled_capture",
                    raw_text="Tax filing is still waiting on missing receipts.",
                    domains=("Money",),
                ),
                CaptureSeed(
                    ref="other_capture",
                    raw_text="Blocked on a package delivery.",
                    domains=("Home",),
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="filing_thread",
                    title="Finish filing",
                    kind="obligation",
                    summary="Close out the filing workflow.",
                    domains=("Money",),
                    salience=0.4,
                    evidence_capture_refs=("stalled_capture",),
                ),
                ThreadSeed(
                    ref="kitchen_thread",
                    title="Restock kitchen",
                    kind="obligation",
                    summary="Buy missing supplies.",
                    domains=("Home",),
                    salience=0.9,
                    evidence_capture_refs=("other_capture",),
                ),
            ),
            thread_states=(
                ThreadStateSeed(
                    ref="filing_state",
                    thread_ref="filing_thread",
                    attention="active",
                    pressure="high",
                    posture="blocked",
                    momentum="stable",
                    affect="draining",
                    horizon="now",
                    evidence_capture_refs=("stalled_capture",),
                ),
            ),
            expected_relevant_capture_refs=("stalled_capture", "other_capture"),
            expected_thread_refs=("filing_thread", "kitchen_thread"),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("stalled_capture",),
                status="ok",
                cited_thread_refs=("filing_thread",),
                cited_state_refs=("filing_state",),
            ),
        ),
        RetrievalEvalCase(
            name="recent_fallback_no_match",
            question="Meditation retreat planning",
            captures=(
                CaptureSeed(
                    ref="recent_capture",
                    raw_text="Need to buy groceries and refill soap.",
                    domains=("Home",),
                ),
            ),
            expected_relevant_capture_refs=("recent_capture",),
            expected_thread_refs=(),
            used_recent_fallback=True,
        ),
        RetrievalEvalCase(
            name="unsupported_ai_citation",
            question="What is the status of my tax receipts?",
            captures=(
                CaptureSeed(
                    ref="supported_capture",
                    raw_text="Still missing tax receipts for filing.",
                    domains=("Money",),
                ),
            ),
            expected_relevant_capture_refs=("supported_capture",),
            expected_thread_refs=(),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("supported_capture",),
                ai_unsupported_capture_ids=("cap_deadbeefcafe",),
                status="unsupported_citations_present",
                unsupported_capture_ids=("cap_deadbeefcafe",),
            ),
        ),
    )


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
            capture_ids[capture_seed.ref] = capture.id
            capture_refs_by_id[capture.id] = capture_seed.ref

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
            if citation_summary["status"] != case.citation.status:
                errors.append(
                    f"citation status: expected {case.citation.status}; "
                    f"got {citation_summary['status']}"
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
