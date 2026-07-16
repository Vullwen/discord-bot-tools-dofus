"""Gestion du forum marché.

Quand un nouveau post est créé dans le forum marché, le bot ajoute un petit
message de gestion avec deux boutons : définir le prix et clôturer la vente.
"""
from __future__ import annotations

import logging
import re
import unicodedata
from typing import Optional

import discord
from discord.ext import commands

import db
from config import MARKET_FORUM_CHANNEL_ID
from utils.perms import is_bot_admin

logger = logging.getLogger("beb-raid.market")

MARKET_FORUM_NAMES = {"le marche", "marche", "le-marché", "marché", "market"}
PRICE_SUFFIX_RE = re.compile(r"\s+-\s+[\d ]+\s+kamas?$", re.IGNORECASE)
STATUS_PREFIX_RE = re.compile(r"^\s*\[(?:finalis[ée]?|vente échouée|vente guilde|vente hdv)\]\s*", re.IGNORECASE)
MAX_THREAD_NAME_LENGTH = 100
SALE_CLOSE_CHOICES = {
    "failed": {"label": "Vente échouée", "prefix": "[vente échouée]", "style": discord.ButtonStyle.danger},
    "guild": {"label": "Vente guilde", "prefix": "[vente guilde]", "style": discord.ButtonStyle.success},
    "hdv": {"label": "Vente HDV", "prefix": "[vente hdv]", "style": discord.ButtonStyle.primary},
}


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[\s_-]+", " ", ascii_value).strip().lower()


