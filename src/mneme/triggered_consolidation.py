from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .artifacts import store_consolidation_run_artifact
from .consolidation import build_consolidation_plan, consolidate_recent_captures


TRIGGER_SOURCES = ("capture", "schedule", "manual")
EXECUTION_MODES = ("skip", "preview", "apply")
REVIEW_REQUIRED_SKIP_REASONS = frozenset(
    {"ambiguous_match", "ambiguous_topic", "insufficient_signal", "low_overlap"}
)


@dataclass(frozen=True)
class TriggeredConsolidationDecision:
    trigger: str
    execution_mode: str
    reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "trigger": self.trigger,
            "execution_mode": self.execution_mode,
            "decision_reason": self.reason,
        }


def decide_triggered_consolidation(
    plan: Any,
    *,
    trigger: str,
) -> TriggeredConsolidationDecision:
    if trigger not in TRIGGER_SOURCES:
        raise ValueError(f"Unsupported trigger: {trigger}")

    if not plan.thread_merges and not plan.candidates:
        return TriggeredConsolidationDecision(
            trigger=trigger,
            execution_mode="skip",
            reason="no_actionable_work",
        )

    if trigger == "capture":
        return TriggeredConsolidationDecision(
            trigger=trigger,
            execution_mode="preview",
            reason="capture_trigger_requires_preview",
        )

    if any(row["reason"] in REVIEW_REQUIRED_SKIP_REASONS for row in plan.skipped):
        return TriggeredConsolidationDecision(
            trigger=trigger,
            execution_mode="preview",
            reason="reviewable_skips_present",
        )

    return TriggeredConsolidationDecision(
        trigger=trigger,
        execution_mode="apply",
        reason="schedule_safe_to_apply" if trigger == "schedule" else "manual_trigger_requests_apply",
    )


def run_triggered_consolidation(
    conn: Any,
    *,
    trigger: str,
    days: int = 7,
    limit: int = 25,
) -> dict[str, Any]:
    plan = build_consolidation_plan(conn, days=days, limit=limit)
    decision = decide_triggered_consolidation(plan, trigger=trigger)

    if decision.execution_mode == "apply":
        result = consolidate_recent_captures(
            conn,
            days=days,
            limit=limit,
            trigger=decision.trigger,
            execution_mode=decision.execution_mode,
            decision_reason=decision.reason,
        )
        result.update(decision.as_dict())
        return result

    summary = _render_triggered_consolidation_report(plan, decision=decision)
    artifact_id = store_consolidation_run_artifact(
        conn,
        days=days,
        limit=limit,
        scanned_capture_count=plan.scanned_capture_count,
        eligible_capture_count=plan.eligible_capture_count,
        thread_merges=[merge.as_dict() for merge in plan.thread_merges],
        candidate_count=len(plan.candidates),
        created_thread_count=0,
        updated_thread_count=0,
        state_count=0,
        consolidated=[],
        skipped=[dict(row) for row in plan.skipped],
        text_output=summary,
        evidence_capture_ids=_collect_capture_ids(plan),
        run_metadata={
            "dry_run": True,
            "trigger": decision.trigger,
            "execution_mode": decision.execution_mode,
            "decision_reason": decision.reason,
        },
    )

    result = plan.as_dict(dry_run=True)
    result.update(
        {
            "artifact_id": artifact_id,
            "merged_thread_count": 0,
            "created_thread_count": 0,
            "updated_thread_count": 0,
            "state_count": 0,
            "consolidated": [],
            "summary": summary,
            **decision.as_dict(),
        }
    )
    return result


def _collect_capture_ids(plan: Any) -> list[str]:
    ordered_capture_ids: list[str] = []
    seen: set[str] = set()

    def record(capture_id: str) -> None:
        if capture_id in seen:
            return
        seen.add(capture_id)
        ordered_capture_ids.append(capture_id)

    for candidate in plan.candidates:
        for capture_id in candidate.capture_ids:
            record(capture_id)
    for row in plan.skipped:
        if "capture_id" in row:
            record(row["capture_id"])
        for capture_id in row.get("capture_ids", ()):
            record(capture_id)

    return ordered_capture_ids


def _render_triggered_consolidation_report(
    plan: Any,
    *,
    decision: TriggeredConsolidationDecision,
) -> str:
    lines = [
        f"Triggered consolidation: {decision.trigger}",
        f"Execution mode: {decision.execution_mode}",
        f"Decision reason: {decision.reason}",
        f"Consolidation window: last {plan.days} day(s)",
        f"Scanned captures: {plan.scanned_capture_count}",
        f"Existing thread merges: {len(plan.thread_merges)}",
        f"Candidates available: {len(plan.candidates)}",
    ]

    if plan.thread_merges:
        lines.append("")
        lines.append("Planned thread merges:")
        for row in plan.thread_merges:
            merge = row.as_dict()
            terms = ", ".join(merge["shared_terms"]) if merge["shared_terms"] else "none"
            lines.append(
                f"- {merge['duplicate_thread_title']} -> {merge['canonical_thread_title']} "
                f"({merge['reason']}, shared: {terms})"
            )

    if plan.candidates:
        lines.append("")
        lines.append("Candidates:")
        for candidate in plan.candidates:
            lines.append(
                f"- {candidate.action}: {candidate.title} ({len(candidate.capture_ids)} capture(s))"
            )

    if plan.skipped:
        lines.append("")
        lines.append("Skipped:")
        for row in plan.skipped:
            if "capture_id" in row:
                lines.append(f"- {row['capture_id']}: {row['reason']}")
            else:
                lines.append(f"- {row['domain']}: {row['reason']}")

    return "\n".join(lines)
