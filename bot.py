import discord
from discord.ext import commands

from config import TOKEN, GUILD_ID
from state import load_session


bot = commands.Bot(command_prefix="!", intents=discord.Intents.all())

COGS = [
    "cogs.tasks",
    "cogs.admin",
    "cogs.stats",
    "cogs.testing",
    "cogs.welcome",
    "cogs.questionnaire",
]


@bot.event
async def on_ready():
    print("Bot Online")

    await load_session(bot)
    import state
    print(f"Session restored: voting_open={state.voting_open}, patrol_votes={len(state.patrol_votes)}, aop_votes={len(state.aop_votes)}")

    for cog in COGS:
        await bot.load_extension(cog)

    bot.tree.copy_global_to(guild=discord.Object(id=GUILD_ID))
    await bot.tree.sync(guild=discord.Object(id=GUILD_ID))


bot.run(TOKEN)