def _format_kamas(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _base_sale_name(name: str) -> str:
    without_status = STATUS_PREFIX_RE.sub("", name).strip()
    without_price = PRICE_SUFFIX_RE.sub("", without_status).strip()
    return without_price or "Vente"


def _with_price(name: str, price: int) -> str:
    suffix = f" - {_format_kamas(price)} kamas"
    max_base_len = MAX_THREAD_NAME_LENGTH - len(suffix)
    base = _base_sale_name(name)
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip()
    return f"{base}{suffix}"


def _closed_name(name: str, status: str) -> str:
    base = STATUS_PREFIX_RE.sub("", name).strip() or "Vente"
    prefix = f"{SALE_CLOSE_CHOICES[status]['prefix']} "
    max_base_len = MAX_THREAD_NAME_LENGTH - len(prefix)
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip()
    return f"{prefix}{base}"


def _parse_kamas(raw: str) -> Optional[int]:
    cleaned = re.sub(r"[\s_,.]", "", raw)
    if not cleaned.isdigit():
        return None
    value = int(cleaned)
    return value if value > 0 else None


class MarketPriceModal(discord.ui.Modal, title="Prix en kamas"):
    price_input = discord.ui.TextInput(
        label="Prix",
        placeholder="Exemple : 1 500 000",
        required=True,
        max_length=20,
    )

    def __init__(self, cog: "MarketCog", control_message_id: Optional[int]):
        super().__init__()
        self.cog = cog
        self.control_message_id = control_message_id

    async def on_submit(self, interaction: discord.Interaction) -> None:
        price = _parse_kamas(str(self.price_input.value))
        if price is None:
            await interaction.response.send_message(
                "Prix invalide. Indique un nombre de kamas, par exemple `1 500 000`.",
                ephemeral=True,
            )
            return
        await self.cog.set_price(interaction, price, self.control_message_id)


class _SetPriceButton(discord.ui.Button):
    def __init__(self, cog: "MarketCog"):
        super().__init__(
            label="💰 Mettre le prix",
            style=discord.ButtonStyle.primary,
            custom_id="bebraid:market:set_price",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        if not self.cog.is_market_thread(interaction.channel):
            await interaction.response.send_message("Ce bouton n'est utilisable que dans le forum marché.", ephemeral=True)
            return
        if not self.cog.is_op(interaction):
            await interaction.response.send_message("Seul l'OP peut modifier le prix.", ephemeral=True)
            return
        control_message_id = getattr(getattr(interaction, "message", None), "id", None)
        await interaction.response.send_modal(MarketPriceModal(self.cog, control_message_id))


class _CloseSaleButton(discord.ui.Button):
    def __init__(self, cog: "MarketCog"):
        super().__init__(
            label="✅ Clôturer la vente",
            style=discord.ButtonStyle.success,
            custom_id="bebraid:market:close",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_close_sale(interaction)


class _LegacyFinalizeSaleButton(discord.ui.Button):
    def __init__(self, cog: "MarketCog"):
        super().__init__(
            label="✅ Vente finalisée",
            style=discord.ButtonStyle.success,
            custom_id="bebraid:market:finalize",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_close_sale(interaction)


class _CloseChoiceButton(discord.ui.Button):
    def __init__(self, cog: "MarketCog", status: str):
        choice = SALE_CLOSE_CHOICES[status]
        super().__init__(label=choice["label"], style=choice["style"])
        self.cog = cog
        self.status = status

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_sale(interaction, self.status)


class MarketCloseChoiceView(discord.ui.View):
    def __init__(self, cog: "MarketCog"):
        super().__init__(timeout=300)
        for status in SALE_CLOSE_CHOICES:
            self.add_item(_CloseChoiceButton(cog, status))


class MarketLegacyPostView(discord.ui.View):
    def __init__(self, cog: "MarketCog"):
        super().__init__(timeout=None)
        self.add_item(_LegacyFinalizeSaleButton(cog))


class MarketPostView(discord.ui.View):
    def __init__(self, cog: "MarketCog"):
        super().__init__(timeout=None)
        self.add_item(_SetPriceButton(cog))
        self.add_item(_CloseSaleButton(cog))


class MarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(MarketPostView(self))
        self.bot.add_view(MarketLegacyPostView(self))
        logger.info("MarketCog prêt")

    def is_market_thread(self, channel) -> bool:
        if not isinstance(channel, discord.Thread):
            return False
        guild = getattr(channel, "guild", None)
        if guild is not None:
            configured_id = db.get_guild_setting_int(guild.id, db.SETTING_MARKET_FORUM_CHANNEL)
            if configured_id:
                return channel.parent_id == configured_id
        if MARKET_FORUM_CHANNEL_ID:
            return channel.parent_id == MARKET_FORUM_CHANNEL_ID
        parent_name = getattr(getattr(channel, "parent", None), "name", "")
        return _normalize_name(parent_name) in {_normalize_name(name) for name in MARKET_FORUM_NAMES}

    def is_op(self, interaction: discord.Interaction) -> bool:
        owner_id = getattr(interaction.channel, "owner_id", None)
        return owner_id is not None and interaction.user.id == owner_id

    def can_close(self, interaction: discord.Interaction) -> bool:
        return self.is_op(interaction) or is_bot_admin(interaction)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if not self.is_market_thread(thread):
            return
        try:
            await thread.send(content=self._control_content(), view=MarketPostView(self))
            logger.info("Boutons marché postés dans le thread %s", thread.id)
        except discord.DiscordException as exc:
            logger.warning("Impossible de poster les boutons marché dans %s: %s", thread.id, exc)

    async def set_price(
        self,
        interaction: discord.Interaction,
        price: int,
        control_message_id: Optional[int],
    ) -> None:
        thread = interaction.channel
        if not self.is_market_thread(thread):
            await interaction.response.send_message("Ce bouton n'est utilisable que dans le forum marché.", ephemeral=True)
            return
        if not self.is_op(interaction):
            await interaction.response.send_message("Seul l'OP peut modifier le prix.", ephemeral=True)
            return

        price_label = _format_kamas(price)
        try:
            await thread.edit(name=_with_price(thread.name, price), reason=f"Prix marché défini par {interaction.user}")
        except discord.DiscordException as exc:
            logger.warning("Renommage prix marché échoué pour %s: %s", thread.id, exc)
            await interaction.response.send_message("Impossible de renommer le post avec le prix.", ephemeral=True)
            return

        await self._edit_control_message(thread, control_message_id, price_label)
        await interaction.response.send_message(f"Prix défini : **{price_label} kamas**.", ephemeral=True)

    async def prompt_close_sale(self, interaction: discord.Interaction) -> None:
        if not self.is_market_thread(interaction.channel):
            await interaction.response.send_message("Ce bouton n'est utilisable que dans le forum marché.", ephemeral=True)
            return
        if not self.can_close(interaction):
            await interaction.response.send_message("Seuls l'OP et les admins peuvent clôturer la vente.", ephemeral=True)
            return
        await interaction.response.send_message(
            "Choisis comment clôturer cette vente :",
            view=MarketCloseChoiceView(self),
            ephemeral=True,
        )

    async def close_sale(self, interaction: discord.Interaction, status: str) -> None:
        thread = interaction.channel
        if status not in SALE_CLOSE_CHOICES:
            await interaction.response.send_message("Choix de clôture invalide.", ephemeral=True)
            return
        if not self.is_market_thread(thread):
            await interaction.response.send_message("Ce bouton n'est utilisable que dans le forum marché.", ephemeral=True)
            return
        if not self.can_close(interaction):
            await interaction.response.send_message("Seuls l'OP et les admins peuvent clôturer la vente.", ephemeral=True)
            return

        label = SALE_CLOSE_CHOICES[status]["label"]
        try:
            await thread.edit(
                name=_closed_name(thread.name, status),
                archived=True,
                locked=True,
                reason=f"{label} par {interaction.user}",
            )
        except discord.Forbidden:
            await interaction.response.send_message(
                "Je n'ai pas les permissions pour clôturer ce post.",
                ephemeral=True,
            )
            return
        except discord.DiscordException as exc:
            logger.warning("Clôture marché échouée pour %s: %s", thread.id, exc)
            await interaction.response.send_message("Impossible de clôturer ce post.", ephemeral=True)
            return

        await interaction.response.send_message(f"{label} : post clôturé.", ephemeral=True)

    def _control_content(self, price_label: Optional[str] = None) -> str:
        price_text = f"**Prix :** {price_label} kamas" if price_label else "**Prix :** non renseigné"
        return f"{price_text}\nOP : utilise les boutons ci-dessous pour gérer la vente."

    async def _edit_control_message(
        self,
        thread: discord.Thread,
        control_message_id: Optional[int],
        price_label: str,
    ) -> None:
        if control_message_id is None:
            return
        try:
            message = await thread.fetch_message(control_message_id)
            await message.edit(content=self._control_content(price_label), view=MarketPostView(self))
        except discord.DiscordException as exc:
            logger.info("Message de contrôle marché non mis à jour dans %s: %s", thread.id, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCog(bot))
