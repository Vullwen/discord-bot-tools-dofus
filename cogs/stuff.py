from __future__ import annotations

from io import BytesIO

import discord
from discord.ext import commands

from utils.stuff_capture import capture_dofusbook_page
from utils.stuff_card import build_stuff_fallback_card, parse_dofusbook_url


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

        screenshot, reason = await capture_dofusbook_page(stuff_link.url)
        if screenshot is not None:
            file = discord.File(BytesIO(screenshot), filename="stuff-dofusbook.png")
            await interaction.followup.send(file=file)
            return

        card = build_stuff_fallback_card(stuff_link, reason)
        file = discord.File(card, filename="stuff-dofusbook.png")
        await interaction.followup.send(
            content=(
                "Je n'ai pas pu lire Dofusbook directement, "
                "mais j'ai genere une carte depuis le lien."
            ),
            file=file,
        )


async def setup(bot: commands.Bot):
    await bot.add_cog(StuffCog(bot))
