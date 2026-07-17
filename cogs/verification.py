"""Vérification des personnages Dofus par ticket privé + analyse d'image."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
from datetime import timedelta
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from config import (
    DOFUS_GUILD_NAME,
    DOFUS_SERVER,
    VERIFICATION_CODE_PREFIX,
    VERIFICATION_EXPIRES_MINUTES,
    now_paris,
)
from utils.perms import is_raid_organizer
from utils.verification import VerificationResult, evaluate_ocr_text, extract_text_from_image_bytes

logger = logging.getLogger("dofus-raid-bot.verification")


def _setting_or_default(guild_id: int, key: str, default: str) -> str:
    value = db.get_guild_setting(guild_id, key)
    return value.strip() if value and value.strip() else default


def _safe_channel_name(character_name: str) -> str:
    base = character_name.casefold().strip()
    base = re.sub(r"[^a-z0-9-]+", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    return f"verification-{base or 'perso'}-{secrets.token_hex(2)}"[:90]


def _new_code() -> str:
    return f"{VERIFICATION_CODE_PREFIX}-{secrets.randbelow(900000) + 100000}"


def _is_image_attachment(attachment: discord.Attachment) -> bool:
    if attachment.content_type and attachment.content_type.startswith("image/"):
        return True
    return attachment.filename.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))


def _format_character_list(rows) -> str:
    return "\n".join(
        f"{'* ' if row['is_main'] else '- '}**{row['character_name']}** — {row['server']}"
        for row in rows
    )


class ManualReviewView(discord.ui.View):
    def __init__(self, cog: "VerificationCog", request_id: int):
        super().__init__(timeout=24 * 60 * 60)
        self.cog = cog
        self.request_id = request_id

    @discord.ui.button(label="Valider", style=discord.ButtonStyle.success)
    async def accept(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.manual_review(interaction, self.request_id, accepted=True)

    @discord.ui.button(label="Refuser", style=discord.ButtonStyle.danger)
    async def reject(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.manual_review(interaction, self.request_id, accepted=False)


class VerificationCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def link(
        self,
        interaction: discord.Interaction,
        personnage: str,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        guild = interaction.guild
        existing = db.get_pending_verification_for_user(
            guild_id=guild.id,
            discord_id=interaction.user.id,
            now=now_paris(),
        )
        if existing is not None:
            channel = guild.get_channel(existing["channel_id"])
            if channel is not None:
                await interaction.response.send_message(
                    f"Tu as déjà une vérification ouverte : {channel.mention}.",
                    ephemeral=True,
                )
                return
            db.update_verification_request(existing["id"], status="expired")

        dofus_server = _setting_or_default(guild.id, db.SETTING_DOFUS_SERVER, DOFUS_SERVER)
        dofus_guild = _setting_or_default(guild.id, db.SETTING_DOFUS_GUILD_NAME, DOFUS_GUILD_NAME)
        code = _new_code()
        expires_at = now_paris() + timedelta(minutes=VERIFICATION_EXPIRES_MINUTES)

        await interaction.response.defer(ephemeral=True)
        try:
            channel = await self._create_private_channel(
                guild,
                interaction.user,
                personnage.strip(),
            )
        except discord.DiscordException as exc:
            logger.warning("Création salon vérification échouée: %s", exc)
            await interaction.followup.send(
                "Impossible de créer le salon privé. Vérifie les permissions `Manage Channels` du bot.",
                ephemeral=True,
            )
            return

        request_id = db.create_verification_request(
            guild_id=guild.id,
            discord_id=interaction.user.id,
            channel_id=channel.id,
            character_name=personnage.strip(),
            server=dofus_server,
            code=code,
            expires_at=expires_at,
        )
        await channel.send(
            content=interaction.user.mention,
            embed=self._instructions_embed(
                request_id=request_id,
                character_name=personnage.strip(),
                server=dofus_server,
                guild_name=dofus_guild,
                code=code,
            ),
        )
        await interaction.followup.send(
            f"Salon de vérification créé : {channel.mention}.",
            ephemeral=True,
        )

    @app_commands.command(name="mychars", description="Liste tes personnages Dofus vérifiés")
    async def mychars(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        rows = db.list_user_characters(guild_id=interaction.guild.id, discord_id=interaction.user.id)
        if not rows:
            await interaction.response.send_message("Aucun personnage vérifié pour l'instant.", ephemeral=True)
            return
        await interaction.response.send_message(_format_character_list(rows), ephemeral=True)

    async def unlink(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        rows = db.list_user_characters(guild_id=interaction.guild.id, discord_id=interaction.user.id)
        if not rows:
            await interaction.response.send_message("Aucun personnage vérifié à retirer.", ephemeral=True)
            return

        deleted = db.delete_user_characters(guild_id=interaction.guild.id, discord_id=interaction.user.id)
        report = await self._revert_verified_member_updates(interaction.guild, interaction.user)
        await interaction.response.send_message(
            f"{deleted} personnage(s) délié(s).\n{report}",
            ephemeral=True,
        )

    @app_commands.command(name="chars", description="Liste les personnages Dofus vérifiés d'un membre")
    @app_commands.describe(membre="Compte Discord à consulter")
    async def chars(self, interaction: discord.Interaction, membre: discord.Member) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        rows = db.list_user_characters(guild_id=interaction.guild.id, discord_id=membre.id)
        if not rows:
            await interaction.response.send_message(
                f"Aucun personnage vérifié pour {membre.mention}.",
                ephemeral=True,
            )
            return
        await interaction.response.send_message(
            f"Personnages vérifiés de {membre.mention} :\n{_format_character_list(rows)}",
            ephemeral=True,
        )

    @app_commands.command(name="find", description="Retrouve le Discord lié à un personnage Dofus")
    @app_commands.describe(personnage="Nom exact du personnage Dofus")
    async def find(self, interaction: discord.Interaction, personnage: str) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        row = db.find_character(guild_id=interaction.guild.id, character_name=personnage)
        if row is None:
            await interaction.response.send_message("Personnage introuvable.", ephemeral=True)
            return
        await interaction.response.send_message(
            f"**{row['character_name']}** ({row['server']}) est lié à <@{row['discord_id']}>.",
            ephemeral=True,
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        request = db.get_verification_by_channel(message.channel.id)
        if request is None or request["status"] not in ("pending", "needs_review"):
            return
        if message.author.id != request["discord_id"]:
            return
        if datetime_from_iso(request["expires_at"]) <= now_paris():
            db.update_verification_request(request["id"], status="expired")
            await message.channel.send("Code expiré. Demande un nouveau salon de vérification à un organisateur.")
            return

        images = [attachment for attachment in message.attachments if _is_image_attachment(attachment)]
        if not images:
            return

        await self._process_attachment(message.channel, request, images[0])

    async def _create_private_channel(
        self,
        guild: discord.Guild,
        member: discord.Member,
        character_name: str,
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
                read_message_history=True,
            )
        manager_role_id = db.get_guild_setting_int(guild.id, db.SETTING_RAID_MANAGER_ROLE)
        if manager_role_id:
            manager_role = guild.get_role(manager_role_id)
            if manager_role is not None:
                overwrites[manager_role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    manage_messages=True,
                    read_message_history=True,
                )
        return await guild.create_text_channel(
            name=_safe_channel_name(character_name),
            overwrites=overwrites,
            reason=f"Vérification Dofus pour {member}",
        )

    def _instructions_embed(
        self,
        *,
        request_id: int,
        character_name: str,
        server: str,
        guild_name: str,
        code: str,
    ) -> discord.Embed:
        embed = discord.Embed(
            title="Vérification Dofus",
            description=(
                f"Perso attendu : **{character_name}**\n"
                f"Serveur : **{server}**\n"
                f"Guilde : **{guild_name}**\n"
                f"Code : `{code}`"
            ),
            color=0x3498DB,
        )
        embed.add_field(
            name="À faire en jeu",
            value=(
                "1. Tape `/whoami`\n"
                "2. Tape `/time`\n"
                f"3. Écris `{code}` dans le chat guilde\n"
                "4. Envoie le screenshot ici"
            ),
            inline=False,
        )
        embed.set_footer(
            text=f"Demande #{request_id} • Expire dans {VERIFICATION_EXPIRES_MINUTES} min"
        )
        return embed

    async def _process_attachment(
        self,
        channel: discord.abc.Messageable,
        request,
        attachment: discord.Attachment,
    ) -> None:
        status_message = await channel.send("Analyse en cours...")
        try:
            data = await attachment.read()
            ocr_text = await asyncio.to_thread(extract_text_from_image_bytes, data)
        except Exception as exc:
            logger.warning("Analyse image échouée pour request %s: %s", request["id"], exc)
            await status_message.edit(content="Impossible de lire cette image. Essaie un screenshot plus net.")
            return

        guild_name = _setting_or_default(
            request["guild_id"], db.SETTING_DOFUS_GUILD_NAME, DOFUS_GUILD_NAME
        )
        result = evaluate_ocr_text(
            ocr_text,
            code=request["code"],
            character_name=request["character_name"],
            server=request["server"],
            guild_name=guild_name,
        )
        db.update_verification_request(request["id"], ocr_text=ocr_text, status=result.status)

        if result.is_valid:
            await self._validate_request(channel, request, reviewed_by=None)
            await status_message.edit(content="Vérification validée automatiquement.")
            return

        if result.status == "needs_review":
            await status_message.edit(
                content=(
                    "L'analyse a trouvé le code mais il manque des éléments sûrs. "
                    "Un organisateur peut valider ou refuser ci-dessous."
                ),
                view=ManualReviewView(self, request["id"]),
            )
            await channel.send(embed=self._review_embed(request, result, ocr_text))
            return

        await status_message.edit(
            content=(
                "Code introuvable dans l'image. Vérifie que le screenshot contient bien "
                "`/whoami`, `/time` et le message en chat guilde."
            )
        )

    def _review_embed(self, request, result: VerificationResult, ocr_text: str) -> discord.Embed:
        preview = ocr_text.strip()[:950] or "(aucun texte détecté)"
        embed = discord.Embed(
            title="Vérification à relire",
            description=(
                f"Score d'analyse : **{result.score}/110**\n"
                f"Perso : **{request['character_name']}**\n"
                f"Serveur : **{request['server']}**\n"
                f"Code : `{request['code']}`"
            ),
            color=0xF1C40F,
        )
        if result.reasons:
            embed.add_field(name="Éléments reconnus", value="\n".join(result.reasons), inline=False)
        embed.add_field(name="Texte détecté", value=f"```text\n{preview}\n```", inline=False)
        return embed

    async def manual_review(
        self,
        interaction: discord.Interaction,
        request_id: int,
        *,
        accepted: bool,
    ) -> None:
        if not is_raid_organizer(interaction):
            await interaction.response.send_message("Permission refusée.", ephemeral=True)
            return
        request = db.get_verification_request(request_id)
        if request is None:
            await interaction.response.send_message("Demande introuvable.", ephemeral=True)
            return
        if accepted:
            await self._validate_request(interaction.channel, request, reviewed_by=interaction.user.id)
            await interaction.response.send_message("Vérification validée.", ephemeral=False)
            return
        db.update_verification_request(request_id, status="rejected", reviewed_by=interaction.user.id)
        await interaction.response.send_message("Vérification refusée. Salon supprimé dans 2 minutes.")
        asyncio.create_task(self._delete_later(interaction.channel, "Vérification Dofus refusée"))

    async def _validate_request(
        self,
        channel: discord.abc.Messageable,
        request,
        *,
        reviewed_by: Optional[int],
    ) -> None:
        existing_characters = db.list_user_characters(
            guild_id=request["guild_id"],
            discord_id=request["discord_id"],
        )
        db.save_verified_character(
            guild_id=request["guild_id"],
            discord_id=request["discord_id"],
            character_name=request["character_name"],
            server=request["server"],
            verified_by=reviewed_by,
            is_main=not existing_characters,
        )
        characters = db.list_user_characters(
            guild_id=request["guild_id"],
            discord_id=request["discord_id"],
        )
        main_character = next((row for row in characters if row["is_main"]), None)
        main_name = main_character["character_name"] if main_character else request["character_name"]
        db.update_verification_request(
            request["id"],
            status="validated",
            reviewed_by=reviewed_by,
            verified_at=now_paris(),
        )
        member_report = await self._apply_verified_member_updates(channel, request, main_name)
        await channel.send(
            f"Validation OK pour **{request['character_name']}** ({request['server']}).\n"
            f"{member_report}\n"
            "Le salon sera supprimé dans 2 minutes."
        )
        asyncio.create_task(self._delete_later(channel, "Vérification Dofus terminée"))

    async def _apply_verified_member_updates(
        self,
        channel: discord.abc.Messageable,
        request,
        main_name: str,
    ) -> str:
        guild = getattr(channel, "guild", None)
        if guild is None:
            return "Modifications Discord non appliquées : guilde introuvable."
        member = guild.get_member(request["discord_id"])
        if member is None:
            try:
                member = await guild.fetch_member(request["discord_id"])
            except discord.DiscordException:
                member = None
        if member is None:
            return "Modifications Discord non appliquées : membre introuvable."

        reports: list[str] = []

        verified_role_id = db.get_guild_setting_int(guild.id, db.SETTING_VERIFIED_MEMBER_ROLE)
        if verified_role_id:
            verified_role = guild.get_role(verified_role_id)
            if verified_role is None:
                reports.append("Rôle membre configuré introuvable.")
            else:
                try:
                    await member.add_roles(verified_role, reason="Vérification Dofus validée")
                    reports.append(f"Rôle attribué : {verified_role.mention}.")
                except discord.DiscordException as exc:
                    logger.warning("Attribution rôle vérifié échouée: %s", exc)
                    reports.append("Rôle membre non attribué : permission Discord insuffisante.")
        else:
            reports.append("Aucun rôle membre configuré.")

        unverified_role_id = db.get_guild_setting_int(guild.id, db.SETTING_UNVERIFIED_MEMBER_ROLE)
        if unverified_role_id:
            unverified_role = guild.get_role(unverified_role_id)
            if unverified_role is None:
                reports.append("Rôle à vérifier configuré introuvable.")
            elif unverified_role in getattr(member, "roles", []):
                try:
                    await member.remove_roles(unverified_role, reason="Vérification Dofus validée")
                    reports.append(f"Rôle retiré : {unverified_role.mention}.")
                except discord.DiscordException as exc:
                    logger.warning("Retrait rôle à vérifier échoué: %s", exc)
                    reports.append("Rôle à vérifier non retiré : permission Discord insuffisante.")

        current_nick = getattr(member, "nick", None) or getattr(member, "display_name", None)
        if current_nick != main_name:
            try:
                await member.edit(nick=main_name, reason="Pseudo main Dofus vérifié")
                reports.append(f"Pseudo Discord renommé en **{main_name}**.")
            except discord.DiscordException as exc:
                logger.warning("Renommage membre vérifié échoué: %s", exc)
                reports.append("Pseudo Discord non modifié : permission Discord insuffisante.")

        return "\n".join(reports)

    async def _revert_verified_member_updates(
        self,
        guild: discord.Guild,
        member: discord.Member,
    ) -> str:
        reports: list[str] = []

        verified_role_id = db.get_guild_setting_int(guild.id, db.SETTING_VERIFIED_MEMBER_ROLE)
        if verified_role_id:
            verified_role = guild.get_role(verified_role_id)
            if verified_role is not None and verified_role in getattr(member, "roles", []):
                try:
                    await member.remove_roles(verified_role, reason="Vérification Dofus supprimée")
                    reports.append(f"Rôle retiré : {verified_role.mention}.")
                except discord.DiscordException as exc:
                    logger.warning("Retrait rôle vérifié échoué: %s", exc)
                    reports.append("Rôle membre non retiré : permission Discord insuffisante.")

        unverified_role_id = db.get_guild_setting_int(guild.id, db.SETTING_UNVERIFIED_MEMBER_ROLE)
        if unverified_role_id:
            unverified_role = guild.get_role(unverified_role_id)
            if unverified_role is not None:
                try:
                    await member.add_roles(unverified_role, reason="Vérification Dofus supprimée")
                    reports.append(f"Rôle attribué : {unverified_role.mention}.")
                except discord.DiscordException as exc:
                    logger.warning("Attribution rôle à vérifier échouée: %s", exc)
                    reports.append("Rôle à vérifier non attribué : permission Discord insuffisante.")

        if getattr(member, "nick", None):
            try:
                await member.edit(nick=None, reason="Vérification Dofus supprimée")
                reports.append("Pseudo Discord réinitialisé.")
            except discord.DiscordException as exc:
                logger.warning("Réinitialisation pseudo vérifié échouée: %s", exc)
                reports.append("Pseudo Discord non modifié : permission Discord insuffisante.")

        return "\n".join(reports) if reports else "Aucun rôle ou pseudo à modifier."

    async def _delete_later(self, channel: discord.abc.Messageable, reason: str) -> None:
        await asyncio.sleep(120)
        delete = getattr(channel, "delete", None)
        if delete is None:
            return
        try:
            await delete(reason=reason)
        except discord.DiscordException as exc:
            logger.warning("Suppression salon vérification échouée: %s", exc)


def datetime_from_iso(value: str):
    from datetime import datetime

    return datetime.fromisoformat(value)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VerificationCog(bot))
