"""Gestion du forum marché.

Quand un nouveau post est créé dans le forum marché, le bot ajoute un petit
message de gestion avec deux boutons : définir le prix et clôturer l'annonce.
"""
from __future__ import annotations

import asyncio
import logging
import re
import unicodedata
from datetime import timedelta
from typing import Optional

import discord
from discord.ext import commands

import db
from config import MARKET_FORUM_CHANNEL_ID, now_paris
from utils.perms import is_bot_admin

logger = logging.getLogger("dofus-raid-bot.market")

MARKET_FORUM_NAMES = {"le marche", "marche", "le-marché", "marché", "market"}
PRICE_SUFFIX_RE = re.compile(r"\s+-\s+[\d ]+\s+kamas?$", re.IGNORECASE)
MARKET_PREFIX_RE = re.compile(
    r"^\s*\[(?:vente|achat|finalis[ée]?|vente (?:annulée|échouée|guilde|hdv)|achat (?:annulé|échoué|guilde|hdv))\]\s*",
    re.IGNORECASE,
)
MAX_THREAD_NAME_LENGTH = 100
MARKET_INACTIVITY_DAYS = 30
MARKET_INACTIVITY_CHECK_SECONDS = 60 * 60
MARKET_OPERATIONS = {
    "sale": {
        "tag": "vente",
        "noun": "vente",
        "object": "la vente",
        "title": "Vente",
        "failed_label": "Vente annulée",
        "close_label": "✅ Clôturer la vente",
        "prompt": "Choisis comment clôturer cette vente :",
    },
    "buy": {
        "tag": "achat",
        "noun": "achat",
        "object": "l'achat",
        "title": "Achat",
        "failed_label": "Achat annulé",
        "close_label": "✅ Clôturer l'achat",
        "prompt": "Choisis comment clôturer cet achat :",
    },
}
CLOSE_STATUSES = {
    "failed": {"suffix": "annulée", "buy_suffix": "annulé", "style": discord.ButtonStyle.danger},
    "guild": {"suffix": "guilde", "buy_suffix": "guilde", "style": discord.ButtonStyle.success},
    "hdv": {"suffix": "HDV", "buy_suffix": "HDV", "style": discord.ButtonStyle.primary},
}


