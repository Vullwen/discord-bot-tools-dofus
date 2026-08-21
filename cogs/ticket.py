"""Gestion des salons de ticket déjà ouverts.

Les boutons de ticket existants permettent encore de créer un raid depuis le
salon privé, d'ajouter des membres et de fermer le salon.
"""
from __future__ import annotations

import logging
import re
import secrets
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from cogs.deathnote import normalize_pseudo
from config import RAID_NAMES
from utils import dates as dates_utils
from utils import names as names_utils
from utils.perms import can_manage_ticket, is_bot_admin, is_raid_organizer

logger = logging.getLogger("dofus-raid-bot.ticket")

DEFAULT_RULE_SECTIONS = (
    (
        "👤 1 — Comportement des membres",
        (
            "Respect obligatoire entre tous les membres",
            "Aucune insulte, harcèlement, menace ou provocation gratuite",
            "Pas de propos discriminatoires ou haineux",
            "Les conflits personnels se règlent en privé ou via un officier",
            "Le troll léger est toléré ; le manque de respect ne l'est pas",
        ),
    ),
    (
        "💬 2 — Utilisation des salons",
        (
            "Poster dans le bon salon",
            "Pas de spam, flood ou pollution de discussion",
            "Pas de publicité externe sans autorisation d'un officier",
            "Les salons d'annonce et d'organisation ne sont pas des salons de débat",
            "Respecter les consignes épinglées",
        ),
    ),
    (
        "⚔️ 3 — Règles en jeu",
        (
            "Représenter la guilde/alliance correctement en jeu",
            "Pas d'arnaque, d'abus ou de comportement toxique sous le blason",
            "Participation aux activités de guilde/alliance selon disponibilités",
            "Prévenir en cas d'absence longue",
            "Respect des décisions AvA / défense / stratégie",
        ),
    ),
    (
        "🏆 4 — Hiérarchie et décisions",
        (
            "La hiérarchie doit être respectée",
            "Les décisions du Chef et des Bras Droits font autorité",
            "Les officiers peuvent modérer, déplacer ou sanctionner",
        ),
    ),
    (
        "🤝 5 — Entraide",
        (
            "L'entraide doit rester réciproque et raisonnable",
            "Les demandes répétées sans participation aux besoins des autres pourront entraîner un avertissement",
            "Après un avertissement, le membre concerné reçoit le rang Fouine pendant la période de suivi",
            "En cas de récidive, une exclusion temporaire pourra être appliquée",
            "Les membres plus bas niveau ne seront pas pénalisés lorsqu'ils ne peuvent pas aider sur du contenu trop avancé",
        ),
    ),
    (
        "🔐 6 — Sécurité et confidentialité",
        (
            "Ne partage jamais tes identifiants",
            "Ne partage jamais les informations personnelles d'un membre",
            "Ne partage jamais les contenus privés du serveur",
            "Pas de doxxing ou fouille d'informations",
        ),
    ),
    (
        "🎙️ 7 — Vocal",
        (
            "Micro propre et audible si possible",
            "Push-to-talk recommandé si environnement bruyant",
            "Respect des activités en cours : donjon, AvA, organisation",
        ),
    ),
    (
        "🚫 8 — Contenus interdits",
        (
            "Contenus NSFW",
            "Liens douteux / malware",
            "Cheat, bot illégal",
            "Politique / religion : éviter les débats conflictuels",
        ),
    ),
    (
        "✍️ 9 — Acceptation",
        (
            "Toute présence sur le serveur vaut acceptation du règlement",
            "Les règles peuvent évoluer ; les membres seront informés",
            "Respecte la meute, et la meute te protégera",
        ),
    ),
)


