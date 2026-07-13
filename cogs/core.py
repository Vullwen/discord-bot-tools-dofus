import discord
from discord.ext import commands


def _help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Aide Beb Raid",
        description="Commandes disponibles sur ce serveur.",
        color=0x2ECC71,
    )
    embed.add_field(
        name="Général",
        value="`/help` : affiche cette aide\n`/ping` : vérifie que le bot répond",
        inline=False,
    )
    embed.add_field(
        name="Raids",
        value=(
            "`/raid` : crée un raid\n"
            "`/list_raids` : liste les raids actifs\n"
            "`/cancel_raid` : annule un raid\n"
            "`/force_close` : clôture un sondage"
        ),
        inline=False,
    )
    embed.add_field(
        name="Absences",
        value=(
            "`/absence_panel` : poste le bouton d'absence\n"
            "`/search_abs` : recherche les absences\n"
            "`/kick_abs` : prévient un membre AFK dans le salon absence et en MP"
        ),
        inline=False,
    )
    embed.add_field(
        name="Configuration",
        value=(
            "`/setchannel` : configure les salons\n"
            "`/setraidrole` : configure le rôle organisateur\n"
            "`/setraidnotifyrole` : configure le rôle de notification\n"
            "`/showconfig` : affiche la configuration"
        ),
        inline=False,
    )
    embed.add_field(
        name="Admin",
        value="`/sync` : resync les commandes\n`/reload` : recharge un cog",
        inline=False,
    )
    return embed


class CoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.app_commands.command(name="help", description="Affiche l'aide du bot")
    async def help(self, interaction: discord.Interaction):
        await interaction.response.send_message(embed=_help_embed(), ephemeral=True)

    @discord.app_commands.command(name="ping", description="Check si le bot est vivant")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! **{latency}ms**", ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CoreCog(bot))