def _normalize_name(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return re.sub(r"[\s_-]+", " ", ascii_value).strip().lower()


def _format_kamas(value: int) -> str:
    return f"{value:,}".replace(",", " ")


def _market_operation(thread) -> str:
    tag_names = {
        _normalize_name(getattr(tag, "name", ""))
        for tag in getattr(thread, "applied_tags", []) or []
    }
    if MARKET_OPERATIONS["buy"]["tag"] in tag_names:
        return "buy"
    return "sale"


def _choice_label(operation: str, status: str) -> str:
    config = MARKET_OPERATIONS[operation]
    status_config = CLOSE_STATUSES[status]
    suffix = status_config["buy_suffix"] if operation == "buy" else status_config["suffix"]
    return f"{config['title']} {suffix}"


def _market_prefix(operation: str) -> str:
    return f"[{MARKET_OPERATIONS[operation]['tag']}]"


def _base_market_name(name: str, operation: str = "sale") -> str:
    without_prefix = MARKET_PREFIX_RE.sub("", name).strip()
    without_price = PRICE_SUFFIX_RE.sub("", without_prefix).strip()
    return without_price or MARKET_OPERATIONS[operation]["title"]


def _open_name(name: str, operation: str = "sale") -> str:
    prefix = f"{_market_prefix(operation)} "
    base = _base_market_name(name, operation)
    max_base_len = MAX_THREAD_NAME_LENGTH - len(prefix)
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip()
    return f"{prefix}{base}"


def _with_price(name: str, price: int, operation: str = "sale") -> str:
    suffix = f" - {_format_kamas(price)} kamas"
    prefix = f"{_market_prefix(operation)} "
    base = _base_market_name(name, operation)
    max_base_len = MAX_THREAD_NAME_LENGTH - len(prefix) - len(suffix)
    if len(base) > max_base_len:
        base = base[:max_base_len].rstrip()
    return f"{prefix}{base}{suffix}"


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
        if not self.cog.can_manage_post(interaction):
            await interaction.response.send_message("Seuls l'OP et les admins peuvent utiliser ce bouton.", ephemeral=True)
            return
        control_message_id = getattr(getattr(interaction, "message", None), "id", None)
        await interaction.response.send_modal(MarketPriceModal(self.cog, control_message_id))


class _CloseSaleButton(discord.ui.Button):
    def __init__(self, cog: "MarketCog", operation: str = "sale"):
        super().__init__(
            label=MARKET_OPERATIONS[operation]["close_label"],
            style=discord.ButtonStyle.success,
            custom_id="bebraid:market:close",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_close_sale(interaction)


class _AdminCloseSaleButton(discord.ui.Button):
    def __init__(self, cog: "MarketCog"):
        super().__init__(
            label="🔒 Clôture admin",
            style=discord.ButtonStyle.danger,
            custom_id="bebraid:market:admin_close",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.prompt_close_sale(interaction, admin_only=True)


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
    def __init__(self, cog: "MarketCog", status: str, operation: str):
        choice = CLOSE_STATUSES[status]
        super().__init__(label=_choice_label(operation, status), style=choice["style"])
        self.cog = cog
        self.status = status

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_sale(interaction, self.status)


class MarketCloseChoiceView(discord.ui.View):
    def __init__(self, cog: "MarketCog", operation: str):
        super().__init__(timeout=300)
        for status in CLOSE_STATUSES:
            self.add_item(_CloseChoiceButton(cog, status, operation))


class MarketLegacyPostView(discord.ui.View):
    def __init__(self, cog: "MarketCog"):
        super().__init__(timeout=None)
        self.add_item(_LegacyFinalizeSaleButton(cog))


class MarketPostView(discord.ui.View):
    def __init__(self, cog: "MarketCog", operation: str = "sale"):
        super().__init__(timeout=None)
        self.add_item(_SetPriceButton(cog))
        self.add_item(_CloseSaleButton(cog, operation))
        self.add_item(_AdminCloseSaleButton(cog))


class MarketCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._cleanup_task: Optional[asyncio.Task] = None
        self._control_sends: set[int] = set()
        self._closing_threads: set[int] = set()

    async def cog_load(self) -> None:
        self.bot.add_view(MarketPostView(self))
        self.bot.add_view(MarketLegacyPostView(self))
        self._cleanup_task = asyncio.create_task(self._inactive_cleanup_loop())
        logger.info("MarketCog prêt")

    async def cog_unload(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()

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

    def can_manage_post(self, interaction: discord.Interaction) -> bool:
        return self.is_op(interaction) or is_bot_admin(interaction)

    @commands.Cog.listener()
    async def on_thread_create(self, thread: discord.Thread) -> None:
        if not self.is_market_thread(thread):
            return
        self._record_activity(thread)
        await self._ensure_thread_presentation(thread)
        await self._ensure_control_message(thread)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if getattr(getattr(message, "author", None), "bot", False):
            return
        channel = getattr(message, "channel", None)
        if self.is_market_thread(channel):
            self._record_activity(channel)
            await self._ensure_control_message(channel)

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
        if not self.can_manage_post(interaction):
            await interaction.response.send_message("Seuls l'OP et les admins peuvent utiliser ce bouton.", ephemeral=True)
            return

        price_label = _format_kamas(price)
        operation = _market_operation(thread)
        await interaction.response.defer(ephemeral=True)
        try:
            await thread.edit(name=_with_price(thread.name, price, operation), reason=f"Prix marché défini par {interaction.user}")
        except discord.DiscordException as exc:
            logger.warning("Renommage prix marché échoué pour %s: %s", thread.id, exc)
            await interaction.followup.send(
                f"Prix défini : **{price_label} kamas**. Le titre n'a pas pu être renommé pour l'instant.",
                ephemeral=True,
            )
            self._record_activity(thread)
            await self._edit_control_message(thread, control_message_id, price_label)
            return
        self._record_activity(thread)
        await self._edit_control_message(thread, control_message_id, price_label)
        await interaction.followup.send(f"Prix défini : **{price_label} kamas**.", ephemeral=True)

    async def prompt_close_sale(self, interaction: discord.Interaction, *, admin_only: bool = False) -> None:
        if not self.is_market_thread(interaction.channel):
            await interaction.response.send_message("Ce bouton n'est utilisable que dans le forum marché.", ephemeral=True)
            return
        if admin_only and not is_bot_admin(interaction):
            await interaction.response.send_message("Seuls les admins peuvent utiliser cette clôture.", ephemeral=True)
            return
        if not admin_only and not self.can_manage_post(interaction):
            await interaction.response.send_message("Seuls l'OP et les admins peuvent clôturer cette annonce.", ephemeral=True)
            return
        operation = _market_operation(interaction.channel)
        await interaction.response.send_message(
            MARKET_OPERATIONS[operation]["prompt"],
            view=MarketCloseChoiceView(self, operation),
            ephemeral=True,
        )

    async def close_sale(self, interaction: discord.Interaction, status: str) -> None:
        thread = interaction.channel
        if status not in CLOSE_STATUSES:
            await interaction.response.send_message("Choix de clôture invalide.", ephemeral=True)
            return
        if not self.is_market_thread(thread):
            await interaction.response.send_message("Ce bouton n'est utilisable que dans le forum marché.", ephemeral=True)
            return
        if not self.can_manage_post(interaction):
            await interaction.response.send_message("Seuls l'OP et les admins peuvent clôturer cette annonce.", ephemeral=True)
            return
        if thread.id in self._closing_threads:
            await interaction.response.send_message("Clôture déjà en cours pour ce post.", ephemeral=True)
            return

        operation = _market_operation(thread)
        label = _choice_label(operation, status)
        reason = f"{label} par {interaction.user}"
        await interaction.response.defer(ephemeral=True)
        self._closing_threads.add(thread.id)
        try:
            await self._archive_market_thread(thread, reason)
        except discord.Forbidden:
            await interaction.followup.send(
                "Je n'ai pas les permissions pour clôturer ce post.",
                ephemeral=True,
            )
            return
        except discord.DiscordException as exc:
            logger.warning("Clôture marché échouée pour %s: %s", thread.id, exc)
            await interaction.followup.send("Impossible de clôturer ce post.", ephemeral=True)
            return
        finally:
            self._closing_threads.discard(thread.id)

        db.mark_market_post_closed(thread.id, status, now_paris())
        logger.info("Post marché %s archivé avec le statut %s", thread.id, status)

    async def _archive_market_thread(self, thread: discord.Thread, reason: str) -> None:
        await thread.edit(locked=True, archived=True, reason=reason)

    async def _ensure_thread_presentation(self, thread: discord.Thread) -> None:
        if MARKET_PREFIX_RE.match(getattr(thread, "name", "")):
            return
        operation = _market_operation(thread)
        try:
            await thread.edit(name=_open_name(thread.name, operation), reason="Présentation marché normalisée")
        except discord.DiscordException as exc:
            logger.info("Présentation marché non normalisée pour %s: %s", thread.id, exc)

    def _record_activity(self, thread: discord.Thread) -> None:
        guild = getattr(thread, "guild", None)
        owner_id = getattr(thread, "owner_id", None)
        if guild is None or owner_id is None:
            return
        db.upsert_market_post(
            thread_id=thread.id,
            guild_id=guild.id,
            owner_id=owner_id,
            last_activity_at=now_paris(),
        )

    async def _ensure_control_message(self, thread: discord.Thread) -> None:
        if thread.id in self._control_sends:
            return
        post = db.get_market_post(thread.id)
        if post is not None and (post["closed_at"] or post["control_message_id"]):
            return
        self._control_sends.add(thread.id)
        try:
            existing_id = await self._find_existing_control_message(thread)
            if existing_id is not None:
                db.set_market_post_control_message(thread.id, existing_id)
                return
            try:
                operation = _market_operation(thread)
                message = await thread.send(content=self._control_content(operation), view=MarketPostView(self, operation))
            except discord.DiscordException as exc:
                logger.warning("Impossible de poster les boutons marché dans %s: %s", thread.id, exc)
                return
            db.set_market_post_control_message(thread.id, message.id)
            logger.info("Boutons marché postés dans le thread %s", thread.id)
        finally:
            self._control_sends.discard(thread.id)

    async def _find_existing_control_message(self, thread: discord.Thread) -> Optional[int]:
        history = getattr(thread, "history", None)
        if history is None:
            return None
        try:
            async for message in history(limit=20):
                if self._message_has_market_controls(message):
                    return message.id
        except discord.DiscordException as exc:
            logger.info("Historique marché non lisible dans %s: %s", thread.id, exc)
        return None

    def _message_has_market_controls(self, message: discord.Message) -> bool:
        for row in getattr(message, "components", None) or []:
            for component in getattr(row, "children", []) or []:
                custom_id = getattr(component, "custom_id", None)
                if custom_id and custom_id.startswith("bebraid:market:"):
                    return True
        return False

    async def _inactive_cleanup_loop(self) -> None:
        try:
            await self.bot.wait_until_ready()
            await self._bootstrap_active_market_threads()
            while not self.bot.is_closed():
                try:
                    await self._close_inactive_posts_once()
                except Exception as exc:
                    logger.exception("Cleanup inactivité marché échoué: %s", exc)
                await asyncio.sleep(MARKET_INACTIVITY_CHECK_SECONDS)
        except asyncio.CancelledError:
            raise

    async def _bootstrap_active_market_threads(self) -> None:
        count = 0
        for guild in getattr(self.bot, "guilds", []) or []:
            seen: set[int] = set()
            for forum in self._market_forums_for_guild(guild):
                for thread in getattr(forum, "threads", []) or []:
                    if thread.id in seen:
                        continue
                    seen.add(thread.id)
                    if not self.is_market_thread(thread):
                        continue
                    self._record_activity(thread)
                    await self._ensure_control_message(thread)
                    count += 1
            for thread in getattr(guild, "threads", []) or []:
                if thread.id in seen:
                    continue
                seen.add(thread.id)
                if not self.is_market_thread(thread):
                    continue
                self._record_activity(thread)
                await self._ensure_control_message(thread)
                count += 1
        if count:
            logger.info("%d post(s) marché actif(s) vérifié(s)", count)

    def _market_forums_for_guild(self, guild: discord.Guild) -> list[discord.ForumChannel]:
        configured_id = db.get_guild_setting_int(guild.id, db.SETTING_MARKET_FORUM_CHANNEL)
        channel_ids = [configured_id] if configured_id else []
        if MARKET_FORUM_CHANNEL_ID and MARKET_FORUM_CHANNEL_ID not in channel_ids:
            channel_ids.append(MARKET_FORUM_CHANNEL_ID)
        forums: list[discord.ForumChannel] = []
        for channel_id in channel_ids:
            channel = guild.get_channel(channel_id) or self.bot.get_channel(channel_id)
            if isinstance(channel, discord.ForumChannel):
                forums.append(channel)
        if forums:
            return forums
        return [
            channel
            for channel in getattr(guild, "channels", []) or []
            if isinstance(channel, discord.ForumChannel)
            and _normalize_name(getattr(channel, "name", "")) in {_normalize_name(name) for name in MARKET_FORUM_NAMES}
        ]

    async def _close_inactive_posts_once(self) -> None:
        cutoff = now_paris() - timedelta(days=MARKET_INACTIVITY_DAYS)
        for post in db.list_inactive_market_posts(cutoff):
            await self._close_inactive_post(post)

    async def _close_inactive_post(self, post) -> None:
        thread = await self._get_thread(post["thread_id"])
        if thread is None:
            db.mark_market_post_closed(post["thread_id"], "missing", now_paris())
            return
        operation = _market_operation(thread)
        label = _choice_label(operation, "failed")
        original_name = thread.name
        try:
            reason = f"{label} automatique après {MARKET_INACTIVITY_DAYS} jours d'inactivité"
            await self._archive_market_thread(thread, reason)
        except discord.DiscordException as exc:
            logger.warning("Clôture automatique marché échouée pour %s: %s", post["thread_id"], exc)
            return
        db.mark_market_post_closed(post["thread_id"], "failed_inactive", now_paris())
        await self._notify_inactive_owner(post["owner_id"], original_name, thread)

    async def _get_thread(self, thread_id: int) -> Optional[discord.Thread]:
        thread = self.bot.get_channel(thread_id)
        if thread is None:
            try:
                thread = await self.bot.fetch_channel(thread_id)
            except discord.NotFound:
                return None
            except discord.DiscordException as exc:
                logger.warning("Post marché %s introuvable: %s", thread_id, exc)
                return None
        return thread if isinstance(thread, discord.Thread) else None

    async def _notify_inactive_owner(self, owner_id: int, thread_name: str, thread: discord.Thread) -> None:
        try:
            user = self.bot.get_user(owner_id) or await self.bot.fetch_user(owner_id)
        except discord.DiscordException as exc:
            logger.info("MP marché impossible, utilisateur %s introuvable: %s", owner_id, exc)
            return
        link = getattr(thread, "jump_url", None)
        suffix = f"\n{link}" if link else ""
        operation = _market_operation(thread)
        failed_label = MARKET_OPERATIONS[operation]["failed_label"].lower()
        try:
            await user.send(
                content=(
                    f"Ton post marché **{thread_name}** a été clôturé automatiquement "
                    f"en **{failed_label}** après {MARKET_INACTIVITY_DAYS} jours sans activité."
                    f"{suffix}"
                )
            )
        except discord.DiscordException as exc:
            logger.info("MP clôture marché échoué pour %s: %s", owner_id, exc)

    def _control_content(self, operation: str = "sale", price_label: Optional[str] = None) -> str:
        price_text = f"**Prix :** {price_label} kamas" if price_label else "**Prix :** non renseigné"
        return f"{price_text}\nOP/admin : utilise les boutons ci-dessous pour gérer {MARKET_OPERATIONS[operation]['object']}."

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
            operation = _market_operation(thread)
            await message.edit(content=self._control_content(operation, price_label), view=MarketPostView(self, operation))
        except discord.DiscordException as exc:
            logger.info("Message de contrôle marché non mis à jour dans %s: %s", thread.id, exc)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MarketCog(bot))