def _safe_onboarding_channel_name(member: discord.Member) -> str:
    display = getattr(member, "display_name", None) or getattr(member, "name", "nouveau")
    base = display.casefold().strip()
    base = re.sub(r"[^a-z0-9-]+", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    return f"ticket-{base or 'nouveau'}-{secrets.token_hex(2)}"[:90]


def _format_lines(lines: tuple[str, ...]) -> str:
    return "\n".join(f"- {line}" for line in lines)


def _apply_rules_branding(
    embed: discord.Embed,
    *,
    guild_name: str,
    guild_icon_url: Optional[str],
) -> discord.Embed:
    if guild_icon_url:
        embed.set_author(name=guild_name, icon_url=guild_icon_url)
        embed.set_thumbnail(url=guild_icon_url)
    else:
        embed.set_author(name=guild_name)
    return embed


def _rules_embed(
    *,
    guild_name: str = "Serveur Discord",
    guild_icon_url: Optional[str] = None,
) -> discord.Embed:
    embed = discord.Embed(
        title=guild_name.strip() or "Serveur Discord",
        description="📜 Règlement du serveur. Merci de le lire avant de cliquer sur le bouton d'acceptation.",
        color=0x2ECC71,
    )
    for name, lines in DEFAULT_RULE_SECTIONS:
        embed.add_field(name=name, value=_format_lines(lines), inline=False)
    return _apply_rules_branding(embed, guild_name=guild_name, guild_icon_url=guild_icon_url)


def _configured_onboarding_role_ids(guild_id: int) -> set[int]:
    role_ids: set[int] = set()
    for setting in (
        db.SETTING_GUILD_MEMBER_ROLE,
        db.SETTING_VERIFIED_MEMBER_ROLE,
        db.SETTING_VISITOR_ROLE,
    ):
        role_id = db.get_guild_setting_int(guild_id, setting)
        if role_id:
            role_ids.add(role_id)
    return role_ids


def _has_onboarding_role(member: discord.Member, guild_id: int) -> bool:
    role_ids = _configured_onboarding_role_ids(guild_id)
    if not role_ids:
        return False
    return any(getattr(role, "id", None) in role_ids for role in getattr(member, "roles", []))


def _deathnote_application_matches(guild_id: int, *texts: Optional[str]):
    entries = db.list_deathnote_entries(guild_id=guild_id, limit=500)
    normalized_texts = [normalize_pseudo(text) for text in texts if text]
    return [
        entry
        for entry in entries
        if any(entry["normalized_pseudo"] in text for text in normalized_texts)
    ]


def _format_deathnote_matches(rows) -> str:
    lines = ["Candidature bloquée : match trouvé dans la deathnote."]
    for row in rows[:5]:
        reason = row["reason"].strip().rstrip(".")
        lines.append(f"- **{row['pseudo']}** : {reason}")
    if len(rows) > 5:
        lines.append(f"- +{len(rows) - 5} autre(s) entrée(s)")
    return "\n".join(lines)


def _parse_whois_account(value: str) -> Optional[str]:
    match = re.search(r"\]\s*(?P<account>.+?)\s+\([^)]+\)\s+se trouve\b", value.strip(), flags=re.IGNORECASE)
    if match is None:
        return None
    account = match.group("account").strip()
    return account or None


class RaidCreateModal(discord.ui.Modal, title="🎯 Créer un raid"):
    raid_input = discord.ui.TextInput(
        label="Raid",
        placeholder=f"{ ' / '.join(RAID_NAMES)} (laisser vide = sondage)",
        required=False,
        max_length=50,
    )
    date_input = discord.ui.TextInput(
        label="Date / heure",
        placeholder="28/06, demain 19h30, 21h… (une heure fixe l'heure)",
        required=True,
        max_length=30,
    )

    def __init__(self, bot: commands.Bot):
        super().__init__()
        self.bot = bot

    async def on_submit(self, interaction: discord.Interaction) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message(
                "🔒 Tu dois avoir le rôle organisateur (ou être admin) pour créer un raid.",
                ephemeral=True,
            )
            return
        raid_cog = self.bot.get_cog("RaidCog")
        if raid_cog is None:
            await interaction.response.send_message("Module de raid indisponible.", ephemeral=True)
            return

        raid_raw = (self.raid_input.value or "").strip()
        if raid_raw:
            matched = names_utils.match_raid_name(raid_raw, RAID_NAMES)
            if matched is None:
                await interaction.response.send_message(
                    f"❌ Raid inconnu. Choix possibles : {', '.join(RAID_NAMES)}.",
                    ephemeral=True,
                )
                return
            raid_name: Optional[str] = matched
        else:
            raid_name = None

        channel = raid_cog._resolve_raids_channel(interaction.guild, interaction.channel)
        if channel is None or not isinstance(channel, discord.abc.Messageable):
            await interaction.response.send_message("Aucun salon de raids configuré.", ephemeral=True)
            return

        date_value = self.date_input.value
        try:
            dates_utils.parse_raid_date(date_value)  # validation précoce
        except dates_utils.InvalidRaidDate as exc:
            await interaction.response.send_message(f"❌ Date invalide : {exc}", ephemeral=True)
            return

        # Heure fixée -> création directe ; sinon -> menu de choix des créneaux.
        if dates_utils.parse_time(date_value) is not None:
            try:
                raid_id = await raid_cog.create_raid(
                    interaction.guild, channel, interaction.user, raid_name, date_value
                )
            except dates_utils.InvalidRaidDate as exc:
                await interaction.response.send_message(f"❌ Date invalide : {exc}", ephemeral=True)
                return
            await interaction.response.send_message(
                f"✅ Raid **#{raid_id}** créé — sondage posté dans {channel.mention}.",
                ephemeral=False,
            )
            return

        await raid_cog._prompt_hour_choice(
            interaction, interaction.guild, channel, interaction.user,
            raid_name, date_value, None,
        )


class _CreateFromTicketButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(label="🎯 Créer ce raid", style=discord.ButtonStyle.primary, custom_id="bebraid:ticket_create")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_modal(RaidCreateModal(self.cog.bot))


class _CloseTicketButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(label="🔒 Fermer", style=discord.ButtonStyle.danger, custom_id="bebraid:ticket_close")
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_ticket(interaction)


class _AddMemberButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="➕ Ajouter un membre",
            style=discord.ButtonStyle.secondary,
            custom_id="bebraid:ticket_add",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_add_member(interaction)


class _AddMemberSelect(discord.ui.UserSelect):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            placeholder="Sélectionne un ou plusieurs membres à ajouter",
            min_values=1,
            max_values=10,
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.add_members(interaction, self.values)


class AddMemberView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=300)
        self.add_item(_AddMemberSelect(cog))


