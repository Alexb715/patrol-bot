"""Anonymous questionnaire feature.

Posts a questionnaire (an editable set of questions from questions.py) into a
public channel with a Respond button. Members answer privately via an ephemeral
form (dropdowns for choice questions, a modal for free text). When it closes —
after its duration or via /questionnaire close — the bot releases an aggregated
digest plus each person's attributed answers into a private results channel.

Follows patrol-bot conventions: config constants from config.py, admin_check for
gating, and the shared SQLite connection via questionnaire_db.
"""

import io
import logging
import re
from datetime import datetime, timedelta, timezone

import discord
from discord import app_commands
from discord.ext import commands, tasks

import content
from config import (
    QUESTIONNAIRE_DEFAULT_DURATION,
    QUESTIONNAIRE_PURGE_ON_RELEASE,
    QUESTIONNAIRE_RESULTS_AS_FILE,
    QUESTIONNAIRE_RESULTS_CHANNEL_ID,
    QUESTIONNAIRE_SHOW_LIVE_COUNT,
    QUESTIONNAIRE_SURVEY_CHANNEL_ID,
)
from helpers import admin_check
from questionnaire_db import (
    close_questionnaire,
    count_responses,
    create_questionnaire,
    delete_questionnaire,
    delete_responses,
    get_questionnaire,
    get_response,
    list_open_questionnaires,
    list_responses,
    set_survey_message_id,
    upsert_response,
)
from questions import (
    DESCRIPTION,
    QUESTIONS,
    TITLE,
    Question,
    question_from_dict,
    question_to_dict,
)
from session import aggregate, clean_and_validate

logger = logging.getLogger(__name__)

CLOSE_CHECK_SECONDS = 30
# Discord views allow 5 action rows; each dropdown takes one and we reserve one
# for the Submit button — so at most 4 choice questions render per form. See the
# extension note in ResponseView if a round ever needs more.
MAX_CHOICE_SELECTS = 4

RESPOND_CUSTOM_ID_TEMPLATE = r"quiz:respond:(?P<qid>\d+)"

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(raw):
    """Parse a compact duration like 48h / 30m / 2d / 1w / 1d12h into a positive
    timedelta. Raises ValueError on anything unparseable."""
    text = (raw or "").strip().lower()
    if not text:
        raise ValueError("Duration is empty.")
    if _DURATION_RE.sub("", text).strip():
        raise ValueError(
            f"Couldn't parse a duration from {raw!r} — try e.g. 48h, 30m, 2d, 1w."
        )
    total = 0
    for value, unit in _DURATION_RE.findall(text):
        total += int(value) * _UNIT_SECONDS[unit.lower()]
    if total <= 0:
        raise ValueError("Duration must be greater than zero.")
    return timedelta(seconds=total)


def _parse_dt(raw):
    parsed = datetime.fromisoformat(raw)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _questions_of(record):
    return [question_from_dict(d) for d in record["questions"]]


# --- Persistent Respond button ---------------------------------------------


class RespondButton(
    discord.ui.DynamicItem[discord.ui.Button],
    template=RESPOND_CUSTOM_ID_TEMPLATE,
):
    def __init__(self, questionnaire_id):
        super().__init__(
            discord.ui.Button(
                label="Respond",
                style=discord.ButtonStyle.success,
                emoji="\U0001f4dd",
                custom_id=f"quiz:respond:{questionnaire_id}",
            )
        )
        self.questionnaire_id = questionnaire_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(int(match["qid"]))

    async def callback(self, interaction):
        cog = interaction.client.get_cog("QuestionnaireCog")
        if not isinstance(cog, QuestionnaireCog):
            await interaction.response.send_message(
                "The questionnaire system isn't available right now.", ephemeral=True
            )
            return
        await cog.open_response_form(interaction, self.questionnaire_id)


def build_respond_view(questionnaire_id):
    view = discord.ui.View(timeout=None)
    view.add_item(RespondButton(questionnaire_id))
    return view


# --- Ephemeral response form ------------------------------------------------


