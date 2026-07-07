"""The questionnaire content — the single file you edit each round.

To change the questions, edit `TITLE`, `DESCRIPTION`, and the `QUESTIONS` tuple
below. Nothing else needs to change. Each `Question` is rendered automatically:

  * `single_choice` / `multi_choice`  -> a dropdown select menu in the response
    form. For `multi_choice`, `min_select`/`max_select` bound how many options a
    person may pick (e.g. "up to two" -> min_select=1, max_select=2). Discord
    enforces these on the client; `session.clean_and_validate` re-checks them.
  * `text`  -> a text box shown in a modal (use `required=False` for optional
    free-form answers).

Layout limits (Discord, current form has no pagination): at most 4 choice
questions and at most 5 text questions per questionnaire. That's plenty for a
round; if you need more, the response form in cogs/questionnaire.py has a
documented extension point for pagination.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

QuestionKind = Literal["single_choice", "multi_choice", "text"]


@dataclass(frozen=True)
class Question:
    key: str  # stable identifier, used as the answers/DB key — don't reuse
    label: str  # short title shown in the results
    prompt: str  # the full question text shown to the respondent
    kind: QuestionKind = "single_choice"
    choices: tuple[str, ...] = ()  # options for the choice kinds
    min_select: int = 1  # multi_choice: fewest options allowed (when required)
    max_select: int = 1  # multi_choice: most options allowed ("up to two" -> 2)
    required: bool = True

    def display_label(self) -> str:
        return self.label or self.key.replace("_", " ").title()


TITLE = "Feedback"

DESCRIPTION = (
    "Help shape how we run patrols. This questionnaire is **anonymous** — your "
    "individual answers are never shown in this channel. Click **Respond** below "
    "to submit privately. You can update your response any time until it closes."
)


QUESTIONS: tuple[Question, ...] = (
    Question(
        key="support_trial",
        label="Two patrol nights (trial)",
        prompt=(
            "Would you support trying two dedicated patrol nights each week for a "
            "1–2 month trial?"
        ),
        kind="single_choice",
        choices=("Yes", "No", "Unsure"),
    ),
    Question(
        key="best_days",
        label="Best two days",
        prompt="Which TWO days of the week would work best for you? (Select up to two.)",
        kind="multi_choice",
        choices=(
            "Monday",
            "Tuesday",
            "Wednesday",
            "Thursday",
            "Friday",
            "Saturday",
            "Sunday",
        ),
        min_select=1,
        max_select=2,
    ),
    Question(
        key="preferred_time",
        label="Preferred time",
        prompt="What time do you usually prefer to join patrols?",
        kind="single_choice",
        choices=(
            "6:00–8:00 PM",
            "7:00–9:00 PM",
            "8:00–10:00 PM",
            "After 10:00 PM",
        ),
    ),
    Question(
        key="barriers",
        label="Biggest barriers",
        prompt=(
            "What is the biggest thing preventing you from participating more "
            "often? (Select one or more.)"
        ),
        kind="multi_choice",
        choices=(
            "Work",
            "School",
            "Family commitments",
            "I don’t know when patrols are happening.",
            "Patrols are often too quiet when I log in.",
            "I’m new and don’t know many people.",
            "I prefer civilian RP.",
            "Other",
        ),
        min_select=1,
        max_select=8,
    ),
    Question(
        key="suggestions",
        label="Suggestions",
        prompt=(
            "Anything else you’d like the leadership team to know about improving "
            "community activity?"
        ),
        kind="text",
        required=False,
    ),
)


def by_key(key: str) -> Question:
    for question in QUESTIONS:
        if question.key == key:
            return question
    raise KeyError(key)


def question_to_dict(question: Question) -> dict[str, Any]:
    """Serialize a Question for the per-questionnaire snapshot stored in the DB,
    so results always reflect exactly what was asked even if this file is edited
    while a questionnaire is still open."""
    return {
        "key": question.key,
        "label": question.label,
        "prompt": question.prompt,
        "kind": question.kind,
        "choices": list(question.choices),
        "min_select": question.min_select,
        "max_select": question.max_select,
        "required": question.required,
    }


def question_from_dict(data: dict[str, Any]) -> Question:
    return Question(
        key=data["key"],
        label=data.get("label", ""),
        prompt=data["prompt"],
        kind=data.get("kind", "single_choice"),
        choices=tuple(data.get("choices", ())),
        min_select=int(data.get("min_select", 1)),
        max_select=int(data.get("max_select", 1)),
        required=bool(data.get("required", True)),
    )