class TicketChannelView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_CreateFromTicketButton(cog))
        self.add_item(_AddMemberButton(cog))
        self.add_item(_CloseTicketButton(cog))


class _JoinGuildButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="Rejoindre la guilde",
            style=discord.ButtonStyle.success,
            custom_id="bebraid:onboarding_join_guild",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.start_guild_application(interaction)


class _VisitorButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="Accès marché",
            style=discord.ButtonStyle.primary,
            custom_id="bebraid:onboarding_visitor",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.choose_onboarding_path(interaction, choice="visitor")


class OnboardingChoiceView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_JoinGuildButton(cog))
        self.add_item(_VisitorButton(cog))
        self.add_item(_CloseOnboardingButton(cog))


class _AcceptGuildButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="Accepter",
            style=discord.ButtonStyle.success,
            custom_id="bebraid:onboarding_accept",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.start_onboarding_accept(interaction)


class _RejectGuildButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="Refuser",
            style=discord.ButtonStyle.danger,
            custom_id="bebraid:onboarding_reject",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.review_onboarding_request(interaction, accepted=False)


class OnboardingReviewView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_AcceptGuildButton(cog))
        self.add_item(_RejectGuildButton(cog))
        self.add_item(_CloseOnboardingButton(cog))


class _CloseOnboardingButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="Clôturer le ticket",
            style=discord.ButtonStyle.danger,
            custom_id="bebraid:onboarding_close",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_onboarding_ticket(interaction)


class OnboardingCloseView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_CloseOnboardingButton(cog))


