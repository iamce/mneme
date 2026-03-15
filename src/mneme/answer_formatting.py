from __future__ import annotations

import re
from typing import Any


_CITATIONS_HEADER_PATTERN = re.compile(r"(?m)^Citations\s*$")


def format_ai_answer_citations(
    *,
    text_output: str,
    context_packet: dict[str, Any],
    citation_summary: dict[str, Any],
) -> str:
    cited_capture_ids = list(citation_summary.get("cited_capture_ids", []))
    if not cited_capture_ids:
        return text_output

    evidence_index = _build_capture_evidence_index(context_packet)
    citation_lines: list[str] = []
    for capture_id in cited_capture_ids:
        evidence = evidence_index.get(capture_id)
        if evidence is None:
            citation_lines.append(f"- {capture_id} | unsupported by retrieval")
            continue

        detail_parts = list(evidence["provenance"])
        if evidence["is_relevant_capture"]:
            detail_parts.insert(0, "relevant capture")
        detail = "; ".join(detail_parts) if detail_parts else "retrieval evidence"
        citation_lines.append(f"- {capture_id} | {detail}")
        if evidence["raw_text"]:
            citation_lines.append(f"  {_summarize_capture_text(evidence['raw_text'])}")

    rendered_citations = "\n".join(citation_lines)
    match = _CITATIONS_HEADER_PATTERN.search(text_output)
    if match:
        return f"{text_output[:match.end()].rstrip()}\n{rendered_citations}"
    return f"{text_output.rstrip()}\n\nCitations\n{rendered_citations}"


def _build_capture_evidence_index(context_packet: dict[str, Any]) -> dict[str, dict[str, Any]]:
    evidence_index: dict[str, dict[str, Any]] = {}

    for row in context_packet.get("relevant_captures", []):
        entry = evidence_index.setdefault(
            row["id"],
            {"raw_text": row["raw_text"], "is_relevant_capture": False, "provenance": []},
        )
        entry["raw_text"] = entry["raw_text"] or row["raw_text"]
        entry["is_relevant_capture"] = True

    for thread in context_packet.get("threads", []):
        thread_id = thread["id"]
        for citation in thread.get("citations", []):
            entry = evidence_index.setdefault(
                citation["capture_id"],
                {
                    "raw_text": citation.get("raw_text", ""),
                    "is_relevant_capture": False,
                    "provenance": [],
                },
            )
            entry["raw_text"] = entry["raw_text"] or citation.get("raw_text", "")
            provenance = _format_thread_provenance(thread_id=thread_id, citation=citation)
            if provenance not in entry["provenance"]:
                entry["provenance"].append(provenance)

    return evidence_index


def _format_thread_provenance(*, thread_id: str, citation: dict[str, Any]) -> str:
    subject_type = citation["subject_type"]
    relation = citation["relation"]
    if subject_type == "thread_state" and citation.get("state_id"):
        return f"{subject_type} {relation} {thread_id}/{citation['state_id']}"
    return f"{subject_type} {relation} {thread_id}"


def _summarize_capture_text(raw_text: str, *, limit: int = 140) -> str:
    collapsed = " ".join(raw_text.split())
    if len(collapsed) <= limit:
        return collapsed
    return f"{collapsed[: limit - 3].rstrip()}..."
