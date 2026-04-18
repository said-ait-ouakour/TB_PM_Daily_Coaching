"""Best-effort extraction of human-readable NAC call text from customernacfeedbacks rows."""

from __future__ import annotations

from typing import Any, Dict, List

# Ordered: first non-empty value wins per row (matches common Supabase column naming).
NAC_TEXT_FIELD_KEYS: tuple[str, ...] = (
    "nac_summary",
    "nac_feedback",
    "feedback_summary",
    "feedback",
    "summary",
    "call_summary",
    "notes",
    "transcript",
)


def extract_nac_feedback_texts(calls: List[Dict[str, Any]]) -> List[str]:
    """Return one snippet per call row when any known feedback/summary field is present."""
    texts: List[str] = []
    for row in calls:
        for key in NAC_TEXT_FIELD_KEYS:
            val = row.get(key)
            if val is None:
                continue
            s = str(val).strip()
            if s:
                texts.append(s)
                break
    return texts
