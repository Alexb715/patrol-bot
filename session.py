"""Pure answer logic — validation and aggregation — with no Discord dependency
so it can be unit-tested directly.

Answer values are normalized as:
  * ``single_choice`` / ``text``  -> a ``str``
  * ``multi_choice``              -> a ``list[str]``
"""

from __future__ import annotations

from typing import Any

from questions import Question


def clean_and_validate(
    questions: list[Question] | tuple[Question, ...],
    raw: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Normalize a raw answer dict and collect any human-readable problems.

    Discord's select menus already enforce choices and min/max on the client;
    this is the authoritative backstop (and the only guard for required fields,
    which Discord can't enforce for a component the user simply never touches).
    Returns ``(cleaned_answers, errors)`` — an empty ``errors`` list means valid.
    """
    cleaned: dict[str, Any] = {}
    errors: list[str] = []

    for question in questions:
        value = raw.get(question.key)

        if question.kind == "text":
            text = value.strip() if isinstance(value, str) else ""
            if question.required and not text:
                errors.append(f"“{question.display_label()}” is required.")
            cleaned[question.key] = text

        elif question.kind == "single_choice":
            choice = value if isinstance(value, str) else ""
            if not choice:
                if question.required:
                    errors.append(f"Please answer “{question.display_label()}”.")
                cleaned[question.key] = ""
            elif choice not in question.choices:
                errors.append(f"Invalid option for “{question.display_label()}”.")
                cleaned[question.key] = ""
            else:
                cleaned[question.key] = choice

        elif question.kind == "multi_choice":
            if isinstance(value, list):
                candidates = value
            elif isinstance(value, str) and value:
                candidates = [value]
            else:
                candidates = []
            # Keep only valid choices, de-duplicated, in a stable order.
            selected: list[str] = []
            for item in candidates:
                if item in question.choices and item not in selected:
                    selected.append(item)
            lower_bound = max(question.min_select, 1)
            if question.required and len(selected) < lower_bound:
                errors.append(
                    f"Select at least {lower_bound} for “{question.display_label()}”."
                )
            if len(selected) > question.max_select:
                errors.append(
                    f"Select at most {question.max_select} for "
                    f"“{question.display_label()}”."
                )
                selected = selected[: question.max_select]
            cleaned[question.key] = selected

        else:  # pragma: no cover - guards against a mistyped kind
            errors.append(f"Unsupported question type: {question.kind}")

    return cleaned, errors


def aggregate(
    questions: list[Question] | tuple[Question, ...],
    responses: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Tally a list of cleaned answer dicts into per-question summaries for the
    results digest. Choice questions produce option counts (multi-choice options
    are counted independently, so their counts can sum beyond the respondent
    total); text questions produce the list of non-empty comments."""
    total = len(responses)
    summary: list[dict[str, Any]] = []

    for question in questions:
        if question.kind in ("single_choice", "multi_choice"):
            counts = {choice: 0 for choice in question.choices}
            for answers in responses:
                value = answers.get(question.key)
                if isinstance(value, list):
                    picks = value
                elif isinstance(value, str) and value:
                    picks = [value]
                else:
                    picks = []
                for pick in picks:
                    if pick in counts:
                        counts[pick] += 1
            summary.append(
                {
                    "question": question,
                    "kind": question.kind,
                    "total": total,
                    "counts": counts,
                }
            )
        else:  # text
            comments: list[str] = []
            for answers in responses:
                value = answers.get(question.key)
                text = value.strip() if isinstance(value, str) else ""
                if text:
                    comments.append(text)
            summary.append(
                {
                    "question": question,
                    "kind": "text",
                    "total": total,
                    "comments": comments,
                }
            )

    return summary
