# Patrol Bot

A Discord bot for managing daily patrol scheduling, AOP (Area of Patrol) voting, attendance tracking, and statistics for roleplay communities.

## Features

- **Daily Patrol Voting** — Members vote for a patrol start time each morning. Votes close at 6:30 PM EST with a minimum attendance threshold.
- **AOP Voting** — Members vote on the patrol area. Supports Liberty City (LC) and Los Santos (LS) map sets, switchable by admins.
- **Persistent Session State** — Votes, messages, and voting status survive bot restarts via SQLite persistence. Buttons remain functional after a restart.
- **Briefing Reminder** — Automatically pings 10 minutes before the confirmed patrol start time to join the briefing voice chat.
- **Cancel Announcements** — Cancelling a patrol notifies the announcement channel and edits any existing announcement.
- **Smart Map Switching** — Changing the map while AOP voting is open resets votes and refreshes buttons automatically.
- **Duplicate Vote Protection** — Changing your vote doesn't inflate stat counters; only the first vote is tracked.
- **Command Autocomplete** — Time slots and area names are suggested as you type in slash commands.
- **Biweekly Stats Leaderboard** — Posts a ranked leaderboard to the stats channel every 14 days.
- **Inactivity Tracking** — Automatically detects members who haven't responded in 2 weeks and posts reports.
- **Welcome & Goodbye Messages** — Automatically sends styled welcome messages (with rules and resources links) to new members, and goodbye messages when members leave.
- **Admin Commands** — Cancel patrols, override start times/AOP, view per-user and server-wide statistics.

## Commands

### Voting

| Command | Description |
|---|---|
| `/open_votes` | Open both patrol and AOP voting |
| `/open_patrol_vote` | Open patrol voting only |
| `/open_aop_vote` | Open AOP voting only |
| `/close_patrol_votes` | Close patrol votes and determine start time |
| `/close_aop_votes` | Close AOP votes, announce the winner, and update the announcement |

### Patrol Management

| Command | Description |
|---|---|
| `/start_patrol <time> <area>` | Force start a patrol with a specific time and area |
| `/cancel_patrol` | Cancel tonight's patrol and notify the announcement channel |
| `/override_patrol_time <time>` | Override the patrol start time |
| `/override_aop <area>` | Override the AOP |
| `/maplc` | Switch AOP options to Liberty City (resets AOP votes if open) |
| `/mapls` | Switch AOP options to Los Santos (resets AOP votes if open) |

### Statistics

| Command | Description |
|---|---|
| `/user_stats <member> [period]` | View a member's vote counts, attendance rate, and last activity |
| `/server_stats [period]` | View total patrols, average attendance, and breakdown by day of week |
| `/activity_stats [period]` | View cancellation rate, no-show rate, and per-day breakdown |
| `/aop_breakdown [period]` | View AOP popularity split by map (LC and LS), with per-day favorites and unused areas |
| `/check_inactive` | List members with the ping role who haven't responded in the last 2 weeks |
| `/force_stats` | Manually post the biweekly stats leaderboard |

### Other

| Command | Description |
|---|---|
| `/help` | Show all admin commands and bot features |
| `/clear_stats` | Clear all statistics data (**destructive**) |

All stats commands support an optional `period` parameter: **All Time** (default) or **Last 2 Weeks**.

### Questionnaires

Post an **anonymous** questionnaire into a public channel, collect answers for a set window, then release the results — an aggregated digest plus each person's answers, attributed — into a separate **private** channel for leadership. Nothing about who answered is ever shown publicly. Members answer through an ephemeral form (dropdowns + a text box); one response each, editable until close. Edit the questions in `questions.py`.

| Command | Description |
|---|---|
| `/questionnaire start [channel] [results_channel] [duration] [title]` | Post a questionnaire. Unset options fall back to the configured defaults. `duration` accepts `48h`, `30m`, `2d`, `1w`, `1d12h`, … |
| `/questionnaire close [id]` | Close now and release results (`id` optional when exactly one is open). |
| `/questionnaire status` | List open questionnaires with response counts. |
| `/questionnaire purge <id>` | Delete a questionnaire's stored responses. |

A questionnaire also auto-closes when its duration elapses (a restart-safe background check). Responses live in the same SQLite database as the patrol stats.

All commands require the admin role and must be used in the admin command channel.

## How It Works

