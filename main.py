import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

import discord
from discord.ext import commands

from config import BOT_COGS, BOT_NAME, DISCORD_GUILD_ID, DISCORD_TOKEN, LOG_LEVEL

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
logger = logging.getLogger("dofus-raid-bot")

intents = discord.Intents.default()
# Requis pour détecter automatiquement les screenshots postés dans les salons
# privés de vérification Dofus.
intents.message_content = True
# Requis pour ouvrir le ticket d'accueil quand un membre accepte le screening
# Discord (Member.pending passe de True à False).
intents.members = True
# Les autres actions gardent interaction.user et fetch_member/fetch_user en fallback.


def _no_prefix(_bot, _message):
    return []

bot = commands.Bot(
    command_prefix=_no_prefix,
    intents=intents,
    description=BOT_NAME,
)

COGS = BOT_COGS


def _presence_name() -> str:
    if COGS == ["cogs.absence"]:
        return "les absences"
    return "les raids"


async def sync_commands() -> None:
    """Publie les slash commands sans garder de doublons guild/global.

    En mode global (DISCORD_GUILD_ID vide), on supprime les anciennes copies de
    guilde qui peuvent rester d'une sync instantanée précédente.
    """
    if DISCORD_GUILD_ID:
        guild = discord.Object(id=DISCORD_GUILD_ID)
        bot.tree.copy_global_to(guild=guild)
        synced = await bot.tree.sync(guild=guild)
        logger.info(f"Synced {len(synced)} slash command(s) to guild {DISCORD_GUILD_ID}")
        return

    synced = await bot.tree.sync()
    logger.info(f"Synced {len(synced)} global slash command(s)")
    for current_guild in bot.guilds:
        guild = discord.Object(id=current_guild.id)
        bot.tree.clear_commands(guild=guild)
        await bot.tree.sync(guild=guild)
    if bot.guilds:
        logger.info(f"Cleared guild slash command copies across {len(bot.guilds)} guild(s)")


@bot.event
async def on_ready():
    logger.info(f"Logged in as {bot.user} (ID: {bot.user.id})")
    logger.info(f"Connected to {len(bot.guilds)} guild(s)")

    await sync_commands()

    await bot.change_presence(
        activity=discord.Activity(
            type=discord.ActivityType.watching,
            name=_presence_name(),
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
        logger.info("Cog set: %s", ", ".join(COGS))

        await bot.start(DISCORD_TOKEN)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
