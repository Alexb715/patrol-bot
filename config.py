import os
import enum

import pytz


TOKEN = os.getenv("TOKEN")

GUILD_ID = int(os.getenv("GUILD_ID", 0))
PATROL_CHANNEL_ID = int(os.getenv("PATROL_CHANNEL_ID", 0))
AOP_CHANNEL_ID = int(os.getenv("AOP_CHANNEL_ID", 0))
BRIEFING_CHANNEL_ID = int(os.getenv("BRIEFING_CHANNEL_ID", 0))
BRIEFING_VOICE_CHANNEL_ID = int(os.getenv("BRIEFING_VOICE_CHANNEL_ID", 0))
STATS_CHANNEL_ID = int(os.getenv("STATS_CHANNEL_ID", 0))
ANNOUNCEMENT_CHANNEL_ID = int(os.getenv("ANNOUNCEMENT_CHANNEL_ID", 0))
ADMIN_COMMAND_CHANNEL = int(os.getenv("ADMIN_COMMAND_CHANNEL", 0))
WELCOME_CHANNEL_ID = int(os.getenv("WELCOME_CHANNEL_ID", 0))
GOODBYE_CHANNEL_ID = int(os.getenv("GOODBYE_CHANNEL_ID", 0))
RULES_CHANNEL_ID = int(os.getenv("RULES_CHANNEL_ID", 0))
SERVER_LINKS_CHANNEL_ID = int(os.getenv("SERVER_LINKS_CHANNEL_ID", 0))
RESOURCES_CHANNEL_ID = int(os.getenv("RESOURCES_CHANNEL_ID", 0))
GENERAL_CHANNEL_ID = int(os.getenv("GENERAL_CHANNEL_ID", 0))
SUPPORT_CHANNEL_ID = int(os.getenv("SUPPORT_CHANNEL_ID", 0))

PING_ROLE_ID = int(os.getenv("PING_ROLE_ID", 0))
ADMIN_ROLE_ID = int(os.getenv("ADMIN_ROLE_ID", 0))

MINIMUM_PATROL = 4

TIMEZONE = pytz.timezone("US/Eastern")

DATABASE_PATH = os.getenv("DATABASE_PATH", "patrol_stats.db")


class Period(enum.Enum):
    all_time = "All Time"
    last_2_weeks = "Last 2 Weeks"


time_slots = [
    "7:00 PM EST",
    "7:30 PM EST",
    "8:00 PM EST",
    "8:30 PM EST",
    "9:00 PM EST",
]

mapLS = [
    "Region Of Waterloo",
    "City Of Guelph",
    "Wellington County",
    "Brant County",
    "Oxford County",
    "Middlesex County",
    "City Of London",
]

mapLC = [
    "City of Toronto",
    "Peel Region",
    "York Region",
    "Durham Region",
    "Halton Region",
    "City of Hamilton",
]