class GuildApplicationModal(discord.ui.Modal, title="Candidature guilde"):
    pseudo_input = discord.ui.TextInput(
        label="Pseudo en jeu",
        placeholder="Exemple : Belette-Royale",
        required=True,
        max_length=80,
    )
    classes_input = discord.ui.TextInput(
        label="Classe(s) / Niveau(x)",
        placeholder="Exemple : Eniripsa 200, Iop 199",
        required=True,
        max_length=200,
    )
    goals_input = discord.ui.TextInput(
        label="Objectifs dans le jeu",
        placeholder="Koli, PvM, fun, opti...",
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: "TicketCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.submit_guild_application(
            interaction,
            pseudo=str(self.pseudo_input.value),
            classes=str(self.classes_input.value),
            goals=str(self.goals_input.value),
        )


class WhoisValidationModal(discord.ui.Modal, title="Validation /whois"):
    whois_input = discord.ui.TextInput(
        label="Résultat /whois",
        placeholder="[21:55] Molg#3264 (Brouki) se trouve en Île de Frigost sur le serveur Dakal...",
        required=True,
        max_length=500,
        style=discord.TextStyle.paragraph,
    )

    def __init__(self, cog: "TicketCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.review_onboarding_request(
            interaction,
            accepted=True,
            whois_result=str(self.whois_input.value),
        )


