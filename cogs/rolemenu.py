"""Menus de rôles configurables par boutons et menus select."""
from __future__ import annotations

import json
import logging
import math
import re
from typing import Any, Iterable, Optional

import discord
from discord import app_commands
from discord.ext import commands

import db
from utils.perms import is_bot_admin

logger = logging.getLogger("beb-raid.rolemenu")

DEFAULT_COLOR = 0x2ECC71
MAX_ACTION_ROWS = 5
MAX_SELECT_OPTIONS = 25
BUTTON_STYLES = {
    "primary": discord.ButtonStyle.primary,
    "secondary": discord.ButtonStyle.secondary,
    "success": discord.ButtonStyle.success,
    "danger": discord.ButtonStyle.danger,
}


def _clean_text(value: Optional[str], *, max_len: int) -> Optional[str]:
    value = (value or "").strip()
    if not value:
        return None
    return value[:max_len]


def _parse_color(value: Optional[str]) -> int:
    raw = (value or "").strip()
    if not raw:
        return DEFAULT_COLOR
    raw = raw.removeprefix("#").removeprefix("0x")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", raw):
        raise ValueError("Couleur invalide. Utilise un hex du type #2ecc71.")
    return int(raw, 16)


def _style_name(value: Optional[str]) -> str:
    raw = (value or "secondary").strip().lower()
    if raw not in BUTTON_STYLES:
        raise ValueError("Style invalide. Choix: primary, secondary, success, danger.")
    return raw


def _component_rows(components: Iterable[discord.ui.Item]) -> int:
    buttons = 0
    selects = 0
    for component in components:
        if isinstance(component, discord.ui.Button):
            buttons += 1
        else:
            selects += 1
    return selects + math.ceil(buttons / 5)


def _extract_role_id(value: Any) -> Optional[int]:
    raw = str(value or "").strip()
    match = re.fullmatch(r"<@&(\d+)>|(\d+)", raw)
    if match:
        return int(match.group(1) or match.group(2))
    return None


def _resolve_role_ref(guild: discord.Guild, value: Any) -> Optional[discord.Role]:
    role_id = _extract_role_id(value)
    if role_id is not None:
        return guild.get_role(role_id)
    normalized = str(value or "").strip().lstrip("@").casefold()
    matches = [role for role in guild.roles if role.name.casefold() == normalized]
    return matches[0] if len(matches) == 1 else None


def _role_is_assignable(guild: discord.Guild, role: discord.Role) -> tuple[bool, str]:
    if role.is_default():
        return False, "le rôle @everyone ne peut pas être attribué"
    if role.managed:
        return False, "ce rôle est géré par une intégration"
    me = guild.me
    if me is not None and role >= me.top_role:
        return False, "ce rôle est au-dessus ou au même niveau que le rôle du bot"
    return True, ""


def _build_embed(menu: Any) -> discord.Embed:
    embed = discord.Embed(
        title=menu["title"],
        description=menu["description"] or None,
        color=menu["color"] if menu["color"] is not None else DEFAULT_COLOR,
    )
    if menu["footer"]:
        embed.set_footer(text=menu["footer"])
    if menu["image_url"]:
        embed.set_image(url=menu["image_url"])
    if menu["thumbnail_url"]:
        embed.set_thumbnail(url=menu["thumbnail_url"])
    return embed


class _RoleButton(discord.ui.Button):
    def __init__(self, cog: "RoleMenuCog", component: Any, row: int):
        style = BUTTON_STYLES.get(component["style"] or "secondary", discord.ButtonStyle.secondary)
        super().__init__(
            label=component["label"],
            style=style,
            emoji=component["emoji"] or None,
            custom_id=f"bebraid:rolebtn:{component['id']}",
            row=row,
        )
        self.cog = cog
        self.component_id = component["id"]

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.handle_button(interaction, self.component_id)


