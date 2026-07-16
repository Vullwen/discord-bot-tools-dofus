from __future__ import annotations

from io import BytesIO
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils.stuff_capture import capture_dofusbook_page
from utils.stuff_card import StuffLink, build_stuff_fallback_card, parse_dofusbook_url


DOFUSBOOK_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:dofusbook\.net|d-bk\.net)/\S+",
    re.IGNORECASE,
)
TRAILING_URL_PUNCTUATION = ".,;:!?)>]}"
RECENT_HISTORY_LIMIT = 80
STUFF_IMAGE_FILENAME = "stuff-dofusbook.png"


class StuffCog(commands.Cog):
    stuff = app_commands.Group(
        name="stuff",
        description="Outils Dofusbook",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @stuff.command(
        name="refresh",
        description="Regénere le dernier stuff Dofusbook récent du salon",
    )
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        channel = interaction.channel
        if channel is None or not hasattr(channel, "history"):
            await interaction.followup.send(
                "Je ne peux pas lire l'historique de ce salon.",
            )
            return

        try:
            source_message, stuff_link = await _find_recent_stuff_message(channel)
        except discord.Forbidden:
            await interaction.followup.send(
                "Il me manque l'accès à l'historique de ce salon.",
            )
            return

        if source_message is None or stuff_link is None:
            await interaction.followup.send(
                "Aucun lien Dofusbook récent trouvé dans ce salon.",
            )
            return

        await _delete_previous_stuff_images(
            channel,
            source_message.id,
            getattr(self.bot.user, "id", None),
        )

        async with channel.typing():
            content, file = await _build_stuff_response(stuff_link)
            await interaction.followup.send(content=content, file=file)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return

        stuff_link = _extract_stuff_link(message.content)
        if stuff_link is None:
            return

        async with message.channel.typing():
            content, file = await _build_stuff_response(stuff_link)
            await message.reply(content=content, file=file, mention_author=False)


async def _build_stuff_response(stuff_link):
    screenshot, reason = await capture_dofusbook_page(stuff_link.url)
    if screenshot is not None:
        return None, discord.File(BytesIO(screenshot), filename=STUFF_IMAGE_FILENAME)

    card = build_stuff_fallback_card(stuff_link, reason)
    return (
        "Je n'ai pas pu lire Dofusbook directement, "
        "mais j'ai genere une carte depuis le lien.",
        discord.File(card, filename=STUFF_IMAGE_FILENAME),
    )


async def _find_recent_stuff_message(channel) -> tuple[discord.Message | None, StuffLink | None]:
    async for message in channel.history(limit=RECENT_HISTORY_LIMIT):
        if message.author.bot or not message.content:
            continue

        stuff_link = _extract_stuff_link(message.content)
        if stuff_link is not None:
            return message, stuff_link

    return None, None


async def _delete_previous_stuff_images(
    channel,
    source_message_id: int,
    bot_user_id: int | None,
) -> int:
    if bot_user_id is None:
        return 0

    deleted = 0
    async for message in channel.history(limit=RECENT_HISTORY_LIMIT):
        if message.id == source_message_id:
            break

        if message.author.id != bot_user_id:
            continue

        if not _looks_like_stuff_response(message):
            continue

        try:
            await message.delete()
            deleted += 1
        except discord.HTTPException:
            continue

    return deleted


def _extract_stuff_link(content: str) -> StuffLink | None:
    match = DOFUSBOOK_LINK_RE.search(content)
    if match is None:
        return None

    try:
        return parse_dofusbook_url(_clean_detected_url(match.group(0)))
    except ValueError:
        return None


def _looks_like_stuff_response(message: discord.Message) -> bool:
    return any(
        attachment.filename == STUFF_IMAGE_FILENAME
        for attachment in message.attachments
    )


def _clean_detected_url(url: str) -> str:
    return url.rstrip(TRAILING_URL_PUNCTUATION)


async def setup(bot: commands.Bot):
    await bot.add_cog(StuffCog(bot))
