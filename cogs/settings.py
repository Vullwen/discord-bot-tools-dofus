"""Configuration en Discord du salon des raids et de la catégorie des tickets.

- /setchannel : définit le salon où arrivent les sondages/embeds des raids
                (ou la catégorie des tickets). Admin uniquement.
- /showconfig : affiche la configuration courante de la guilde.
"""
from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import ADMIN_IDS

_CHANNEL_LABEL = {
    db.SETTING_RAIDS_CHANNEL: "Salon des raids",
    db.SETTING_TICKET_CATEGORY: "Catégorie des tickets",
}


class SettingsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="setchannel", description="Définit le salon des raids ou la catégorie des tickets (admin)")
    @app_commands.describe(
        setting="Ce que tu veux configurer",
        channel="Le salon (raid) ou la catégorie (tickets)",
    )
    @app_commands.choices(
        setting=[
            app_commands.Choice(name="Salon des raids", value=db.SETTING_RAIDS_CHANNEL),
            app_commands.Choice(name="Catégorie des tickets", value=db.SETTING_TICKET_CATEGORY),
        ]
    )
    async def setchannel(
        self,
        interaction: discord.Interaction,
        setting: app_commands.Choice[str],
        channel: discord.abc.GuildChannel,
    ) -> None:
        if interaction.user.id not in ADMIN_IDS:
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        if setting.value == db.SETTING_TICKET_CATEGORY and not isinstance(channel, discord.CategoryChannel):
            await interaction.response.send_message(
                "La catégorie des tickets doit être une **catégorie** (➕ Créer une catégorie), pas un salon texte.",
                ephemeral=True,
            )
            return

        db.set_guild_setting(interaction.guild.id, setting.value, str(channel.id))
        label = _CHANNEL_LABEL.get(setting.value, setting.value)
        await interaction.response.send_message(
            f"✅ {label} défini sur {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="showconfig", description="Affiche la configuration des raids/tickets de ce serveur")
    async def showconfig(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        guild = interaction.guild

        def _mention(key):
            cid = db.get_guild_setting_int(guild.id, key)
            if not cid:
                return "*(non défini)*"
            ch = guild.get_channel(cid)
            return ch.mention if ch else f"*(salon {cid} introuvable)*"

        embed = discord.Embed(title="⚙️ Configuration", color=0x2ECC71)
        embed.add_field(name="Salon des raids", value=_mention(db.SETTING_RAIDS_CHANNEL), inline=False)
        embed.add_field(name="Catégorie des tickets", value=_mention(db.SETTING_TICKET_CATEGORY), inline=False)
        embed.set_footer(text="Configure avec /setchannel")
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