class _RoleSelect(discord.ui.Select):
    def __init__(self, cog: "RoleMenuCog", component: Any, options: list[Any], row: int):
        discord_options = [
            discord.SelectOption(
                label=option["label"],
                value=str(option["role_id"]),
                description=option["description"] or None,
                emoji=option["emoji"] or None,
            )
            for option in options
        ]
        max_values = max(1, min(component["max_values"], len(discord_options)))
        min_values = min(max(component["min_values"], 0), max_values)
        super().__init__(
            placeholder=component["placeholder"] or "Choisis tes rôles",
            min_values=min_values,
            max_values=max_values,
            options=discord_options,
            custom_id=f"bebraid:rolesel:{component['id']}",
            row=row,
        )
        self.cog = cog
        self.component_id = component["id"]

    async def callback(self, interaction: discord.Interaction) -> None:
        role_ids = [int(value) for value in self.values if value.isdigit()]
        await self.cog.handle_select(interaction, self.component_id, role_ids)


class RoleMenuView(discord.ui.View):
    def __init__(self, cog: "RoleMenuCog", menu: Any):
        super().__init__(timeout=None)
        self.cog = cog
        components = db.list_role_menu_components(menu["id"])
        selects = [component for component in components if component["component_type"] == "select"]
        buttons = [component for component in components if component["component_type"] == "button"]

        row = 0
        for component in selects:
            if row >= MAX_ACTION_ROWS:
                break
            options = db.list_role_menu_options(component["id"])
            if not options:
                continue
            self.add_item(_RoleSelect(cog, component, options, row))
            row += 1

        button_row = row
        button_count = 0
        for component in buttons:
            if button_row >= MAX_ACTION_ROWS:
                break
            self.add_item(_RoleButton(cog, component, button_row))
            button_count += 1
            if button_count % 5 == 0:
                button_row += 1