1. **8:00 AM EST** — The bot automatically posts patrol and AOP votes with interactive buttons.
2. Members click buttons to vote for a start time or mark "Can't Make It", and vote for an AOP area.
3. **6:30 PM EST** — Voting closes automatically. If minimum attendance is met, the patrol is confirmed and an announcement is posted. Otherwise, it's cancelled.
4. **10 minutes before patrol** — A briefing reminder is sent to the briefing channel.
5. Admins can override times/AOP, cancel, or force-start patrols at any time.

## Maps

### Liberty City (LC)
City of Toronto, Peel Region, York Region, Durham Region, Halton Region, City of Hamilton

### Los Santos (LS)
City of Orillia, City Of Barrie, Simcoe County Central, Kawartha Lakes, Peterborough, Northumberland, Prince Edward County

## Environment Variables

| Variable | Description |
|---|---|
| `TOKEN` | Discord bot token |
| `GUILD_ID` | Discord server ID |
| `PATROL_CHANNEL_ID` | Channel for patrol voting |
| `AOP_CHANNEL_ID` | Channel for AOP voting |
| `BRIEFING_CHANNEL_ID` | Text channel for briefing reminders |
| `BRIEFING_VOICE_CHANNEL_ID` | Voice channel linked in briefing reminders |
| `STATS_CHANNEL_ID` | Channel for biweekly stats leaderboard and inactivity reports |
| `ANNOUNCEMENT_CHANNEL_ID` | Channel for patrol confirmed/cancelled announcements |
| `ADMIN_COMMAND_CHANNEL` | Channel where admin commands are allowed |
| `WELCOME_CHANNEL_ID` | Channel for welcome messages when members join |
| `GOODBYE_CHANNEL_ID` | Channel for goodbye messages when members leave |
| `RULES_CHANNEL_ID` | Rules channel linked in welcome message |
| `SERVER_LINKS_CHANNEL_ID` | Server links channel linked in welcome message |
| `RESOURCES_CHANNEL_ID` | Resources channel linked in welcome message |
| `GENERAL_CHANNEL_ID` | General channel linked in welcome message |
| `SUPPORT_CHANNEL_ID` | Support ticket channel linked in welcome message |
| `PING_ROLE_ID` | Role to ping for voting and briefing reminders |
| `ADMIN_ROLE_ID` | Role required to use admin commands |
| `DATABASE_PATH` | Path to SQLite database (default: `patrol_stats.db`) |
| `QUESTIONNAIRE_SURVEY_CHANNEL_ID` | Default public channel for `/questionnaire start` (optional) |
| `QUESTIONNAIRE_RESULTS_CHANNEL_ID` | Default **private** channel where attributed results are released (optional) |
| `QUESTIONNAIRE_DEFAULT_DURATION` | Default open duration, e.g. `48h` (optional) |
| `QUESTIONNAIRE_SHOW_LIVE_COUNT` | Show a live "Responses: N" count (people who fully answered) on the public embed — `true`/`false` (default `true`) |
| `QUESTIONNAIRE_RESULTS_AS_FILE` | Also attach a CSV of attributed answers on release — `true`/`false` (default `false`) |
| `QUESTIONNAIRE_PURGE_ON_RELEASE` | Delete stored responses right after releasing — `true`/`false` (default `false`) |

## Docker

### Run with Docker

```bash
docker run -d \
  -e TOKEN=your-bot-token \
  -e GUILD_ID=123456789 \
  -e PATROL_CHANNEL_ID=123456789 \
  -e AOP_CHANNEL_ID=123456789 \
  -e BRIEFING_CHANNEL_ID=123456789 \
  -e BRIEFING_VOICE_CHANNEL_ID=123456789 \
  -e STATS_CHANNEL_ID=123456789 \
  -e ANNOUNCEMENT_CHANNEL_ID=123456789 \
  -e ADMIN_COMMAND_CHANNEL=123456789 \
  -e WELCOME_CHANNEL_ID=123456789 \
  -e GOODBYE_CHANNEL_ID=123456789 \
  -e RULES_CHANNEL_ID=123456789 \
  -e SERVER_LINKS_CHANNEL_ID=123456789 \
  -e RESOURCES_CHANNEL_ID=123456789 \
  -e GENERAL_CHANNEL_ID=123456789 \
  -e SUPPORT_CHANNEL_ID=123456789 \
  -e PING_ROLE_ID=123456789 \
  -e ADMIN_ROLE_ID=123456789 \
  -v patrol-data:/app/data \
  ghcr.io/alexb715/patrol-bot:latest
```

### Build locally

```bash
docker build -t patrol-bot .
```

## Running without Docker

```bash
pip install -r requirements.txt
python bot.py
```
