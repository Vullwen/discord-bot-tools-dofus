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
            "`/raid` : crée un raid ou un sondage\n"
            "`/list_raids` : liste les raids actifs\n"
            "`/cancel_raid` : annule un raid\n"
            "`/force_close` : clôture un sondage\n"
            "`/ban_raid` / `/unban_raid` : gère les bans raid\n"
            "`/show_bans` : liste les bans actifs"
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
        name="Stuff Dofusbook",
        value=(
            "`/stuff refresh` : régénère le dernier stuff Dofusbook récent du salon\n"
            "Lien Dofusbook posté : génère automatiquement une image du stuff"
        ),
        inline=False,
    )
    embed.add_field(
        name="Vérification Dofus",
        value=(
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
            "`/setbotadminrole` / `/setraidrole` : configure les droits bot/raid\n"
            "`/setraidnotifyrole` : configure le rôle de notification raid\n"
            "`/setbaserole` : configure le rôle remis avec `/absence kick`\n"
            "`/setmemberrole` / `/setunverifiedrole` : configure les rôles de vérification\n"
            "`/setdofusconfig` : configure guilde/serveur Dofus pour la vérification\n"
            "`/showconfig` : affiche la configuration"
        ),
        inline=False,
    )
    embed.add_field(
        name="Menus de rôles",
        value=(
            "`/rolemenu create` : crée un panneau de rôles\n"
            "`/rolemenu edit_embed` / `edit_description` : édite l'embed\n"
            "`/rolemenu add_button` / `edit_button` : gère les boutons\n"
            "`/rolemenu add_select` / `edit_select` : gère les selects\n"
            "`/rolemenu add_option` / `edit_option` / `move_option` : gère les options\n"
            "`/rolemenu remove_component` / `remove_option` : supprime un élément\n"
            "`/rolemenu list` / `inspect` / `refresh` : exploite les panneaux\n"
            "`/rolemenu export` / `import_config` / `copy` : duplique ou restaure"
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
