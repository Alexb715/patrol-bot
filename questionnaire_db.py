"""SQLite persistence for the questionnaire feature.

Reuses patrol-bot's single shared connection (see database.py) so everything
lives in the same patrol_stats.db file. Tables are created on import. Rows are
mapped to explicit dicts here so we never change the shared connection's
row_factory (the rest of the bot relies on tuple rows).

User IDs are stored only to enforce one response per person and allow edits;
they are surfaced only in the private results release, never in the public
survey channel.
"""

import json

from database import conn, cursor

cursor.execute("""
CREATE TABLE IF NOT EXISTS questionnaires(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    message_id TEXT,
    results_channel_id TEXT NOT NULL,
    opened_by TEXT NOT NULL,
    opened_at TEXT NOT NULL,
    closes_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    closed_at TEXT,
    questions_json TEXT NOT NULL
)
""")

cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_questionnaires_status ON questionnaires(status)"
)

cursor.execute("""
CREATE TABLE IF NOT EXISTS questionnaire_responses(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    questionnaire_id INTEGER NOT NULL,
    user_id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL,
    answers_json TEXT NOT NULL,
    submitted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(questionnaire_id, user_id)
)
""")

cursor.execute(
    "CREATE INDEX IF NOT EXISTS idx_qresponses_questionnaire "
    "ON questionnaire_responses(questionnaire_id)"
)

conn.commit()


_Q_COLS = (
    "id", "title", "channel_id", "message_id", "results_channel_id",
    "opened_by", "opened_at", "closes_at", "status", "closed_at", "questions_json",
)
_Q_SELECT = ", ".join(_Q_COLS)

_R_COLS = (
    "id", "questionnaire_id", "user_id", "username", "display_name",
    "answers_json", "submitted_at", "updated_at",
)
_R_SELECT = ", ".join(_R_COLS)


def _to_questionnaire(row):
    record = dict(zip(_Q_COLS, row))
    record["questions"] = json.loads(record.pop("questions_json"))
    return record


def _to_response(row):
    record = dict(zip(_R_COLS, row))
    record["answers"] = json.loads(record.pop("answers_json"))
    return record


# --- Questionnaires ---------------------------------------------------------


def create_questionnaire(*, title, channel_id, results_channel_id, opened_by,
                         opened_at, closes_at, questions):
    cursor.execute(
        "INSERT INTO questionnaires"
        "(title, channel_id, results_channel_id, opened_by, opened_at, "
        " closes_at, status, questions_json) "
        "VALUES(?, ?, ?, ?, ?, ?, 'open', ?)",
        (
            title,
            str(channel_id),
            str(results_channel_id),
            str(opened_by),
            opened_at.isoformat(),
            closes_at.isoformat(),
            json.dumps(questions, ensure_ascii=False),
        ),
    )
    conn.commit()
    return cursor.lastrowid


def set_survey_message_id(questionnaire_id, message_id):
    cursor.execute(
        "UPDATE questionnaires SET message_id = ? WHERE id = ?",
        (str(message_id), questionnaire_id),
    )
    conn.commit()


def get_questionnaire(questionnaire_id):
    cursor.execute(
        f"SELECT {_Q_SELECT} FROM questionnaires WHERE id = ?", (questionnaire_id,)
    )
    row = cursor.fetchone()
    return _to_questionnaire(row) if row else None


def list_open_questionnaires():
    cursor.execute(
        f"SELECT {_Q_SELECT} FROM questionnaires WHERE status = 'open' ORDER BY id"
    )
    return [_to_questionnaire(r) for r in cursor.fetchall()]


def close_questionnaire(questionnaire_id, closed_at):
    """Atomically flip an open questionnaire to closed. Returns True only for the
    call that actually closed it, so the manual /close command and the auto-close
    timer can't both release results."""
    cursor.execute(
        "UPDATE questionnaires SET status = 'closed', closed_at = ? "
        "WHERE id = ? AND status = 'open'",
        (closed_at.isoformat(), questionnaire_id),
    )
    conn.commit()
    return cursor.rowcount > 0


def delete_questionnaire(questionnaire_id):
    cursor.execute(
        "DELETE FROM questionnaire_responses WHERE questionnaire_id = ?",
        (questionnaire_id,),
    )
    cursor.execute("DELETE FROM questionnaires WHERE id = ?", (questionnaire_id,))
    conn.commit()


# --- Responses --------------------------------------------------------------


def upsert_response(*, questionnaire_id, user_id, username, display_name, answers, now):
    cursor.execute(
        "INSERT INTO questionnaire_responses"
        "(questionnaire_id, user_id, username, display_name, answers_json, "
        " submitted_at, updated_at) "
        "VALUES(?, ?, ?, ?, ?, ?, ?) "
        "ON CONFLICT(questionnaire_id, user_id) DO UPDATE SET "
        "  username = excluded.username, "
        "  display_name = excluded.display_name, "
        "  answers_json = excluded.answers_json, "
        "  updated_at = excluded.updated_at",
        (
            questionnaire_id,
            str(user_id),
            username,
            display_name,
            json.dumps(answers, ensure_ascii=False),
            now.isoformat(),
            now.isoformat(),
        ),
    )
    conn.commit()


def get_response(questionnaire_id, user_id):
    cursor.execute(
        f"SELECT {_R_SELECT} FROM questionnaire_responses "
        "WHERE questionnaire_id = ? AND user_id = ?",
        (questionnaire_id, str(user_id)),
    )
    row = cursor.fetchone()
    return _to_response(row) if row else None


def list_responses(questionnaire_id):
    cursor.execute(
        f"SELECT {_R_SELECT} FROM questionnaire_responses "
        "WHERE questionnaire_id = ? ORDER BY submitted_at",
        (questionnaire_id,),
    )
    return [_to_response(r) for r in cursor.fetchall()]


def count_responses(questionnaire_id):
    cursor.execute(
        "SELECT COUNT(*) FROM questionnaire_responses WHERE questionnaire_id = ?",
        (questionnaire_id,),
    )
    return int(cursor.fetchone()[0])


def delete_responses(questionnaire_id):
    cursor.execute(
        "DELETE FROM questionnaire_responses WHERE questionnaire_id = ?",
        (questionnaire_id,),
    )
    conn.commit()
    return cursor.rowcount
