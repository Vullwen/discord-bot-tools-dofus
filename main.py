import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from config import BOT_NAME, DISCORD_GUILD_ID, DISCORD_TOKEN, LOG_LEVEL

_handler = logging.StreamHandler()
_handler.setFormatter(
    logging.Formatter(
        fmt="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
)
_handler.formatter.converter = lambda ts: datetime.fromtimestamp(
    ts, tz=ZoneInfo("Europe/Paris")
).timetuple()

logging.basicConfig(level=getattr(logging, LOG_LEVEL, logging.INFO), handlers=[_handler])
logger = logging.getLogger("beb-raid")

intents = discord.Intents.default()
# Pas d'intent privilégié requis : on utilise interaction.user et fetch_member/fetch_user
# en fallback, le bot démarre même si SERVER MEMBERS INTENT n'est pas activé.


def _no_prefix(_bot, _message):
    return []

bot = commands.Bot(
    command_prefix=_no_prefix,
    intents=intents,
    description=BOT_NAME,
)

COGS = [
    "cogs.core",
    "cogs.admin",
    "cogs.raid",
    "cogs.ticket",
]


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    if DISCORD_GUILD_ID:
        guild = discord.Object(id=DISCORD_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
    else:
        synced = await bot.tree.sync()

    logger.info(f"Synced {len(synced)} slash command(s)")

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name="les raids",
        )
    )


@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error):
    if isinstance(error, discord.app_commands.errors.CommandInvokeError):
        original = error.original
        logger.error(f"/{interaction.command.name}: {original}", exc_info=original)
        msg = f"Erreur: `{type(original).__name__}: {original}`"
    else:
        logger.error(f"Command error: {error}")
        msg = f"Erreur: `{error}`"

    try:
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)
    except Exception:
        pass


async def main():
    if not DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN not set")
        return

    async with bot:
        for cog in COGS:
            try:
                await bot.load_extension(cog)
                logger.info(f"Loaded cog: {cog}")
            except Exception as exc:
                logger.error(f"Failed to load cog {cog}: {exc}", exc_info=True)

        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
