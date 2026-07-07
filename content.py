"""Embed and text builders for everything the bot renders: the public survey
message, the private results release (header, aggregated digest, per-respondent
entries), and the response-form confirmations.

Kept separate from the cog so the presentation is easy to tweak and the pure
builders can be smoke-tested without a running bot.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import discord

from questions import Question

EMBED_FIELD_LIMIT = 1024
EMBED_TOTAL_LIMIT = 5500  # keep clear of Discord's 6000 hard cap
MAX_FIELDS_PER_EMBED = 24
_BAR_WIDTH = 12


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _rel_timestamp(when: datetime) -> str:
    """Discord relative timestamp, e.g. 'in 2 days' / '3 hours ago'."""
    return f"<t:{int(when.timestamp())}:R>"


def _full_timestamp(when: datetime) -> str:
    return f"<t:{int(when.timestamp())}:f>"


# --- Public survey message --------------------------------------------------


def build_survey_embed(
    *,
    title: str,
    description: str,
    closes_at: datetime,
    questions: list[Question],
    response_count: int | None = None,
    show_count: bool = False,
    closed: bool = False,
) -> discord.Embed:
    """The single message posted in the public channel. Reveals nothing about who
    answered; the response count is optional and, when shown, is just a number."""
    lines = [description, ""]
    for index, question in enumerate(questions, start=1):
        hint = ""
        if question.kind == "multi_choice":
            if question.max_select > 1:
                hint = f" *(pick up to {question.max_select})*"
        lines.append(f"**{index}.** {question.prompt}{hint}")

    embed = discord.Embed(
        title=title,
        description=truncate("\n".join(lines), 4096),
        color=discord.Color.greyple() if closed else discord.Color.blurple(),
    )
    if closed:
        embed.add_field(name="Status", value="✅ Closed — thanks to everyone who responded.", inline=False)
    else:
        embed.add_field(
            name="Closes",
            value=f"{_full_timestamp(closes_at)} ({_rel_timestamp(closes_at)})",
            inline=False,
        )
    if show_count and response_count is not None:
        embed.add_field(name="Responses", value=str(response_count), inline=False)
    footer = "Anonymous · one response per person · editable until it closes"
    embed.set_footer(text=footer)
    return embed


def build_form_intro_embed(title: str, editing: bool) -> discord.Embed:
    note = (
        "You've already responded — submitting again will **replace** your "
        "previous answers."
        if editing
        else "Make your selections below, then press **Submit**."
    )
    return discord.Embed(
        title=truncate(f"Respond · {title}", 256),
        description=(
            f"{note}\n\nYour answers are private — only your selections are sent, "
            "and they're never shown with your name in the public channel."
        ),
        color=discord.Color.blurple(),
    )


CONFIRM_RECORDED = (
    "✅ Your response was recorded — thank you! You can click **Respond** again "
    "to change it any time until the questionnaire closes."
)

CONFIRM_CLOSED_RACE = (
    "This questionnaire just closed, so your response wasn't recorded. Sorry for "
    "the timing!"
)

FORM_CLOSED = "This questionnaire is closed — thanks for your interest."


def build_validation_error(errors: list[str]) -> str:
    bullets = "\n".join(f"• {error}" for error in errors)
    return (
        "⚠️ Your response wasn't saved. Please fix the following and click "
        f"**Respond** again:\n{bullets}"
    )


# --- Private results release ------------------------------------------------


def build_results_header_embed(
    *, title: str, total: int, closed_at: datetime
) -> discord.Embed:
    embed = discord.Embed(
        title=truncate(f"Results · {title}", 256),
        description=(
            f"Closed {_full_timestamp(closed_at)} · **{total}** "
            f"{'response' if total == 1 else 'responses'}.\n"
            "An aggregated digest follows, then each individual response."
        ),
        color=discord.Color.green(),
    )
    embed.set_footer(text="Attributed results — keep this channel restricted to leadership.")
    return embed


def _bar(count: int, total: int) -> str:
    filled = int(round((count / total) * _BAR_WIDTH)) if total else 0
    filled = max(0, min(_BAR_WIDTH, filled))
    return "█" * filled + "░" * (_BAR_WIDTH - filled)


def _choice_field_value(counts: dict[str, int], total: int) -> str:
    if not counts:
        return "—"
    lines = []
    # Show the most-picked options first for quick reading.
    for option, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        pct = (count / total * 100) if total else 0
        lines.append(f"`{_bar(count, total)}` **{count}** ({pct:.0f}%) · {option}")
    return truncate("\n".join(lines), EMBED_FIELD_LIMIT)


def _comment_field_value(comments: list[str]) -> str:
    if not comments:
        return "*No comments.*"
    lines = [f"• {c}" for c in comments]
    value = "\n".join(lines)
    if len(value) <= EMBED_FIELD_LIMIT:
        return value
    # Fit as many whole comments as possible; note how many were cut.
    kept: list[str] = []
    used = 0
    for line in lines:
        if used + len(line) + 1 > EMBED_FIELD_LIMIT - 40:
            break
        kept.append(line)
        used += len(line) + 1
    remaining = len(lines) - len(kept)
    kept.append(f"*…and {remaining} more (see individual responses below).*")
    return "\n".join(kept)


def build_digest_embeds(title: str, aggregated: list[dict[str, Any]]) -> list[discord.Embed]:
    """Render the aggregated summary. Returns one or more embeds, splitting when
    field-count or character limits would be exceeded."""
    embeds: list[discord.Embed] = []

    def _new_embed() -> discord.Embed:
        return discord.Embed(
            title=truncate(f"Summary · {title}", 256),
            color=discord.Color.teal(),
        )

    current = _new_embed()
    used_chars = len(current.title or "")

    for entry in aggregated:
        question: Question = entry["question"]
        total = entry["total"]
        if entry["kind"] == "text":
            name = f"{question.display_label()} — {len(entry['comments'])} comment(s)"
            value = _comment_field_value(entry["comments"])
        else:
            name = question.display_label()
            if entry["kind"] == "multi_choice":
                name = f"{name} — multiple choice (of {total})"
            value = _choice_field_value(entry["counts"], total)

        name = truncate(name, 256)
        addition = len(name) + len(value)
        if len(current.fields) >= MAX_FIELDS_PER_EMBED or (
            used_chars + addition > EMBED_TOTAL_LIMIT and current.fields
        ):
            embeds.append(current)
            current = _new_embed()
            used_chars = len(current.title or "")
        current.add_field(name=name, value=value, inline=False)
        used_chars += addition

    embeds.append(current)
    return embeds


def _answer_display(question: Question, value: Any) -> str:
    if isinstance(value, list):
        return ", ".join(value) if value else "—"
    text = str(value) if value not in (None, "") else "—"
    return truncate(text, EMBED_FIELD_LIMIT)


def build_respondent_embed(
    *,
    questions: list[Question],
    response: dict[str, Any],
    index: int,
    total: int,
) -> discord.Embed:
    answers = response.get("answers", {})
    embed = discord.Embed(
        title=truncate(response.get("display_name", "Unknown"), 256),
        description=f"`{response.get('username', '')}` · <@{response.get('user_id', '')}>",
        color=discord.Color.blurple(),
    )
    for question in questions:
        embed.add_field(
            name=truncate(question.display_label(), 256),
            value=_answer_display(question, answers.get(question.key)),
            inline=False,
        )
    updated = response.get("updated_at", "")
    footer = f"Response {index}/{total}"
    if updated:
        footer = f"{footer} · submitted {updated[:16].replace('T', ' ')} UTC"
    embed.set_footer(text=footer)
    return embed


def build_results_csv(questions: list[Question], responses: list[dict[str, Any]]) -> str:
    """A CSV of attributed answers for archival. Written by hand (not the csv
    module) so it stays simple; fields are quoted and internal quotes doubled."""

    def esc(value: str) -> str:
        return '"' + str(value).replace('"', '""') + '"'

    header = ["display_name", "username", "user_id"] + [q.key for q in questions]
    rows = [",".join(esc(h) for h in header)]
    for response in responses:
        answers = response.get("answers", {})
        cells = [
            response.get("display_name", ""),
            response.get("username", ""),
            response.get("user_id", ""),
        ]
        for question in questions:
            value = answers.get(question.key)
            if isinstance(value, list):
                cells.append("; ".join(value))
            else:
                cells.append("" if value is None else str(value))
        rows.append(",".join(esc(c) for c in cells))
    return "\n".join(rows)
