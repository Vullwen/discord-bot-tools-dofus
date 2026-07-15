from __future__ import annotations

from io import BytesIO
import re

import discord
from discord.ext import commands

from utils.stuff_capture import capture_dofusbook_page
from utils.stuff_card import build_stuff_fallback_card, parse_dofusbook_url


DOFUSBOOK_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:dofusbook\.net|d-bk\.net)/\S+",
    re.IGNORECASE,
)
TRAILING_URL_PUNCTUATION = ".,;:!?)>]}"


class StuffCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.app_commands.command(
        name="stuff",
        description="Genere une image a partir d'un lien Dofusbook",
    )
    @discord.app_commands.describe(lien="Lien dofusbook.net ou d-bk.net du stuff")
    async def stuff(self, interaction: discord.Interaction, lien: str):
        try:
            stuff_link = parse_dofusbook_url(lien)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        await interaction.response.defer(thinking=True)

        content, file = await _build_stuff_response(stuff_link)
        await interaction.followup.send(content=content, file=file)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return

        match = DOFUSBOOK_LINK_RE.search(message.content)
        if match is None:
            return

        try:
            stuff_link = parse_dofusbook_url(_clean_detected_url(match.group(0)))
        except ValueError:
            return

        async with message.channel.typing():
            content, file = await _build_stuff_response(stuff_link)
            await message.reply(content=content, file=file, mention_author=False)


async def _build_stuff_response(stuff_link):
    screenshot, reason = await capture_dofusbook_page(stuff_link.url)
    if screenshot is not None:
        return None, discord.File(BytesIO(screenshot), filename="stuff-dofusbook.png")

    card = build_stuff_fallback_card(stuff_link, reason)
    return (
        "Je n'ai pas pu lire Dofusbook directement, "
        "mais j'ai genere une carte depuis le lien.",
        discord.File(card, filename="stuff-dofusbook.png"),
    )


def _clean_detected_url(url: str) -> str:
    return url.rstrip(TRAILING_URL_PUNCTUATION)


async def setup(bot: commands.Bot):
    await bot.add_cog(StuffCog(bot))
