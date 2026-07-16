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
            "`/ban_raid` : interdit temporairement les votes et inscriptions\n"
            "`/unban_raid` : retire un ban raid\n"
            "`/show_bans` : liste les bans raid actifs\n"
            "`/cancel_raid` : annule un raid\n"
            "`/force_close` : clôture un sondage"
        ),
        inline=False,
    )
    embed.add_field(
        name="Absences",
        value=(
            "`/absence declare` : ouvre le formulaire d'absence\n"
            "`/absence panel` : poste le bouton d'absence\n"
            "`/absence search` : recherche les absences\n"
            "`/absence add` : ajoute une absence pour un membre\n"
            "`/absence stop` : stoppe une absence\n"
            "`/absence kick` : prévient un membre AFK, remet le rôle de base et envoie le MP"
        ),
        inline=False,
    )
    embed.add_field(
        name="Vérification Dofus",
        value=(
            "`/stuff refresh` : regenere le dernier stuff Dofusbook recent du salon\n"
            "Lien Dofusbook poste : genere automatiquement une image du stuff\n"
            "`/mychars` : liste tes personnages vérifiés\n"
            "`/chars` : liste les personnages vérifiés d'un membre\n"
            "`/find` : retrouve le Discord lié à un personnage"
        ),
        inline=False,
    )
    embed.add_field(
        name="Configuration",
        value=(
            "`/setchannel` : configure les salons\n"
            "`/setbotadminrole` : configure le rôle admin bot\n"
            "`/setraidrole` : configure le rôle organisateur\n"
            "`/setraidnotifyrole` : configure le rôle de notification\n"
            "`/setbaserole` : configure le rôle remis avec `/absence kick`\n"
            "`/setmemberrole` : configure le rôle donné après vérification\n"
            "`/setunverifiedrole` : configure le rôle retiré après vérification\n"
            "`/setdofusconfig` : configure guilde/serveur Dofus pour la vérification\n"
            "`/showconfig` : affiche la configuration"
        ),
        inline=False,
    )
    embed.add_field(
        name="Menus de rôles",
        value=(
            "`/rolemenu create` : crée un panneau de rôles\n"
            "`/rolemenu edit_description` : édite la description en multiline\n"
            "`/rolemenu add_button` : ajoute un bouton de rôle\n"
            "`/rolemenu edit_button` : modifie un bouton existant\n"
            "`/rolemenu add_select` puis `/rolemenu add_option` : ajoute un menu select\n"
            "`/rolemenu edit_select` / `edit_option` / `move_option` : modifie les selects/options\n"
            "`/rolemenu inspect` : liste les IDs à utiliser pour éditer\n"
            "`/rolemenu export` : récupère le JSON d'un panneau existant\n"
            "`/rolemenu copy` : duplique un panneau dans un salon\n"
            "`/rolemenu import_config` : crée un panneau complet depuis du JSON"
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