class _QuestionSelect(discord.ui.Select):
    """A dropdown for one choice question. Stores the picked value(s) on the
    parent view and acknowledges without changing the message."""

    def __init__(self, question, existing):
        self.question = question
        is_multi = question.kind == "multi_choice"
        existing_set = (
            set(existing)
            if isinstance(existing, list)
            else ({existing} if existing else set())
        )
        options = [
            discord.SelectOption(
                label=content.truncate(choice, 100),
                value=content.truncate(choice, 100),
                default=choice in existing_set,
            )
            for choice in question.choices[:25]
        ]
        super().__init__(
            placeholder=content.truncate(question.prompt, 150),
            min_values=max(question.min_select, 1) if is_multi else 1,
            max_values=question.max_select if is_multi else 1,
            options=options,
        )

    async def callback(self, interaction):
        view = self.view
        if self.question.kind == "multi_choice":
            view.answers[self.question.key] = list(self.values)
        else:
            view.answers[self.question.key] = self.values[0] if self.values else ""
        await interaction.response.defer()


class _SubmitButton(discord.ui.Button):
    def __init__(self):
        super().__init__(label="Submit", style=discord.ButtonStyle.primary)

    async def callback(self, interaction):
        view = self.view
        if view.text_questions:
            await interaction.response.send_modal(ResponseModal(view))
        else:
            await view.cog.finalize_response(interaction, view, {})


class ResponseView(discord.ui.View):
    def __init__(self, *, cog, questionnaire_id, questions, existing):
        super().__init__(timeout=900)
        self.cog = cog
        self.questionnaire_id = questionnaire_id
        self.questions = questions
        self.existing = existing
        self.choice_questions = [
            q for q in questions if q.kind in ("single_choice", "multi_choice")
        ]
        self.text_questions = [q for q in questions if q.kind == "text"]
        self.answers = {
            q.key: existing[q.key] for q in self.choice_questions if q.key in existing
        }

        rendered = self.choice_questions[:MAX_CHOICE_SELECTS]
        if len(self.choice_questions) > MAX_CHOICE_SELECTS:
            # Extension point: paginate the form across multiple ephemeral
            # messages if a round ever needs more than 4 choice questions.
            logger.warning(
                "Questionnaire %s has %d choice questions; only the first %d fit "
                "the form.",
                questionnaire_id,
                len(self.choice_questions),
                MAX_CHOICE_SELECTS,
            )
        for question in rendered:
            self.add_item(_QuestionSelect(question, existing.get(question.key)))
        self.add_item(_SubmitButton())


class ResponseModal(discord.ui.Modal):
    def __init__(self, view):
        super().__init__(title="Your response")
        self.view_ref = view
        self.inputs = {}
        for question in view.text_questions[:5]:
            existing = view.existing.get(question.key, "")
            text_input = discord.ui.TextInput(
                label=content.truncate(question.display_label(), 45),
                placeholder=content.truncate(question.prompt, 100),
                style=discord.TextStyle.paragraph,
                required=question.required,
                max_length=1000,
                default=existing or None,
            )
            self.inputs[question.key] = text_input
            self.add_item(text_input)

    async def on_submit(self, interaction):
        text_answers = {key: ti.value for key, ti in self.inputs.items()}
        await self.view_ref.cog.finalize_response(
            interaction, self.view_ref, text_answers
        )


# --- The cog ----------------------------------------------------------------