class _AcceptRulesButton(discord.ui.Button):
    def __init__(self, cog: "TicketCog"):
        super().__init__(
            label="J'accepte le règlement",
            style=discord.ButtonStyle.success,
            custom_id="bebraid:rules_accept",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.accept_rules(interaction)


class RulesAcceptView(discord.ui.View):
    def __init__(self, cog: "TicketCog"):
        super().__init__(timeout=None)
        self.add_item(_AcceptRulesButton(cog))


class TicketCog(commands.Cog):
    ticket = app_commands.Group(name="ticket", description="Gestion des tickets")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        # Vues persistantes (custom_id fixes) : routage sur tous les messages.
        self.bot.add_view(TicketChannelView(self))
        self.bot.add_view(OnboardingChoiceView(self))
        self.bot.add_view(OnboardingReviewView(self))
        self.bot.add_view(OnboardingCloseView(self))
        self.bot.add_view(RulesAcceptView(self))
        logger.info("TicketCog prêt")

    @ticket.command(name="reglement", description="Poste le bouton d'acceptation du règlement")
    @app_commands.describe(
        channel="Salon où poster le bouton (vide = salon actuel)",
        titre="Titre custom si l'option texte est renseignée",
        texte="Texte custom optionnel. Utilise \\n pour forcer un retour ligne.",
    )
    async def ticket_rules_panel(
        self,
        interaction: discord.Interaction,
        channel: Optional[discord.TextChannel] = None,
        titre: str = "Règlement",
        texte: Optional[str] = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return

        target = channel or interaction.channel
        if target is None or not isinstance(target, discord.abc.Messageable):
            await interaction.response.send_message("Salon introuvable.", ephemeral=True)
            return

        guild_icon_url = interaction.guild.icon.url if interaction.guild.icon else None
        guild_name = interaction.guild.name

        if texte is None or not texte.strip():
            embed = _rules_embed(guild_name=guild_name, guild_icon_url=guild_icon_url)
        else:
            embed = discord.Embed(
                title=(titre.strip() if titre and titre.strip() else guild_name),
                description=texte.strip().replace("\\n", "\n"),
                color=0x2ECC71,
            )
            _apply_rules_branding(embed, guild_name=guild_name, guild_icon_url=guild_icon_url)

        await target.send(embed=embed, view=RulesAcceptView(self))
        await interaction.response.send_message(
            f"Panneau d'acceptation posté dans {target.mention}.",
            ephemeral=True,
        )

    async def accept_rules(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if _has_onboarding_role(interaction.user, interaction.guild.id):
            await interaction.response.send_message(
                "Tu as déjà accès au serveur. Pas besoin de rouvrir un ticket.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True)
        channel = await self.open_onboarding_ticket(
            interaction.user,
            reason="Ticket d'accueil après clic règlement",
        )
        if channel is None:
            await interaction.followup.send(
                "Impossible de créer ton ticket. Préviens un admin.",
                ephemeral=True,
            )
            return
        await interaction.followup.send(
            f"Règlement accepté. Ton ticket est ouvert ici : {channel.mention}.",
            ephemeral=True,
        )

    async def open_onboarding_ticket(self, member: discord.Member, *, reason: str) -> Optional[discord.TextChannel]:
        guild = member.guild
        existing = db.get_open_onboarding_ticket_for_user(guild_id=guild.id, user_id=member.id)
        if existing is not None:
            channel = guild.get_channel(existing["channel_id"])
            if isinstance(channel, discord.TextChannel):
                return channel
            db.update_onboarding_ticket(existing["channel_id"], status="deleted")
            db.close_ticket(existing["channel_id"])

        try:
            channel = await self._create_onboarding_channel(guild, member, reason=reason)
        except discord.DiscordException as exc:
            logger.warning("Création ticket accueil échouée pour %s: %s", member, exc)
            return None

        db.create_ticket(channel_id=channel.id, guild_id=guild.id, opener_id=member.id)
        db.create_onboarding_ticket(channel_id=channel.id, guild_id=guild.id, user_id=member.id)
        await channel.send(
            content=member.mention,
            embed=self._onboarding_choice_embed(),
            view=OnboardingChoiceView(self),
        )
        return channel

    async def _create_onboarding_channel(
        self,
        guild: discord.Guild,
        member: discord.Member,
        *,
        reason: str,
    ) -> discord.TextChannel:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
            member: discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                attach_files=True,
                read_message_history=True,
            ),
        }
        if guild.me is not None:
            overwrites[guild.me] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                manage_channels=True,
                manage_roles=True,
                kick_members=True,
                read_message_history=True,
            )
        bot_admin_role_id = db.get_guild_setting_int(guild.id, db.SETTING_BOT_ADMIN_ROLE)
        if bot_admin_role_id:
            role = guild.get_role(bot_admin_role_id)
            if role is not None:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    read_message_history=True,
                )
        return await guild.create_text_channel(
            name=_safe_onboarding_channel_name(member),
            overwrites=overwrites,
            reason=reason,
        )

    def _onboarding_choice_embed(self) -> discord.Embed:
        embed = discord.Embed(
            title="Bienvenue chez B&B",
            description=(
                "Souhaites-tu rejoindre la guilde ou avoir accès au marché d'items ?"
            ),
            color=0x2ECC71,
        )
        return embed

    def _guild_application_embed(self, *, pseudo: str, classes: str, goals: str) -> discord.Embed:
        embed = discord.Embed(
            title="Candidature guilde",
            description="Réponses envoyées via le formulaire d'inscription.",
            color=0xF1C40F,
        )
        embed.add_field(name="Pseudo en jeu", value=pseudo.strip() or "Non renseigné", inline=False)
        embed.add_field(name="Classe(s) / Niveau(x)", value=classes.strip() or "Non renseigné", inline=False)
        embed.add_field(name="Objectifs", value=goals.strip() or "Non renseigné", inline=False)
        return embed

    async def start_guild_application(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        ticket = db.get_onboarding_ticket_by_channel(interaction.channel_id)
        if ticket is None or ticket["status"] in ("closed", "deleted"):
            await interaction.response.send_message("Ticket d'accueil introuvable.", ephemeral=True)
            return
        if ticket["status"] != "pending":
            await interaction.response.send_message("Un choix a déjà été enregistré pour ce ticket.", ephemeral=True)
            return
        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message("Seul le nouveau membre peut choisir ici.", ephemeral=True)
            return
        await interaction.response.send_modal(GuildApplicationModal(self))

    async def submit_guild_application(
        self,
        interaction: discord.Interaction,
        *,
        pseudo: str,
        classes: str,
        goals: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        ticket = db.get_onboarding_ticket_by_channel(interaction.channel_id)
        if ticket is None or ticket["status"] in ("closed", "deleted"):
            await interaction.response.send_message("Ticket d'accueil introuvable.", ephemeral=True)
            return
        if ticket["status"] != "pending":
            await interaction.response.send_message("Un choix a déjà été enregistré pour ce ticket.", ephemeral=True)
            return
        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message("Seul le nouveau membre peut choisir ici.", ephemeral=True)
            return

        clean_pseudo = pseudo.strip()
        clean_classes = classes.strip()
        clean_goals = goals.strip()
        if not clean_pseudo or not clean_classes or not clean_goals:
            await interaction.response.send_message("Tous les champs du formulaire sont obligatoires.", ephemeral=True)
            return

        deathnote_matches = _deathnote_application_matches(
            interaction.guild.id,
            clean_pseudo,
            clean_classes,
            clean_goals,
            getattr(interaction.user, "display_name", None),
            getattr(interaction.user, "global_name", None),
            getattr(interaction.user, "name", None),
        )
        status = "deathnote_blocked" if deathnote_matches else "guild_pending"
        db.update_onboarding_ticket(
            interaction.channel_id,
            choice="guild",
            status=status,
            application_pseudo=clean_pseudo,
            application_classes=clean_classes,
            application_goals=clean_goals,
        )
        if deathnote_matches:
            content = (
                f"<@{ticket['user_id']}> souhaite rejoindre la guilde.\n"
                f"{_format_deathnote_matches(deathnote_matches)}\n"
                "Aucun rôle ne peut être attribué depuis cette demande. "
                "Un admin bot peut fermer le ticket avec le bouton ci-dessous."
            )
            view = OnboardingCloseView(self)
        else:
            content = (
                f"<@{ticket['user_id']}> souhaite rejoindre la guilde. "
                "Un administrateur regardera sa demande. "
                "Le bouton Accepter est réservé aux admins."
            )
            view = OnboardingReviewView(self)
        await interaction.response.send_message(
            content=content,
            embed=self._guild_application_embed(
                pseudo=clean_pseudo,
                classes=clean_classes,
                goals=clean_goals,
            ),
            view=view,
        )

    async def choose_onboarding_path(
        self,
        interaction: discord.Interaction,
        *,
        choice: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        ticket = db.get_onboarding_ticket_by_channel(interaction.channel_id)
        if ticket is None or ticket["status"] in ("closed", "deleted"):
            await interaction.response.send_message("Ticket d'accueil introuvable.", ephemeral=True)
            return
        if ticket["status"] != "pending":
            await interaction.response.send_message("Un choix a déjà été enregistré pour ce ticket.", ephemeral=True)
            return
        if interaction.user.id != ticket["user_id"]:
            await interaction.response.send_message("Seul le nouveau membre peut choisir ici.", ephemeral=True)
            return

        if choice == "guild":
            await interaction.response.send_modal(GuildApplicationModal(self))
            return

        db.update_onboarding_ticket(
            interaction.channel_id,
            choice="visitor",
            status="visitor_pending",
        )
        await interaction.response.send_message(
            content=(
                f"<@{ticket['user_id']}> demande l'accès au marché. "
                "Un administrateur regardera ta demande. "
                "Le bouton Accepter est réservé aux admins."
            ),
            ephemeral=False,
            view=OnboardingReviewView(self),
        )

    async def start_onboarding_accept(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        ticket = db.get_onboarding_ticket_by_channel(interaction.channel_id)
        if ticket is None or ticket["status"] in ("closed", "deleted"):
            await interaction.response.send_message("Ticket d'accueil introuvable.", ephemeral=True)
            return
        if ticket["status"] not in ("guild_pending", "visitor_pending"):
            await interaction.response.send_message("Cette demande a déjà été traitée.", ephemeral=True)
            return
        if ticket["choice"] == "guild":
            await interaction.response.send_modal(WhoisValidationModal(self))
            return
        await self.review_onboarding_request(interaction, accepted=True)

    async def review_onboarding_request(
        self,
        interaction: discord.Interaction,
        *,
        accepted: bool,
        whois_result: Optional[str] = None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        ticket = db.get_onboarding_ticket_by_channel(interaction.channel_id)
        if ticket is None or ticket["status"] in ("closed", "deleted"):
            await interaction.response.send_message("Ticket d'accueil introuvable.", ephemeral=True)
            return
        if ticket["status"] not in ("guild_pending", "visitor_pending"):
            await interaction.response.send_message("Cette demande a déjà été traitée.", ephemeral=True)
            return
        if ticket["choice"] not in ("guild", "visitor"):
            await interaction.response.send_message("Ce ticket n'est pas une demande d'accueil.", ephemeral=True)
            return

        if accepted:
            if ticket["choice"] == "visitor":
                report = await self._grant_visitor_role(interaction.guild, ticket["user_id"])
                status = "visitor_granted"
                message = "Accès marché accepté."
            else:
                account_name = _parse_whois_account(whois_result or "")
                if account_name is None:
                    await interaction.response.send_message(
                        "Résultat /whois invalide. Colle la ligne complète du jeu avant d'accepter.",
                        ephemeral=True,
                    )
                    return
                deathnote_matches = _deathnote_application_matches(
                    interaction.guild.id,
                    account_name,
                    ticket["application_pseudo"],
                    ticket["application_classes"],
                    ticket["application_goals"],
                )
                if deathnote_matches:
                    db.update_onboarding_ticket(
                        interaction.channel_id,
                        status="deathnote_blocked",
                    )
                    await interaction.response.send_message(
                        f"{_format_deathnote_matches(deathnote_matches)}\n"
                        f"Compte /whois vérifié : `{account_name}`.\n"
                        "Aucun rôle n'a été attribué. "
                        "Un admin bot peut fermer le ticket avec le bouton ci-dessous.",
                        ephemeral=False,
                        view=OnboardingCloseView(self),
                    )
                    return
                report = await self._grant_guild_role(interaction.guild, ticket["user_id"])
                status = "accepted"
                message = f"Candidature acceptée.\nCompte /whois vérifié : `{account_name}`."
            db.update_onboarding_ticket(
                interaction.channel_id,
                status=status,
            )
            await interaction.response.send_message(
                f"{message}\n{report}\nUn admin bot peut fermer le ticket avec le bouton ci-dessous.",
                ephemeral=False,
                view=OnboardingCloseView(self),
            )
            return

        report = await self._kick_onboarding_member(interaction.guild, ticket["user_id"])
        db.update_onboarding_ticket(
            interaction.channel_id,
            status="rejected",
        )
        message = (
            "Accès marché refusé."
            if ticket["choice"] == "visitor"
            else "Candidature refusée."
        )
        await interaction.response.send_message(
            f"{message}\n{report}\nUn admin bot peut fermer le ticket avec le bouton ci-dessous.",
            ephemeral=False,
            view=OnboardingCloseView(self),
        )

    async def review_guild_application(
        self,
        interaction: discord.Interaction,
        *,
        accepted: bool,
    ) -> None:
        if accepted:
            await self.start_onboarding_accept(interaction)
            return
        await self.review_onboarding_request(interaction, accepted=accepted)

    async def _grant_guild_role(self, guild: discord.Guild, user_id: int) -> str:
        role_id = (
            db.get_guild_setting_int(guild.id, db.SETTING_GUILD_MEMBER_ROLE)
            or db.get_guild_setting_int(guild.id, db.SETTING_VERIFIED_MEMBER_ROLE)
        )
        return await self._grant_role(
            guild,
            user_id,
            role_id,
            missing_message="Aucun rôle membre guilde configuré.",
            reason="Candidature guilde acceptée",
        )

    async def _grant_visitor_role(self, guild: discord.Guild, user_id: int) -> str:
        return await self._grant_role(
            guild,
            user_id,
            db.get_guild_setting_int(guild.id, db.SETTING_VISITOR_ROLE),
            missing_message="Aucun rôle visiteur marché configuré.",
            reason="Accès marché demandé via ticket d'accueil",
        )

    async def _grant_role(
        self,
        guild: discord.Guild,
        user_id: int,
        role_id: Optional[int],
        *,
        missing_message: str,
        reason: str,
    ) -> str:
        if not role_id:
            return missing_message
        role = guild.get_role(role_id)
        if role is None:
            return "Rôle configuré introuvable."
        member = await self._fetch_member(guild, user_id)
        if member is None:
            return "Membre introuvable."
        try:
            await member.add_roles(role, reason=reason)
        except discord.DiscordException as exc:
            logger.warning("Attribution rôle accueil échouée: %s", exc)
            return "Rôle non attribué : permission Discord insuffisante."
        return f"Rôle attribué : {role.mention}."

    async def _kick_onboarding_member(self, guild: discord.Guild, user_id: int) -> str:
        member = await self._fetch_member(guild, user_id)
        if member is None:
            return "Membre déjà absent du serveur."
        try:
            await member.kick(reason="Candidature guilde refusée")
        except discord.DiscordException as exc:
            logger.warning("Kick candidature refusée échoué: %s", exc)
            return "Kick non effectué : permission Discord insuffisante."
        return "Membre kick du serveur."

    async def _fetch_member(self, guild: discord.Guild, user_id: int) -> Optional[discord.Member]:
        member = guild.get_member(user_id)
        if member is not None:
            return member
        try:
            return await guild.fetch_member(user_id)
        except discord.DiscordException:
            return None

    async def close_onboarding_ticket(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        ticket = db.get_onboarding_ticket_by_channel(interaction.channel_id)
        if ticket is None:
            await interaction.response.send_message("Ticket d'accueil introuvable.", ephemeral=True)
            return

        db.close_onboarding_ticket(interaction.channel_id)
        await interaction.response.send_message("Ticket d'accueil fermé. Suppression du salon...", ephemeral=False)
        try:
            await interaction.channel.delete(reason="Ticket d'accueil fermé par un admin bot")
        except discord.DiscordException as exc:
            logger.warning("Suppression ticket accueil %s échouée: %s", interaction.channel_id, exc)

    async def close_ticket(self, interaction: discord.Interaction) -> None:
        ticket = db.get_ticket_by_channel(interaction.channel_id)
        if not can_manage_ticket(interaction, ticket):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        if ticket is not None:
            db.close_ticket(interaction.channel_id)
        await interaction.response.send_message("🔒 Ticket fermé. Suppression du salon...", ephemeral=False)
        try:
            await interaction.channel.delete(reason="Ticket raid fermé")
        except discord.DiscordException as exc:
            logger.warning("Suppression du ticket %s échouée: %s", interaction.channel_id, exc)

    def _is_ticket_manager(self, interaction: discord.Interaction) -> bool:
        """Organisateur (admin/rôle) ou opener du ticket : peut ajouter des membres / fermer."""
        ticket = db.get_ticket_by_channel(interaction.channel_id)
        return can_manage_ticket(interaction, ticket)

    async def prompt_add_member(self, interaction: discord.Interaction) -> None:
        if not self._is_ticket_manager(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        await interaction.response.send_message(
            "👤 Choisis les membres à ajouter au salon :", view=AddMemberView(self), ephemeral=True
        )

    async def add_members(self, interaction: discord.Interaction, users) -> None:
        guild = interaction.guild
        channel = interaction.channel
        if guild is None or not isinstance(channel, discord.abc.GuildChannel):
            return
        added: list[str] = []
        skipped: list[str] = []
        for user in users:
            member = guild.get_member(user.id)
            if member is None:
                try:
                    member = await guild.fetch_member(user.id)
                except discord.DiscordException:
                    member = None
            if member is None:
                skipped.append(f"`{user}`")
                continue
            try:
                await channel.set_permissions(
                    member,
                    view_channel=True,
                    send_messages=True,
                    attach_files=True,
                    read_message_history=True,
                    reason=f"Ajouté au ticket par {interaction.user}",
                )
                added.append(member.mention)
            except discord.DiscordException as exc:
                logger.warning("Ajout membre %s au ticket %s échoué: %s", member, channel.id, exc)
                skipped.append(member.mention)

        parts: list[str] = []
        if added:
            parts.append(f"✅ Ajouté au salon : {', '.join(added)}")
        if skipped:
            parts.append(f"⚠️ Impossible à ajouter : {', '.join(skipped)}")
        if not parts:
            parts.append("Aucun membre à ajouter.")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TicketCog(bot))
