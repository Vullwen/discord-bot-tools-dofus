"""Menus de rôles configurables par boutons et menus select."""
from __future__ import annotations

import io
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


def _clean_multiline_text(value: Optional[str], *, max_len: int) -> Optional[str]:
    value = (value or "").replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\\n", "\n").replace("\\t", "    ")
    value = value.strip("\n")
    if not value.strip():
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


def _role_id_text(role_id: Optional[int]) -> Optional[str]:
    return str(role_id) if role_id else None


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


class EmbedDescriptionModal(discord.ui.Modal):
    def __init__(self, cog: "RoleMenuCog", menu: Any):
        super().__init__(title=f"Description menu #{menu['id']}")
        self.cog = cog
        self.menu_id = menu["id"]
        self.description_input = discord.ui.TextInput(
            label="Description de l'embed",
            style=discord.TextStyle.paragraph,
            default=menu["description"] or "",
            required=False,
            max_length=4000,
            placeholder="Tu peux utiliser des retours à la ligne, indentation, listes, etc.",
        )
        self.add_item(self.description_input)

    async def on_submit(self, interaction: discord.Interaction) -> None:
        menu = await self.cog._get_menu_for_admin(interaction, self.menu_id)
        if menu is None:
            return
        db.update_role_menu(
            self.menu_id,
            description=_clean_multiline_text(self.description_input.value, max_len=4096),
        )
        await self.cog._refresh_menu(self.menu_id)
        await interaction.response.send_message(
            f"✅ Description du menu **#{self.menu_id}** mise à jour.",
            ephemeral=True,
        )


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

    def _export_payload(self, menu: Any) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "embed": {
                "title": menu["title"],
                "description": menu["description"] or "",
                "color": f"#{(menu['color'] if menu['color'] is not None else DEFAULT_COLOR):06x}",
            },
            "components": [],
        }
        if menu["footer"]:
            payload["embed"]["footer"] = menu["footer"]
        if menu["image_url"]:
            payload["embed"]["image"] = menu["image_url"]
        if menu["thumbnail_url"]:
            payload["embed"]["thumbnail"] = menu["thumbnail_url"]

        for component in db.list_role_menu_components(menu["id"]):
            if component["component_type"] == "button":
                item = {
                    "type": "button",
                    "role": _role_id_text(component["role_id"]),
                    "label": component["label"],
                    "style": component["style"] or "secondary",
                }
                if component["emoji"]:
                    item["emoji"] = component["emoji"]
                if component["exclusive"]:
                    item["exclusive"] = True
                payload["components"].append(item)
                continue

            item = {
                "type": "select",
                "placeholder": component["placeholder"] or "Choisis tes rôles",
                "min": component["min_values"],
                "max": component["max_values"],
                "options": [],
            }
            if component["exclusive"]:
                item["exclusive"] = True
            for option in db.list_role_menu_options(component["id"]):
                option_item = {
                    "role": str(option["role_id"]),
                    "label": option["label"],
                }
                if option["description"]:
                    option_item["description"] = option["description"]
                if option["emoji"]:
                    option_item["emoji"] = option["emoji"]
                item["options"].append(option_item)
            payload["components"].append(item)

        return payload

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
            description=_clean_multiline_text(description, max_len=4096),
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
            fields["description"] = _clean_multiline_text(description, max_len=4096)
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

    @rolemenu.command(name="edit_description", description="Ouvre un éditeur multiline pour la description")
    @app_commands.describe(menu_id="ID du menu")
    async def edit_description(self, interaction: discord.Interaction, menu_id: int) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None:
            return
        await interaction.response.send_modal(EmbedDescriptionModal(self, menu))

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
        button_id = db.add_role_menu_component(
            menu_id=menu_id,
            component_type="button",
            label=_clean_text(label, max_len=80) or role.name[:80],
            emoji=_clean_text(emoji, max_len=80),
            style=_style_name(style_value),
            role_id=role.id,
            exclusive=exclusive,
        )
        await self._refresh_menu(menu_id)
        await interaction.response.send_message(
            f"✅ Bouton **#{button_id}** ajouté pour {role.mention}.",
            ephemeral=True,
        )

    @rolemenu.command(name="edit_button", description="Modifie un bouton de rôle")
    @app_commands.describe(
        button_id="ID du bouton",
        role="Nouveau rôle à ajouter/retirer",
        label="Nouveau texte du bouton",
        emoji="Nouvel emoji du bouton",
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
    async def edit_button(
        self,
        interaction: discord.Interaction,
        button_id: int,
        role: Optional[discord.Role] = None,
        label: Optional[str] = None,
        emoji: Optional[str] = None,
        style: Optional[app_commands.Choice[str]] = None,
        exclusive: Optional[bool] = None,
    ) -> None:
        component = db.get_role_menu_component(button_id)
        if component is None or component["component_type"] != "button":
            await interaction.response.send_message("Bouton introuvable.", ephemeral=True)
            return
        menu = await self._get_menu_for_admin(interaction, component["menu_id"])
        if menu is None or interaction.guild is None:
            return

        fields: dict[str, Any] = {}
        if role is not None:
            ok, reason = _role_is_assignable(interaction.guild, role)
            if not ok:
                await interaction.response.send_message(f"Impossible d'utiliser {role.mention}: {reason}.", ephemeral=True)
                return
            fields["role_id"] = role.id
            if label is None:
                fields["label"] = role.name[:80]
        if label is not None:
            fields["label"] = _clean_text(label, max_len=80) or component["label"]
        if emoji is not None:
            fields["emoji"] = _clean_text(emoji, max_len=80)
        if style is not None:
            fields["style"] = _style_name(style.value)
        if exclusive is not None:
            fields["exclusive"] = 1 if exclusive else 0
        db.update_role_menu_component(button_id, **fields)
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(f"✅ Bouton **#{button_id}** mis à jour.", ephemeral=True)

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

    @rolemenu.command(name="edit_select", description="Modifie un menu select")
    @app_commands.describe(
        select_id="ID du select",
        placeholder="Nouveau texte affiché dans le select",
        min_values="Nouveau nombre minimum de choix",
        max_values="Nouveau nombre maximum de choix",
        exclusive="Retire les rôles non sélectionnés dans ce select",
    )
    async def edit_select(
        self,
        interaction: discord.Interaction,
        select_id: int,
        placeholder: Optional[str] = None,
        min_values: Optional[int] = None,
        max_values: Optional[int] = None,
        exclusive: Optional[bool] = None,
    ) -> None:
        component = db.get_role_menu_component(select_id)
        if component is None or component["component_type"] != "select":
            await interaction.response.send_message("Select introuvable.", ephemeral=True)
            return
        menu = await self._get_menu_for_admin(interaction, component["menu_id"])
        if menu is None:
            return

        next_min = component["min_values"] if min_values is None else min_values
        next_max = component["max_values"] if max_values is None else max_values
        if not 0 <= next_min <= next_max <= MAX_SELECT_OPTIONS:
            await interaction.response.send_message("Valeurs invalides: utilise 0 <= min <= max <= 25.", ephemeral=True)
            return

        fields: dict[str, Any] = {}
        if placeholder is not None:
            fields["placeholder"] = _clean_text(placeholder, max_len=150) or component["placeholder"]
        if min_values is not None:
            fields["min_values"] = min_values
        if max_values is not None:
            fields["max_values"] = max_values
        if exclusive is not None:
            fields["exclusive"] = 1 if exclusive else 0
        db.update_role_menu_component(select_id, **fields)
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(f"✅ Select **#{select_id}** mis à jour.", ephemeral=True)

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
        option_id = db.add_role_menu_option(
            component_id=select_id,
            role_id=role.id,
            label=_clean_text(label, max_len=100) or role.name[:100],
            description=_clean_text(description, max_len=100),
            emoji=_clean_text(emoji, max_len=80),
        )
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(
            f"✅ Option **#{option_id}** ajoutée pour {role.mention}.",
            ephemeral=True,
        )

    @rolemenu.command(name="edit_option", description="Modifie une option d'un select")
    @app_commands.describe(
        option_id="ID de l'option",
        role="Nouveau rôle proposé",
        label="Nouveau libellé affiché",
        description="Nouvelle description courte",
        emoji="Nouvel emoji",
    )
    async def edit_option(
        self,
        interaction: discord.Interaction,
        option_id: int,
        role: Optional[discord.Role] = None,
        label: Optional[str] = None,
        description: Optional[str] = None,
        emoji: Optional[str] = None,
    ) -> None:
        option = db.get_role_menu_option(option_id)
        if option is None:
            await interaction.response.send_message("Option introuvable.", ephemeral=True)
            return
        component = db.get_role_menu_component(option["component_id"])
        if component is None:
            await interaction.response.send_message("Select introuvable.", ephemeral=True)
            return
        menu = await self._get_menu_for_admin(interaction, component["menu_id"])
        if menu is None or interaction.guild is None:
            return

        fields: dict[str, Any] = {}
        if role is not None:
            ok, reason = _role_is_assignable(interaction.guild, role)
            if not ok:
                await interaction.response.send_message(f"Impossible d'utiliser {role.mention}: {reason}.", ephemeral=True)
                return
            fields["role_id"] = role.id
            if label is None:
                fields["label"] = role.name[:100]
        if label is not None:
            fields["label"] = _clean_text(label, max_len=100) or option["label"]
        if description is not None:
            fields["description"] = _clean_text(description, max_len=100)
        if emoji is not None:
            fields["emoji"] = _clean_text(emoji, max_len=80)
        db.update_role_menu_option(option_id, **fields)
        await self._refresh_menu(component["menu_id"])
        await interaction.response.send_message(f"✅ Option **#{option_id}** mise à jour.", ephemeral=True)

    @rolemenu.command(name="move_option", description="Déplace une option vers un autre select du même menu")
    @app_commands.describe(
        option_id="ID de l'option à déplacer",
        select_id="ID du select de destination",
    )
    async def move_option(
        self,
        interaction: discord.Interaction,
        option_id: int,
        select_id: int,
    ) -> None:
        option = db.get_role_menu_option(option_id)
        if option is None:
            await interaction.response.send_message("Option introuvable.", ephemeral=True)
            return
        source = db.get_role_menu_component(option["component_id"])
        target = db.get_role_menu_component(select_id)
        if source is None or source["component_type"] != "select":
            await interaction.response.send_message("Select source introuvable.", ephemeral=True)
            return
        if target is None or target["component_type"] != "select":
            await interaction.response.send_message("Select destination introuvable.", ephemeral=True)
            return
        if source["menu_id"] != target["menu_id"]:
            await interaction.response.send_message(
                "Déplacement refusé: les deux selects doivent appartenir au même menu.",
                ephemeral=True,
            )
            return
        menu = await self._get_menu_for_admin(interaction, source["menu_id"])
        if menu is None:
            return
        if source["id"] == target["id"]:
            await interaction.response.send_message("Cette option est déjà dans ce select.", ephemeral=True)
            return

        target_options = db.list_role_menu_options(target["id"])
        duplicate = next(
            (item for item in target_options if item["role_id"] == option["role_id"]),
            None,
        )
        if duplicate is not None:
            await interaction.response.send_message(
                f"Le select destination contient déjà une option pour ce rôle: **#{duplicate['id']}**.",
                ephemeral=True,
            )
            return
        if len(target_options) >= MAX_SELECT_OPTIONS:
            await interaction.response.send_message(
                "Le select destination a déjà 25 options, limite Discord atteinte.",
                ephemeral=True,
            )
            return

        db.update_role_menu_option(option_id, component_id=target["id"])
        await self._refresh_menu(source["menu_id"])
        await interaction.response.send_message(
            f"✅ Option **#{option_id}** déplacée vers le select **#{target['id']}**.",
            ephemeral=True,
        )

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

    @rolemenu.command(name="inspect", description="Liste les IDs des boutons/selects/options d'un menu")
    @app_commands.describe(menu_id="ID du menu à inspecter")
    async def inspect(self, interaction: discord.Interaction, menu_id: int) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None or interaction.guild is None:
            return

        lines = [
            f"Menu **#{menu['id']}** · <#{menu['channel_id']}> · `{menu['title']}`",
            "",
        ]
        components = db.list_role_menu_components(menu_id)
        if not components:
            lines.append("Aucun bouton/select configuré.")
        for component in components:
            if component["component_type"] == "button":
                role = interaction.guild.get_role(component["role_id"]) if component["role_id"] else None
                role_text = role.mention if role else f"`{component['role_id']}`"
                lines.append(
                    f"Button **#{component['id']}** · {component['label']} · {role_text} · "
                    f"style `{component['style'] or 'secondary'}` · exclusive `{bool(component['exclusive'])}`"
                )
                continue

            lines.append(
                f"Select **#{component['id']}** · {component['placeholder']} · "
                f"min/max `{component['min_values']}/{component['max_values']}` · "
                f"exclusive `{bool(component['exclusive'])}`"
            )
            options = db.list_role_menu_options(component["id"])
            if not options:
                lines.append("  aucune option")
            for option in options:
                role = interaction.guild.get_role(option["role_id"])
                role_text = role.mention if role else f"`{option['role_id']}`"
                lines.append(f"  Option **#{option['id']}** · {option['label']} · {role_text}")

        text = "\n".join(lines)
        if len(text) > 1900:
            text = text[:1890] + "\n…"
        await interaction.response.send_message(text, ephemeral=True)

    @rolemenu.command(name="export", description="Exporte un menu en JSON réimportable")
    @app_commands.describe(menu_id="ID du menu à exporter")
    async def export(self, interaction: discord.Interaction, menu_id: int) -> None:
        menu = await self._get_menu_for_admin(interaction, menu_id)
        if menu is None:
            return

        payload = self._export_payload(menu)
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        file = discord.File(
            io.BytesIO(content.encode("utf-8")),
            filename=f"rolemenu-{menu_id}.json",
        )
        await interaction.response.send_message(
            f"✅ Export du menu **#{menu_id}**. Le fichier est compatible avec `/rolemenu import_config`.",
            file=file,
            ephemeral=True,
        )

    @rolemenu.command(name="copy", description="Copie un menu de rôles dans un autre salon")
    @app_commands.describe(
        menu_id="ID du menu à copier",
        channel="Salon où poster la copie",
    )
    async def copy(
        self,
        interaction: discord.Interaction,
        menu_id: int,
        channel: discord.TextChannel,
    ) -> None:
        source_menu = await self._get_menu_for_admin(interaction, menu_id)
        if source_menu is None or interaction.guild is None:
            return
        if channel.guild.id != interaction.guild.id:
            await interaction.response.send_message(
                "Le salon de destination doit être sur le même serveur.",
                ephemeral=True,
            )
            return

        new_menu_id = db.create_role_menu(
            guild_id=interaction.guild.id,
            channel_id=channel.id,
            title=source_menu["title"],
            description=source_menu["description"],
            color=source_menu["color"],
            footer=source_menu["footer"],
            image_url=source_menu["image_url"],
            thumbnail_url=source_menu["thumbnail_url"],
            created_by=interaction.user.id,
        )

        component_count = 0
        option_count = 0
        for component in db.list_role_menu_components(source_menu["id"]):
            new_component_id = db.add_role_menu_component(
                menu_id=new_menu_id,
                component_type=component["component_type"],
                label=component["label"],
                placeholder=component["placeholder"],
                min_values=component["min_values"],
                max_values=component["max_values"],
                exclusive=bool(component["exclusive"]),
                style=component["style"],
                emoji=component["emoji"],
                role_id=component["role_id"],
            )
            component_count += 1
            for option in db.list_role_menu_options(component["id"]):
                db.add_role_menu_option(
                    component_id=new_component_id,
                    role_id=option["role_id"],
                    label=option["label"],
                    description=option["description"],
                    emoji=option["emoji"],
                )
                option_count += 1

        new_menu = db.get_role_menu(new_menu_id)
        message = await channel.send(embed=_build_embed(new_menu), view=self._view_or_none(new_menu))
        db.update_role_menu(new_menu_id, message_id=message.id)
        await interaction.response.send_message(
            f"✅ Menu **#{menu_id}** copié vers {channel.mention} sous l'ID **#{new_menu_id}** "
            f"({component_count} composant(s), {option_count} option(s)).",
            ephemeral=True,
        )

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
