import discord
from discord.ext import commands


HELP_SECTIONS = (
    (
        "Général",
        (
            ("`/help`", "affiche cette aide"),
            ("`/ping`", "vérifie que le bot répond"),
        ),
    ),
    (
        "Raids",
        (
            ("`/raid start`", "crée un raid ou un sondage"),
            ("`/raid list`", "liste les raids actifs"),
            ("`/raid cancel`", "annule un raid"),
            ("`/raid close`", "clôture un sondage"),
            ("`/raid warn`", "avertit un membre pour les raids"),
            ("`/raid ban` / `/raid unban`", "gère les bans raid"),
            ("`/raid bans`", "liste les bans actifs"),
        ),
    ),
    (
        "Absences",
        (
            ("`/absence declare`", "ouvre le formulaire d'absence"),
            ("`/absence panel`", "poste le bouton d'absence"),
            ("`/absence search`", "recherche les absences"),
            ("`/absence add`", "ajoute une absence pour un membre"),
            ("`/absence stop`", "stoppe une absence"),
            ("`/absence kick`", "prévient un membre AFK, remet le rôle de base et envoie le MP"),
        ),
    ),
    (
        "Stuff Dofusbook",
        (
            ("`/stuff refresh`", "régénère le dernier stuff Dofusbook récent du salon"),
            ("Lien Dofusbook posté", "génère automatiquement une image du stuff"),
        ),
    ),
    (
        "Vérification Dofus",
        (
            ("`/mychars`", "liste tes personnages vérifiés"),
            ("`/chars`", "liste les personnages vérifiés d'un membre"),
            ("`/find`", "retrouve le Discord lié à un personnage"),
        ),
    ),
    (
        "Configuration",
        (
            ("`/config channel`", "configure les salons"),
            ("`/config role`", "configure les rôles"),
            ("`/config dofus`", "configure guilde/serveur Dofus pour la vérification"),
            ("`/config show`", "affiche la configuration"),
        ),
    ),
    (
        "Menus de rôles",
        (
            ("`/rolemenu create`", "crée un panneau de rôles"),
            ("`/rolemenu edit_embed` / `edit_description`", "édite l'embed"),
            ("`/rolemenu add_button` / `edit_button`", "gère les boutons"),
            ("`/rolemenu add_select` / `edit_select`", "gère les selects"),
            ("`/rolemenu add_option` / `edit_option` / `move_option`", "gère les options"),
            ("`/rolemenu remove_component` / `remove_option`", "supprime un élément"),
            ("`/rolemenu list` / `inspect` / `refresh`", "exploite les panneaux"),
            ("`/rolemenu export` / `import_config` / `copy`", "duplique ou restaure"),
        ),
    ),
    (
        "Admin",
        (
            ("`/sync`", "synchronise les commandes"),
            ("`/reload`", "recharge un cog"),
        ),
    ),
)


def _format_help_lines(entries: tuple[tuple[str, str], ...]) -> str:
    return "\n".join(f"{command} : {description}" for command, description in entries)


def _help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Aide Beb Raid",
        description="Commandes disponibles sur ce serveur.",
        color=0x2ECC71,
    )
    for name, entries in HELP_SECTIONS:
        embed.add_field(name=name, value=_format_help_lines(entries), inline=False)
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
