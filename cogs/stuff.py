from __future__ import annotations

from io import BytesIO
import re

import discord
from discord import app_commands
from discord.ext import commands

from utils.stuff_capture import capture_dofusbook_page
from utils.stuff_card import StuffLink, build_stuff_fallback_card, parse_dofusbook_url
from utils.perms import is_bot_admin


DOFUSBOOK_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:dofusbook\.net|d-bk\.net)/\S+",
    re.IGNORECASE,
)
TRAILING_URL_PUNCTUATION = ".,;:!?)>]}"
RECENT_HISTORY_LIMIT = 80
STUFF_IMAGE_FILENAME = "stuff-dofusbook.png"


class _AdminCloseStuffButton(discord.ui.Button):
    def __init__(self, cog: "StuffCog"):
        super().__init__(
            label="🔒 Clôture admin",
            style=discord.ButtonStyle.danger,
            custom_id="bebraid:stuff:admin_close",
        )
        self.cog = cog

    async def callback(self, interaction: discord.Interaction) -> None:
        await self.cog.close_stuff(interaction)


class StuffCloseView(discord.ui.View):
    def __init__(self, cog: "StuffCog"):
        super().__init__(timeout=None)
        self.add_item(_AdminCloseStuffButton(cog))


class StuffCog(commands.Cog):
    stuff = app_commands.Group(
        name="stuff",
        description="Outils Dofusbook",
    )

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        self.bot.add_view(StuffCloseView(self))

    @stuff.command(
        name="refresh",
        description="Regénere le dernier stuff Dofusbook récent du salon",
    )
    async def refresh(self, interaction: discord.Interaction):
        await interaction.response.defer(thinking=True)

        channel = interaction.channel
        if channel is None or not hasattr(channel, "history"):
            await interaction.followup.send(
                "Je ne peux pas lire l'historique de ce salon.",
            )
            return

        try:
            source_message, stuff_link = await _find_recent_stuff_message(channel)
        except discord.Forbidden:
            await interaction.followup.send(
                "Il me manque l'accès à l'historique de ce salon.",
            )
            return

        if source_message is None or stuff_link is None:
            await interaction.followup.send(
                "Aucun lien Dofusbook récent trouvé dans ce salon.",
            )
            return

        async with channel.typing():
            content, file = await _build_stuff_response(stuff_link)
            await interaction.followup.send(content=content, file=file, view=StuffCloseView(self))

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or not message.content:
            return

        stuff_link = _extract_stuff_link(message.content)
        if stuff_link is None:
            return

        async with message.channel.typing():
            content, file = await _build_stuff_response(stuff_link)
            await message.reply(content=content, file=file, mention_author=False, view=StuffCloseView(self))

    async def close_stuff(self, interaction: discord.Interaction) -> None:
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Seuls les admins peuvent utiliser cette clôture.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True)
        channel = interaction.channel
        if isinstance(channel, discord.Thread):
            await self._notify_stuff_owner(channel, None)
            try:
                await channel.edit(
                    archived=True,
                    locked=True,
                    reason=f"Stuff clôturé par {interaction.user}",
                )
            except discord.Forbidden:
                await interaction.followup.send(
                    "Je n'ai pas les permissions pour clôturer ce stuff.",
                    ephemeral=True,
                )
                return
            except discord.DiscordException:
                await interaction.followup.send("Impossible de clôturer ce stuff.", ephemeral=True)
                return
            await interaction.followup.send("Stuff clôturé.", ephemeral=True)
            return

        message = getattr(interaction, "message", None)
        if message is None:
            await interaction.followup.send("Rien à clôturer ici.", ephemeral=True)
            return
        await self._notify_stuff_owner(channel, message)
        try:
            await message.delete()
        except discord.DiscordException:
            await interaction.followup.send("Impossible de supprimer ce message stuff.", ephemeral=True)
            return
        await interaction.followup.send("Message stuff supprimé.", ephemeral=True)

    async def _notify_stuff_owner(self, channel, control_message) -> None:
        owner, label, link = await self._resolve_stuff_owner(channel, control_message)
        if owner is None or getattr(owner, "bot", False):
            return
        suffix = f"\n{link}" if link else ""
        try:
            await owner.send(
                content=(
                    f"Ton post stuff **{label}** a été clôturé pour non-respect des règles."
                    f"{suffix}"
                )
            )
        except discord.DiscordException:
            return

    async def _resolve_stuff_owner(self, channel, control_message):
        owner_id = getattr(channel, "owner_id", None)
        if owner_id is not None:
            user = self.bot.get_user(owner_id)
            if user is None:
                try:
                    user = await self.bot.fetch_user(owner_id)
                except discord.DiscordException:
                    user = None
            if user is not None:
                return user, getattr(channel, "name", None) or "Dofusbook", getattr(channel, "jump_url", None)

        source_message = _referenced_message(control_message)
        if source_message is None:
            return None, "Dofusbook", None
        author = getattr(source_message, "author", None)
        return author, _stuff_message_label(source_message), getattr(source_message, "jump_url", None)


async def _build_stuff_response(stuff_link):
    screenshot, reason = await capture_dofusbook_page(stuff_link.url)
    if screenshot is not None:
        return None, discord.File(BytesIO(screenshot), filename=STUFF_IMAGE_FILENAME)

    card = build_stuff_fallback_card(stuff_link, reason)
    return (
        "Je n'ai pas pu lire Dofusbook directement, "
        "mais j'ai genere une carte depuis le lien.",
        discord.File(card, filename=STUFF_IMAGE_FILENAME),
    )


async def _find_recent_stuff_message(channel) -> tuple[discord.Message | None, StuffLink | None]:
    async for message in channel.history(limit=RECENT_HISTORY_LIMIT):
        if message.author.bot or not message.content:
            continue

        stuff_link = _extract_stuff_link(message.content)
        if stuff_link is not None:
            return message, stuff_link

    return None, None


def _extract_stuff_link(content: str) -> StuffLink | None:
    match = DOFUSBOOK_LINK_RE.search(content)
    if match is None:
        return None

    try:
        return parse_dofusbook_url(_clean_detected_url(match.group(0)))
    except ValueError:
        return None


def _clean_detected_url(url: str) -> str:
    return url.rstrip(TRAILING_URL_PUNCTUATION)


def _referenced_message(message):
    reference = getattr(message, "reference", None)
    if reference is None:
        return None
    return getattr(reference, "resolved", None) or getattr(reference, "cached_message", None)


def _stuff_message_label(message) -> str:
    content = (getattr(message, "content", None) or "").strip().replace("\n", " ")
    if not content:
        return "Dofusbook"
    if len(content) > 80:
        return f"{content[:77].rstrip()}..."
    return content


async def setup(bot: commands.Bot):
    await bot.add_cog(StuffCog(bot))
