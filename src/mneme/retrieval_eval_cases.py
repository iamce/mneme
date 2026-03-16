from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CaptureSeed:
    ref: str
    raw_text: str
    domains: tuple[str, ...] = ()
    age_minutes: int = 0


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
    age_minutes: int = 0


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
    age_minutes: int = 0


@dataclass(frozen=True)
class CitationExpectation:
    ai_cited_capture_refs: tuple[str, ...] = ()
    ai_unsupported_capture_ids: tuple[str, ...] = ()
    status: str = "ok"
    supported_capture_refs: tuple[str, ...] = ()
    cited_thread_refs: tuple[str, ...] = ()
    cited_state_refs: tuple[str, ...] = ()
    unsupported_capture_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class KnownRetrievalGap:
    label: str
    target_relevant_capture_refs: tuple[str, ...] = ()
    target_thread_refs: tuple[str, ...] = ()
    target_used_recent_fallback: bool | None = None


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
    known_gap: KnownRetrievalGap | None = None


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
        RetrievalEvalCase(
            name="dormant_thread_status_support",
            question="What is dormant?",
            captures=(
                CaptureSeed(
                    ref="passport_capture",
                    raw_text="The passport renewal can wait until summer.",
                    domains=("Home",),
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="passport_thread",
                    title="Renew passport",
                    kind="obligation",
                    summary="Handle passport renewal later.",
                    domains=("Home",),
                    status="dormant",
                    salience=0.3,
                    evidence_capture_refs=("passport_capture",),
                ),
                ThreadSeed(
                    ref="travel_thread",
                    title="Book travel",
                    kind="obligation",
                    summary="Choose flights for the trip.",
                    domains=("Home",),
                    salience=0.8,
                ),
            ),
            expected_relevant_capture_refs=("passport_capture",),
            expected_thread_refs=("passport_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("passport_capture",),
                cited_thread_refs=("passport_thread",),
            ),
        ),
        RetrievalEvalCase(
            name="broader_thread_match_beats_salience",
            question="What about tax receipts?",
            captures=(
                CaptureSeed(
                    ref="partial_capture",
                    raw_text="Taxes need attention this week.",
                    domains=("Money",),
                    age_minutes=20,
                ),
                CaptureSeed(
                    ref="full_capture",
                    raw_text="Still missing tax receipts for filing.",
                    domains=("Money",),
                    age_minutes=10,
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="partial_thread",
                    title="File taxes",
                    kind="obligation",
                    summary="Handle the filing soon.",
                    domains=("Money",),
                    salience=0.95,
                    evidence_capture_refs=("partial_capture",),
                    age_minutes=20,
                ),
                ThreadSeed(
                    ref="full_thread",
                    title="Paperwork cleanup",
                    kind="obligation",
                    summary="Administrative loose ends.",
                    domains=("Money",),
                    salience=0.2,
                    evidence_capture_refs=("full_capture",),
                    age_minutes=10,
                ),
            ),
            expected_relevant_capture_refs=("full_capture", "partial_capture"),
            expected_thread_refs=("full_thread", "partial_thread"),
            used_recent_fallback=False,
        ),
        RetrievalEvalCase(
            name="citation_support_tracks_thread_and_state_shapes",
            question="What is the status of my tax receipts?",
            captures=(
                CaptureSeed(
                    ref="thread_capture",
                    raw_text="Taxes are overdue and I need to file them this weekend.",
                    domains=("Money",),
                ),
                CaptureSeed(
                    ref="state_capture",
                    raw_text="I am still missing tax receipts needed for filing.",
                    domains=("Money",),
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
                    evidence_capture_refs=("thread_capture",),
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
                    evidence_capture_refs=("state_capture",),
                ),
            ),
            expected_relevant_capture_refs=("state_capture", "thread_capture"),
            expected_thread_refs=("tax_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("thread_capture", "state_capture"),
                supported_capture_refs=("thread_capture", "state_capture"),
                cited_thread_refs=("tax_thread",),
                cited_state_refs=("tax_state",),
            ),
        ),
        RetrievalEvalCase(
            name="capture_recency_breaks_equal_direct_match_ties",
            question="Project note",
            captures=(
                CaptureSeed(
                    ref="older_capture",
                    raw_text="Project note: finalize vendor shortlist.",
                    domains=("Work",),
                    age_minutes=30,
                ),
                CaptureSeed(
                    ref="newer_capture",
                    raw_text="Project note: finalize launch checklist.",
                    domains=("Work",),
                    age_minutes=5,
                ),
            ),
            expected_relevant_capture_refs=("newer_capture", "older_capture"),
            expected_thread_refs=(),
            used_recent_fallback=False,
        ),
        RetrievalEvalCase(
            name="thread_last_seen_breaks_equal_state_match_ties",
            question="What is blocked?",
            captures=(
                CaptureSeed(
                    ref="older_capture",
                    raw_text="Waiting on vendor reply.",
                    domains=("Work",),
                    age_minutes=20,
                ),
                CaptureSeed(
                    ref="newer_capture",
                    raw_text="Waiting on legal review.",
                    domains=("Work",),
                    age_minutes=10,
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="older_thread",
                    title="Vendor renewal",
                    kind="obligation",
                    summary="Wait for procurement to answer.",
                    domains=("Work",),
                    salience=0.5,
                    age_minutes=20,
                ),
                ThreadSeed(
                    ref="newer_thread",
                    title="Contract review",
                    kind="obligation",
                    summary="Wait for legal to answer.",
                    domains=("Work",),
                    salience=0.5,
                    age_minutes=5,
                ),
            ),
            thread_states=(
                ThreadStateSeed(
                    ref="older_state",
                    thread_ref="older_thread",
                    attention="active",
                    pressure="high",
                    posture="blocked",
                    momentum="stable",
                    affect="neutral",
                    horizon="now",
                    evidence_capture_refs=("older_capture",),
                    age_minutes=20,
                ),
                ThreadStateSeed(
                    ref="newer_state",
                    thread_ref="newer_thread",
                    attention="active",
                    pressure="high",
                    posture="blocked",
                    momentum="stable",
                    affect="neutral",
                    horizon="now",
                    evidence_capture_refs=("newer_capture",),
                    age_minutes=5,
                ),
            ),
            expected_relevant_capture_refs=("newer_capture", "older_capture"),
            expected_thread_refs=("newer_thread", "older_thread"),
            used_recent_fallback=False,
        ),
        RetrievalEvalCase(
            name="wording_gap_paraphrase_vehicle_registration",
            question="What about my car papers?",
            captures=(
                CaptureSeed(
                    ref="recent_distractor",
                    raw_text="Need to buy groceries after work.",
                    domains=("Home",),
                    age_minutes=5,
                ),
                CaptureSeed(
                    ref="vehicle_capture",
                    raw_text="Need to renew vehicle registration before July.",
                    domains=("Home",),
                    age_minutes=40,
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="vehicle_thread",
                    title="Renew vehicle registration",
                    kind="obligation",
                    summary="Handle the registration renewal paperwork.",
                    domains=("Home",),
                    salience=0.8,
                    evidence_capture_refs=("vehicle_capture",),
                    age_minutes=40,
                ),
            ),
            expected_relevant_capture_refs=("vehicle_capture",),
            expected_thread_refs=("vehicle_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("vehicle_capture",),
                cited_thread_refs=("vehicle_thread",),
            ),
        ),
        RetrievalEvalCase(
            name="wording_gap_synonym_doctor_visit",
            question="What about my physician checkup?",
            captures=(
                CaptureSeed(
                    ref="recent_distractor",
                    raw_text="Replace the kitchen light bulb.",
                    domains=("Home",),
                    age_minutes=3,
                ),
                CaptureSeed(
                    ref="doctor_capture",
                    raw_text="Need to schedule a doctor appointment before June.",
                    domains=("Body",),
                    age_minutes=35,
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="doctor_thread",
                    title="Schedule doctor appointment",
                    kind="obligation",
                    summary="Book the annual doctor visit.",
                    domains=("Body",),
                    salience=0.7,
                    evidence_capture_refs=("doctor_capture",),
                    age_minutes=35,
                ),
            ),
            expected_relevant_capture_refs=("doctor_capture",),
            expected_thread_refs=("doctor_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("doctor_capture",),
                cited_thread_refs=("doctor_thread",),
            ),
        ),
        RetrievalEvalCase(
            name="wording_gap_alias_robert_bob",
            question="What do I owe Bob?",
            captures=(
                CaptureSeed(
                    ref="recent_distractor",
                    raw_text="Drop off the mail on the way home.",
                    domains=("Home",),
                    age_minutes=2,
                ),
                CaptureSeed(
                    ref="robert_capture",
                    raw_text="Need to pay Robert back for concert tickets.",
                    domains=("Social",),
                    age_minutes=30,
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="robert_thread",
                    title="Pay Robert back",
                    kind="obligation",
                    summary="Settle the concert ticket reimbursement.",
                    domains=("Social",),
                    salience=0.6,
                    evidence_capture_refs=("robert_capture",),
                    age_minutes=30,
                ),
            ),
            expected_relevant_capture_refs=("robert_capture",),
            expected_thread_refs=("robert_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("robert_capture",),
                cited_thread_refs=("robert_thread",),
            ),
        ),
        RetrievalEvalCase(
            name="wording_gap_cross_domain_reimbursement_expense_report",
            question="What do I need to get reimbursed?",
            captures=(
                CaptureSeed(
                    ref="recent_distractor",
                    raw_text="Pick up dry cleaning before dinner.",
                    domains=("Home",),
                    age_minutes=3,
                ),
                CaptureSeed(
                    ref="expense_capture",
                    raw_text="Submit expense report for hotel receipt.",
                    domains=("Work",),
                    age_minutes=35,
                ),
            ),
            threads=(
                ThreadSeed(
                    ref="expense_thread",
                    title="File expense report",
                    kind="obligation",
                    summary="Submit the reimbursement paperwork for the hotel stay.",
                    domains=("Work",),
                    salience=0.75,
                    evidence_capture_refs=("expense_capture",),
                    age_minutes=35,
                ),
            ),
            expected_relevant_capture_refs=("expense_capture",),
            expected_thread_refs=("expense_thread",),
            used_recent_fallback=False,
            citation=CitationExpectation(
                ai_cited_capture_refs=("expense_capture",),
                cited_thread_refs=("expense_thread",),
            ),
        ),
    )