class QuestionnaireCog(commands.Cog):
    questionnaire = app_commands.Group(
        name="questionnaire",
        description="Create and manage anonymous questionnaires.",
        guild_only=True,
    )

    def __init__(self, bot):
        self.bot = bot
        self.default_survey_channel_id = QUESTIONNAIRE_SURVEY_CHANNEL_ID or None
        self.default_results_channel_id = QUESTIONNAIRE_RESULTS_CHANNEL_ID or None
        self.show_live_count = QUESTIONNAIRE_SHOW_LIVE_COUNT
        self.results_as_file = QUESTIONNAIRE_RESULTS_AS_FILE
        self.purge_on_release = QUESTIONNAIRE_PURGE_ON_RELEASE
        try:
            self.default_duration = parse_duration(QUESTIONNAIRE_DEFAULT_DURATION)
        except ValueError:
            logger.warning(
                "Invalid QUESTIONNAIRE_DEFAULT_DURATION %r; defaulting to 48h.",
                QUESTIONNAIRE_DEFAULT_DURATION,
            )
            self.default_duration = timedelta(hours=48)
        self.close_due.start()

    def cog_unload(self):
        self.close_due.cancel()

    # --- Auto-close timer ---------------------------------------------------

    @tasks.loop(seconds=CLOSE_CHECK_SECONDS)
    async def close_due(self):
        """Release any questionnaire whose time is up. Restart-safe: it rescans
        the DB each tick, so nothing needs re-arming after a restart."""
        now = datetime.now(timezone.utc)
        try:
            open_questionnaires = list_open_questionnaires()
        except Exception:
            logger.exception("Failed to list open questionnaires")
            return
        for record in open_questionnaires:
            try:
                if _parse_dt(record["closes_at"]) <= now:
                    await self.close_and_release(record["id"], reason="expired")
            except Exception:
                logger.exception("Failed to auto-close questionnaire %s", record["id"])

    @close_due.before_loop
    async def _before_close(self):
        await self.bot.wait_until_ready()

    # --- Helpers ------------------------------------------------------------

    async def _deny_if_not_admin(self, interaction):
        if not admin_check(interaction):
            await interaction.response.send_message(
                "No permission — use this in the admin command channel with the "
                "admin role.",
                ephemeral=True,
            )
            return True
        return False

    async def _resolve_text_channel(self, channel_id):
        if not channel_id:
            return None
        channel = self.bot.get_channel(channel_id)
        if channel is None:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                return None
        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            return channel
        return None

    # --- /questionnaire start ----------------------------------------------

    @questionnaire.command(name="start", description="Post a new anonymous questionnaire.")
    @app_commands.describe(
        channel="Channel to post the questionnaire in (defaults to the configured survey channel).",
        results_channel="Private channel where attributed results are released (defaults to configured).",
        duration="How long it stays open, e.g. 48h, 30m, 2d (defaults to the configured duration).",
        title="Override the questionnaire title.",
    )
    async def start(self, interaction, channel: discord.TextChannel = None,
                    results_channel: discord.TextChannel = None,
                    duration: str = None, title: str = None):
        if await self._deny_if_not_admin(interaction):
            return

        survey_channel = channel or await self._resolve_text_channel(
            self.default_survey_channel_id
        )
        if survey_channel is None:
            await interaction.response.send_message(
                "No survey channel available. Pass `channel:` or set "
                "`QUESTIONNAIRE_SURVEY_CHANNEL_ID`.",
                ephemeral=True,
            )
            return

        results_ch = results_channel or await self._resolve_text_channel(
            self.default_results_channel_id
        )
        if results_ch is None:
            await interaction.response.send_message(
                "No results channel available. Pass `results_channel:` or set "
                "`QUESTIONNAIRE_RESULTS_CHANNEL_ID`.",
                ephemeral=True,
            )
            return

        if duration:
            try:
                span = parse_duration(duration)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        else:
            span = self.default_duration

        now = datetime.now(timezone.utc)
        closes_at = now + span
        final_title = (title or TITLE).strip() or TITLE
        snapshot = [question_to_dict(q) for q in QUESTIONS]

        questionnaire_id = create_questionnaire(
            title=final_title,
            channel_id=survey_channel.id,
            results_channel_id=results_ch.id,
            opened_by=interaction.user.id,
            opened_at=now,
            closes_at=closes_at,
            questions=snapshot,
        )

        embed = content.build_survey_embed(
            title=final_title,
            description=DESCRIPTION,
            closes_at=closes_at,
            questions=[question_from_dict(d) for d in snapshot],
            response_count=0,
            show_count=self.show_live_count,
        )
        try:
            message = await survey_channel.send(
                embed=embed, view=build_respond_view(questionnaire_id)
            )
        except discord.Forbidden:
            delete_questionnaire(questionnaire_id)
            await interaction.response.send_message(
                f"I couldn't post in {survey_channel.mention} — I need Send "
                "Messages and Embed Links there.",
                ephemeral=True,
            )
            return
        except discord.HTTPException:
            delete_questionnaire(questionnaire_id)
            logger.exception("Failed to post questionnaire %s", questionnaire_id)
            await interaction.response.send_message(
                "Something went wrong posting the questionnaire. Please try again.",
                ephemeral=True,
            )
            return

        set_survey_message_id(questionnaire_id, message.id)
        await interaction.response.send_message(
            f"Posted **{final_title}** (#{questionnaire_id}) in "
            f"{survey_channel.mention}. It closes {content._rel_timestamp(closes_at)} "
            f"and results will go to {results_ch.mention}.\n{message.jump_url}",
            ephemeral=True,
        )

    # --- /questionnaire close ----------------------------------------------

    @questionnaire.command(name="close", description="Close a questionnaire now and release results.")
    @app_commands.describe(id="Questionnaire id (optional if exactly one is open).")
    async def close(self, interaction, id: int = None):
        if await self._deny_if_not_admin(interaction):
            return

        if id is None:
            open_questionnaires = list_open_questionnaires()
            if not open_questionnaires:
                await interaction.response.send_message(
                    "There are no open questionnaires.", ephemeral=True
                )
                return
            if len(open_questionnaires) > 1:
                listing = ", ".join(
                    f"#{q['id']} ({q['title']})" for q in open_questionnaires
                )
                await interaction.response.send_message(
                    f"Multiple questionnaires are open — specify one with `id:`. "
                    f"Open: {listing}",
                    ephemeral=True,
                )
                return
            id = open_questionnaires[0]["id"]

        record = get_questionnaire(id)
        if record is None:
            await interaction.response.send_message(
                f"No questionnaire with id #{id}.", ephemeral=True
            )
            return
        if record["status"] != "open":
            await interaction.response.send_message(
                f"Questionnaire #{id} is already closed.", ephemeral=True
            )
            return

        await interaction.response.defer(ephemeral=True)
        released = await self.close_and_release(id, reason="manual")
        if released:
            await interaction.followup.send(
                f"Closed questionnaire #{id} and released results to the results "
                "channel.",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                f"Questionnaire #{id} was already being closed.", ephemeral=True
            )

    # --- /questionnaire status ---------------------------------------------

    @questionnaire.command(name="status", description="List currently open questionnaires.")
    async def status(self, interaction):
        if await self._deny_if_not_admin(interaction):
            return
        open_questionnaires = list_open_questionnaires()
        if not open_questionnaires:
            await interaction.response.send_message(
                "There are no open questionnaires.", ephemeral=True
            )
            return
        lines = []
        for record in open_questionnaires:
            count = count_responses(record["id"])
            closes = content._rel_timestamp(_parse_dt(record["closes_at"]))
            lines.append(
                f"**#{record['id']}** · {record['title']} — {count} "
                f"response(s), closes {closes}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    # --- /questionnaire purge ----------------------------------------------

    @questionnaire.command(
        name="purge", description="Delete the stored responses for a questionnaire."
    )
    @app_commands.describe(id="Questionnaire id whose stored responses to delete.")
    async def purge(self, interaction, id: int):
        if await self._deny_if_not_admin(interaction):
            return
        record = get_questionnaire(id)
        if record is None:
            await interaction.response.send_message(
                f"No questionnaire with id #{id}.", ephemeral=True
            )
            return
        deleted = delete_responses(id)
        await interaction.response.send_message(
            f"Deleted {deleted} stored response(s) for #{id}.", ephemeral=True
        )

    # --- Response form ------------------------------------------------------

    async def open_response_form(self, interaction, questionnaire_id):
        record = get_questionnaire(questionnaire_id)
        if record is None or record["status"] != "open":
            await interaction.response.send_message(content.FORM_CLOSED, ephemeral=True)
            return
        questions = _questions_of(record)
        existing = get_response(questionnaire_id, interaction.user.id)
        existing_answers = existing["answers"] if existing else {}
        view = ResponseView(
            cog=self,
            questionnaire_id=questionnaire_id,
            questions=questions,
            existing=existing_answers,
        )
        embed = content.build_form_intro_embed(record["title"], existing is not None)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    async def finalize_response(self, interaction, view, text_answers):
        raw = dict(view.answers)
        raw.update(text_answers)
        cleaned, errors = clean_and_validate(view.questions, raw)
        if errors:
            await interaction.response.send_message(
                content.build_validation_error(errors), ephemeral=True
            )
            return

        record = get_questionnaire(view.questionnaire_id)
        if record is None or record["status"] != "open":
            await interaction.response.send_message(
                content.CONFIRM_CLOSED_RACE, ephemeral=True
            )
            return

        member = interaction.user
        try:
            upsert_response(
                questionnaire_id=view.questionnaire_id,
                user_id=member.id,
                username=str(member),
                display_name=getattr(member, "display_name", None) or member.name,
                answers=cleaned,
                now=datetime.now(timezone.utc),
            )
        except Exception:
            logger.exception("Failed to save response for %s", member.id)
            await interaction.response.send_message(
                "A database error stopped your response from saving. Please try "
                "again.",
                ephemeral=True,
            )
            return

        await interaction.response.send_message(content.CONFIRM_RECORDED, ephemeral=True)
        if self.show_live_count:
            await self._update_live_count(record)

    # --- Close + release pipeline ------------------------------------------

    async def close_and_release(self, questionnaire_id, *, reason):
        now = datetime.now(timezone.utc)
        if not close_questionnaire(questionnaire_id, now):
            return False
        logger.info("Closing questionnaire %s (%s)", questionnaire_id, reason)

        record = get_questionnaire(questionnaire_id)
        if record is None:
            return True
        questions = _questions_of(record)
        responses = list_responses(questionnaire_id)

        try:
            await self._release_results(record, questions, responses, now)
        except Exception:
            logger.exception("Failed to release results for %s", questionnaire_id)
        try:
            await self._mark_survey_closed(record, questions)
        except Exception:
            logger.exception("Failed to mark survey %s closed", questionnaire_id)

        if self.purge_on_release:
            try:
                delete_responses(questionnaire_id)
            except Exception:
                logger.exception("Failed to purge responses for %s", questionnaire_id)
        return True

    async def _release_results(self, record, questions, responses, closed_at):
        channel = await self._resolve_text_channel(int(record["results_channel_id"]))
        if channel is None:
            logger.warning(
                "Results channel %s for questionnaire %s is unavailable.",
                record["results_channel_id"],
                record["id"],
            )
            return

        no_ping = discord.AllowedMentions.none()
        total = len(responses)

        header = content.build_results_header_embed(
            title=record["title"], total=total, closed_at=closed_at
        )
        await channel.send(embed=header, allowed_mentions=no_ping)

        if total == 0:
            await channel.send(
                "*No responses were submitted before this questionnaire closed.*",
                allowed_mentions=no_ping,
            )
            return

        digest_embeds = content.build_digest_embeds(
            record["title"], aggregate(questions, [r["answers"] for r in responses])
        )
        for embed in digest_embeds:
            await channel.send(embed=embed, allowed_mentions=no_ping)

        respondent_embeds = [
            content.build_respondent_embed(
                questions=questions, response=response, index=i, total=total
            )
            for i, response in enumerate(responses, start=1)
        ]
        for start in range(0, len(respondent_embeds), 10):
            await channel.send(
                embeds=respondent_embeds[start : start + 10],
                allowed_mentions=no_ping,
            )

        if self.results_as_file:
            csv_text = content.build_results_csv(questions, responses)
            file = discord.File(
                io.BytesIO(csv_text.encode("utf-8")),
                filename=f"results_{record['id']}.csv",
            )
            await channel.send(file=file, allowed_mentions=no_ping)

    async def _mark_survey_closed(self, record, questions):
        message_id = record.get("message_id")
        if not message_id:
            return
        channel = await self._resolve_text_channel(int(record["channel_id"]))
        if channel is None:
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            return
        embed = content.build_survey_embed(
            title=record["title"],
            description=DESCRIPTION,
            closes_at=_parse_dt(record["closes_at"]),
            questions=questions,
            response_count=count_responses(record["id"]),
            show_count=self.show_live_count,
            closed=True,
        )
        try:
            await message.edit(embed=embed, view=None)
        except discord.HTTPException:
            logger.exception("Failed to edit closed survey message %s", message_id)

    async def _update_live_count(self, record):
        message_id = record.get("message_id")
        if not message_id:
            return
        try:
            channel = await self._resolve_text_channel(int(record["channel_id"]))
            if channel is None:
                return
            message = await channel.fetch_message(int(message_id))
            count = count_responses(record["id"])
            embed = content.build_survey_embed(
                title=record["title"],
                description=DESCRIPTION,
                closes_at=_parse_dt(record["closes_at"]),
                questions=_questions_of(record),
                response_count=count,
                show_count=True,
            )
            await message.edit(embed=embed)
        except (discord.HTTPException, ValueError):
            logger.debug("Could not update live count for %s", record["id"], exc_info=True)


async def setup(bot):
    # Register the Respond button as a dynamic item so buttons on already posted
    # questionnaires keep working across restarts.
    bot.add_dynamic_items(RespondButton)
    await bot.add_cog(QuestionnaireCog(bot))