class RoleMenuCog(commands.Cog):
    rolemenu = app_commands.Group(
        name="rolemenu",
        description="Crée et configure des menus de rôles",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        db.init()
        loaded = 0
        for menu in db.list_role_menus():
            if menu["message_id"]:
                view = self._view_or_none(menu)
                if view is not None:
                    self.bot.add_view(view, message_id=menu["message_id"])
                    loaded += 1
        logger.info("RoleMenuCog prêt, %d menu(s) persistant(s) rechargé(s)", loaded)

    def _view_or_none(self, menu: Any) -> Optional[RoleMenuView]:
        view = RoleMenuView(self, menu)
        return view if view.children else None

    async def _require_admin(self, interaction: discord.Interaction) -> bool:
        if is_bot_admin(interaction):
            return True
        await interaction.response.send_message("Permission refusée.", ephemeral=True)
        return False

    async def _get_menu_for_admin(self, interaction: discord.Interaction, menu_id: int) -> Optional[Any]:
        if not await self._require_admin(interaction):
            return None
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return None
        menu = db.get_role_menu(menu_id)
        if menu is None or menu["guild_id"] != interaction.guild.id:
            await interaction.response.send_message("Menu introuvable sur ce serveur.", ephemeral=True)
            return None
        return menu

    async def _fetch_menu_message(self, menu: Any) -> Optional[discord.Message]:
        channel = self.bot.get_channel(menu["channel_id"])
        if channel is None:
            channel = await self.bot.fetch_channel(menu["channel_id"])
        if not isinstance(channel, discord.abc.Messageable) or not menu["message_id"]:
            return None
        return await channel.fetch_message(menu["message_id"])

    async def _refresh_menu(self, menu_id: int) -> None:
        menu = db.get_role_menu(menu_id)
        if menu is None:
            return
        message = await self._fetch_menu_message(menu)
        if message is None:
            return
        view = self._view_or_none(menu)
        await message.edit(embed=_build_embed(menu), view=view)

    def _configured_row_count(self, menu_id: int, *, extra_button: int = 0, extra_select: int = 0) -> int:
        components = db.list_role_menu_components(menu_id)
        buttons = len([c for c in components if c["component_type"] == "button"]) + extra_button
        selects = len([c for c in components if c["component_type"] == "select"]) + extra_select
        return selects + math.ceil(buttons / 5)

    async def _send_result(
        self,
        interaction: discord.Interaction,
        added: list[str],
        removed: list[str],
        skipped: list[str],
    ) -> None:
        parts: list[str] = []
        if added:
            parts.append(f"✅ Ajouté : {', '.join(added)}")
        if removed:
            parts.append(f"➖ Retiré : {', '.join(removed)}")
        if skipped:
            parts.append(f"⚠️ Ignoré : {'; '.join(skipped)}")
        if not parts:
            parts.append("Aucun changement.")
        await interaction.response.send_message("\n".join(parts), ephemeral=True)

    async def _apply_roles(
        self,
        interaction: discord.Interaction,
        *,
        component: Any,
        selected_role_ids: list[int],
        toggle: bool,
    ) -> None:
        guild = interaction.guild
        if guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        member = interaction.user
        if not isinstance(member, discord.Member):
            member = await guild.fetch_member(interaction.user.id)

        added: list[str] = []
        removed: list[str] = []
        skipped: list[str] = []
        selected = set(selected_role_ids)
        roles_by_id = {role.id: role for role in guild.roles}

        if component["exclusive"]:
            if component["component_type"] == "select":
                configured_ids = {option["role_id"] for option in db.list_role_menu_options(component["id"])}
            else:
                menu_components = db.list_role_menu_components(component["menu_id"])
                configured_ids = {
                    c["role_id"]
                    for c in menu_components
                    if c["component_type"] == "button" and c["role_id"]
                }
                for c in menu_components:
                    if c["component_type"] == "select":
                        configured_ids.update(
                            option["role_id"] for option in db.list_role_menu_options(c["id"])
                        )
            for role_id in sorted(configured_ids - selected):
                role = roles_by_id.get(role_id)
                if role is not None and role in member.roles:
                    ok, reason = _role_is_assignable(guild, role)
                    if not ok:
                        skipped.append(f"{role.mention} ({reason})")
                        continue
                    await member.remove_roles(role, reason="Menu de rôles Beb Raid")
                    removed.append(role.mention)

        for role_id in selected_role_ids:
            role = roles_by_id.get(role_id)
            if role is None:
                skipped.append(f"rôle {role_id} introuvable")
                continue
            ok, reason = _role_is_assignable(guild, role)
            if not ok:
                skipped.append(f"{role.mention} ({reason})")
                continue
            if toggle and role in member.roles:
                await member.remove_roles(role, reason="Menu de rôles Beb Raid")
                removed.append(role.mention)
            elif role not in member.roles:
                await member.add_roles(role, reason="Menu de rôles Beb Raid")
                added.append(role.mention)

        await self._send_result(interaction, added, removed, skipped)

    async def handle_button(self, interaction: discord.Interaction, component_id: int) -> None:
        component = db.get_role_menu_component(component_id)
        if component is None or component["component_type"] != "button" or not component["role_id"]:
            await interaction.response.send_message("Ce bouton n'est plus configuré.", ephemeral=True)
            return
        await self._apply_roles(
            interaction,
            component=component,
            selected_role_ids=[component["role_id"]],
            toggle=True,
        )

    async def handle_select(
        self,
        interaction: discord.Interaction,
        component_id: int,
        role_ids: list[int],
    ) -> None:
        component = db.get_role_menu_component(component_id)
        if component is None or component["component_type"] != "select":
            await interaction.response.send_message("Ce menu n'est plus configuré.", ephemeral=True)
            return
        configured = {option["role_id"] for option in db.list_role_menu_options(component_id)}
        selected = [role_id for role_id in role_ids if role_id in configured]
        await self._apply_roles(
            interaction,
            component=component,
            selected_role_ids=selected,
            toggle=not bool(component["exclusive"]),
        )

    @rolemenu.command(name="create", description="Publie un nouveau menu de rôles")
    @app_commands.describe(
        channel="Salon où poster le menu",
        titre="Titre de l'embed",
        description="Texte de l'embed",
        couleur="Couleur hex, ex: #2ecc71",
        footer="Footer de l'embed",
        image="URL d'image principale",
        thumbnail="URL de miniature",
    )
    async def create(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        titre: str,
        description: Optional[str] = None,
        couleur: Optional[str] = None,
        footer: Optional[str] = None,
        image: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> None:
        if not await self._require_admin(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        try:
            color = _parse_color(couleur)
        except ValueError as exc:
            await interaction.response.send_message(str(exc), ephemeral=True)
            return

        menu_id = db.create_role_menu(
            guild_id=interaction.guild.id,
            channel_id=channel.id,
            title=_clean_text(titre, max_len=256) or "Rôles",
            description=_clean_text(description, max_len=4096),
            color=color,
            footer=_clean_text(footer, max_len=2048),
            image_url=_clean_text(image, max_len=2048),
            thumbnail_url=_clean_text(thumbnail, max_len=2048),
            created_by=interaction.user.id,
        )
        menu = db.get_role_menu(menu_id)
        message = await channel.send(embed=_build_embed(menu))
        db.update_role_menu(menu_id, message_id=message.id)
        await interaction.response.send_message(
            f"✅ Menu de rôles **#{menu_id}** créé dans {channel.mention}. "
            "Ajoute des boutons ou selects avec les commandes `/rolemenu`.",
            ephemeral=True,
        )

    @rolemenu.command(name="edit_embed", description="Modifie l'embed d'un menu de rôles")
    @app_commands.describe(
        menu_id="ID du menu",
        titre="Nouveau titre",
        description="Nouvelle description",
        couleur="Couleur hex, ex: #5865f2",
        footer="Footer",
        image="URL d'image principale",
        thumbnail="URL de miniature",
    )
    async def edit_embed(
        self,
        interaction: discord.Interaction,
        menu_id: int,
        titre: Optional[str] = None,
        description: Optional[str] = None,
        couleur: Optional[str] = None,
        footer: Optional[str] = None,
        image: Optional[str] = None,
        thumbnail: Optional[str] = None,
    ) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None:
            return
        fields: dict[str, Any] = {}
        if titre is not None:
            fields["title"] = _clean_text(titre, max_len=256) or "Rôles"
        if description is not None:
            fields["description"] = _clean_text(description, max_len=4096)
        if couleur is not None:
            try:
                fields["color"] = _parse_color(couleur)
            except ValueError as exc:
                await interaction.response.send_message(str(exc), ephemeral=True)
                return
        if footer is not None:
            fields["footer"] = _clean_text(footer, max_len=2048)
        if image is not None:
            fields["image_url"] = _clean_text(image, max_len=2048)
        if thumbnail is not None:
            fields["thumbnail_url"] = _clean_text(thumbnail, max_len=2048)
        db.update_role_menu(menu_id, **fields)
        await self._refresh_menu(menu_id)
        await interaction.response.send_message(f"✅ Embed du menu **#{menu_id}** mis à jour.", ephemeral=True)

    @rolemenu.command(name="add_button", description="Ajoute un bouton de rôle")
    @app_commands.describe(
        menu_id="ID du menu",
        role="Rôle à ajouter/retirer",
        label="Texte du bouton (vide = nom du rôle)",
        emoji="Emoji du bouton",
        style="primary, secondary, success ou danger",
        exclusive="Retire les autres rôles configurés sur ce menu avant d'ajouter celui-ci",
    )
    @app_commands.choices(
        style=[
            app_commands.Choice(name="primary", value="primary"),
            app_commands.Choice(name="secondary", value="secondary"),
            app_commands.Choice(name="success", value="success"),
            app_commands.Choice(name="danger", value="danger"),
        ]
    )
    async def add_button(
        self,
        interaction: discord.Interaction,
        menu_id: int,
        role: discord.Role,
        label: Optional[str] = None,
        emoji: Optional[str] = None,
        style: app_commands.Choice[str] = None,
        exclusive: bool = False,
    ) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None or interaction.guild is None:
            return
        if self._configured_row_count(menu_id, extra_button=1) > MAX_ACTION_ROWS:
            await interaction.response.send_message("Limite Discord atteinte: 5 lignes de composants maximum.", ephemeral=True)
            return
        ok, reason = _role_is_assignable(interaction.guild, role)
        if not ok:
            await interaction.response.send_message(f"Impossible d'utiliser {role.mention}: {reason}.", ephemeral=True)
            return
        style_value = style.value if style else "secondary"
        db.add_role_menu_component(
            menu_id=menu_id,
            component_type="button",
            label=_clean_text(label, max_len=80) or role.name[:80],
            emoji=_clean_text(emoji, max_len=80),
            style=_style_name(style_value),
            role_id=role.id,
            exclusive=exclusive,
        )
        await self._refresh_menu(menu_id)
        await interaction.response.send_message(f"✅ Bouton ajouté pour {role.mention}.", ephemeral=True)

    @rolemenu.command(name="add_select", description="Ajoute un menu select vide")
    @app_commands.describe(
        menu_id="ID du menu",
        placeholder="Texte affiché dans le select",
        min_values="Nombre minimum de choix (0 pour pouvoir vider)",
        max_values="Nombre maximum de choix",
        exclusive="Retire les rôles non sélectionnés dans ce select",
    )
    async def add_select(
        self,
        interaction: discord.Interaction,
        menu_id: int,
        placeholder: str,
        min_values: int = 0,
        max_values: int = 1,
        exclusive: bool = False,
    ) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None:
            return
        if self._configured_row_count(menu_id, extra_select=1) > MAX_ACTION_ROWS:
            await interaction.response.send_message("Limite Discord atteinte: 5 lignes de composants maximum.", ephemeral=True)
            return
        if not 0 <= min_values <= max_values <= MAX_SELECT_OPTIONS:
            await interaction.response.send_message("Valeurs invalides: utilise 0 <= min <= max <= 25.", ephemeral=True)
            return
        component_id = db.add_role_menu_component(
            menu_id=menu_id,
            component_type="select",
            placeholder=_clean_text(placeholder, max_len=150) or "Choisis tes rôles",
            min_values=min_values,
            max_values=max_values,
            exclusive=exclusive,
        )
        await self._refresh_menu(menu_id)
        await interaction.response.send_message(
            f"✅ Select **#{component_id}** ajouté. Ajoute ses rôles avec `/rolemenu add_option`.",
            ephemeral=True,
        )

    @rolemenu.command(name="add_option", description="Ajoute un rôle dans un select")
    @app_commands.describe(
        select_id="ID du select",
        role="Rôle proposé",
        label="Libellé affiché (vide = nom du rôle)",
        description="Description courte de l'option",
        emoji="Emoji de l'option",
    )
    async def add_option(
        self,
        interaction: discord.Interaction,
        select_id: int,
        role: discord.Role,
        label: Optional[str] = None,
        description: Optional[str] = None,
        emoji: Optional[str] = None,
    ) -> None:
        component = db.get_role_menu_component(select_id)
        if component is None or component["component_type"] != "select":
            await interaction.response.send_message("Select introuvable.", ephemeral=True)
            return
        menu = await self._get_menu_for_admin(interaction, component["menu_id"])
        if menu is None or interaction.guild is None:
            return
        options = db.list_role_menu_options(select_id)
        if len(options) >= MAX_SELECT_OPTIONS and all(option["role_id"] != role.id for option in options):
            await interaction.response.send_message("Ce select a déjà 25 options, limite Discord atteinte.", ephemeral=True)
            return
        ok, reason = _role_is_assignable(interaction.guild, role)
        if not ok:
            await interaction.response.send_message(f"Impossible d'utiliser {role.mention}: {reason}.", ephemeral=True)
            return
        db.add_role_menu_option(
            component_id=select_id,
            role_id=role.id,
            label=_clean_text(label, max_len=100) or role.name[:100],
            description=_clean_text(description, max_len=100),
            emoji=_clean_text(emoji, max_len=80),
        )
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(f"✅ Option ajoutée pour {role.mention}.", ephemeral=True)

    @rolemenu.command(name="remove_component", description="Supprime un bouton ou un select")
    async def remove_component(self, interaction: discord.Interaction, component_id: int) -> None:
        component = db.get_role_menu_component(component_id)
        if component is None:
            await interaction.response.send_message("Composant introuvable.", ephemeral=True)
            return
        menu = await self._get_menu_for_admin(interaction, component["menu_id"])
        if menu is None:
            return
        db.delete_role_menu_component(component_id)
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(f"✅ Composant **#{component_id}** supprimé.", ephemeral=True)

    @rolemenu.command(name="remove_option", description="Supprime une option d'un select")
    async def remove_option(self, interaction: discord.Interaction, option_id: int) -> None:
        option = db.get_role_menu_option(option_id)
        if option is None:
            await interaction.response.send_message("Option introuvable.", ephemeral=True)
            return
        component = db.get_role_menu_component(option["component_id"])
        if component is None:
            await interaction.response.send_message("Select introuvable.", ephemeral=True)
            return
        menu = await self._get_menu_for_admin(interaction, component["menu_id"])
        if menu is None:
            return
        db.delete_role_menu_option(option_id)
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(f"✅ Option **#{option_id}** supprimée.", ephemeral=True)

    @rolemenu.command(name="refresh", description="Reposte la vue Discord d'un menu")
    async def refresh(self, interaction: discord.Interaction, menu_id: int) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None:
            return
        await self._refresh_menu(menu_id)
        await interaction.response.send_message(f"✅ Menu **#{menu_id}** rafraîchi.", ephemeral=True)

    @rolemenu.command(name="list", description="Liste les menus de rôles du serveur")
    async def list_menus(self, interaction: discord.Interaction) -> None:
        if not await self._require_admin(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        menus = db.list_role_menus(interaction.guild.id)
        if not menus:
            await interaction.response.send_message("Aucun menu de rôles configuré.", ephemeral=True)
            return
        lines = []
        for menu in menus[:20]:
            lines.append(
                f"#{menu['id']} · <#{menu['channel_id']}> · message `{menu['message_id'] or 'non posté'}` · {menu['title']}"
            )
        await interaction.response.send_message("\n".join(lines), ephemeral=True)

    @rolemenu.command(name="import_config", description="Crée un menu complet depuis une configuration JSON")
    @app_commands.describe(
        channel="Salon où poster le menu",
        configuration="JSON contenant embed et components",
    )
    async def import_config(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
        configuration: str,
    ) -> None:
        if not await self._require_admin(interaction):
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        try:
            payload = json.loads(configuration)
            embed_conf = payload.get("embed", {})
            components_conf = payload.get("components", [])
            color = _parse_color(embed_conf.get("color"))
        except (TypeError, json.JSONDecodeError, ValueError) as exc:
            await interaction.response.send_message(f"Configuration invalide: {exc}", ephemeral=True)
            return
        if not isinstance(components_conf, list):
            await interaction.response.send_message("`components` doit être une liste.", ephemeral=True)
            return

        prepared: list[dict[str, Any]] = []
        row_count = 0
        button_count = 0
        for component in components_conf:
            if not isinstance(component, dict):
                await interaction.response.send_message("Chaque composant doit être un objet JSON.", ephemeral=True)
                return
            component_type = str(component.get("type", "")).lower()
            if component_type == "button":
                role = _resolve_role_ref(interaction.guild, component.get("role"))
                if role is None:
                    await interaction.response.send_message(f"Rôle introuvable: {component.get('role')}", ephemeral=True)
                    return
                try:
                    _style_name(component.get("style"))
                except ValueError as exc:
                    await interaction.response.send_message(str(exc), ephemeral=True)
                    return
                ok, reason = _role_is_assignable(interaction.guild, role)
                if not ok:
                    await interaction.response.send_message(f"Impossible d'utiliser {role.mention}: {reason}.", ephemeral=True)
                    return
                button_count += 1
                prepared.append({"type": "button", "role": role, "data": component})
            elif component_type == "select":
                try:
                    min_values = int(component.get("min", 0))
                    max_values = int(component.get("max", 1))
                except (TypeError, ValueError):
                    await interaction.response.send_message("Valeurs min/max invalides dans un select.", ephemeral=True)
                    return
                if not 0 <= min_values <= max_values <= MAX_SELECT_OPTIONS:
                    await interaction.response.send_message("Valeurs min/max invalides dans un select.", ephemeral=True)
                    return
                options = component.get("options", [])
                if not isinstance(options, list) or not options:
                    await interaction.response.send_message("Chaque select doit avoir au moins une option.", ephemeral=True)
                    return
                if len(options) > MAX_SELECT_OPTIONS:
                    await interaction.response.send_message("Un select ne peut pas dépasser 25 options.", ephemeral=True)
                    return
                prepared_options = []
                for option in options:
                    role = _resolve_role_ref(interaction.guild, option.get("role") if isinstance(option, dict) else None)
                    if role is None:
                        await interaction.response.send_message(f"Rôle introuvable dans un select: {option}", ephemeral=True)
                        return
                    ok, reason = _role_is_assignable(interaction.guild, role)
                    if not ok:
                        await interaction.response.send_message(f"Impossible d'utiliser {role.mention}: {reason}.", ephemeral=True)
                        return
                    prepared_options.append((role, option))
                row_count += 1
                prepared.append({
                    "type": "select",
                    "options": prepared_options,
                    "data": component,
                    "min": min_values,
                    "max": max_values,
                })
            else:
                await interaction.response.send_message("Type de composant invalide: utilise button ou select.", ephemeral=True)
                return

        if row_count + math.ceil(button_count / 5) > MAX_ACTION_ROWS:
            await interaction.response.send_message("Limite Discord atteinte: 5 lignes de composants maximum.", ephemeral=True)
            return

        menu_id = db.create_role_menu(
            guild_id=interaction.guild.id,
            channel_id=channel.id,
            title=_clean_text(embed_conf.get("title"), max_len=256) or "Rôles",
            description=_clean_text(embed_conf.get("description"), max_len=4096),
            color=color,
            footer=_clean_text(embed_conf.get("footer"), max_len=2048),
            image_url=_clean_text(embed_conf.get("image"), max_len=2048),
            thumbnail_url=_clean_text(embed_conf.get("thumbnail"), max_len=2048),
            created_by=interaction.user.id,
        )
        for component in prepared:
            data = component["data"]
            if component["type"] == "button":
                role = component["role"]
                db.add_role_menu_component(
                    menu_id=menu_id,
                    component_type="button",
                    label=_clean_text(data.get("label"), max_len=80) or role.name[:80],
                    emoji=_clean_text(data.get("emoji"), max_len=80),
                    style=_style_name(data.get("style")),
                    role_id=role.id,
                    exclusive=bool(data.get("exclusive")),
                )
            else:
                component_id = db.add_role_menu_component(
                    menu_id=menu_id,
                    component_type="select",
                    placeholder=_clean_text(data.get("placeholder"), max_len=150) or "Choisis tes rôles",
                    min_values=component["min"],
                    max_values=component["max"],
                    exclusive=bool(data.get("exclusive")),
                )
                for role, option in component["options"]:
                    db.add_role_menu_option(
                        component_id=component_id,
                        role_id=role.id,
                        label=_clean_text(option.get("label"), max_len=100) or role.name[:100],
                        description=_clean_text(option.get("description"), max_len=100),
                        emoji=_clean_text(option.get("emoji"), max_len=80),
                    )

        menu = db.get_role_menu(menu_id)
        message = await channel.send(embed=_build_embed(menu), view=self._view_or_none(menu))
        db.update_role_menu(menu_id, message_id=message.id)
        await interaction.response.send_message(f"✅ Menu de rôles **#{menu_id}** importé dans {channel.mention}.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RoleMenuCog(bot))
