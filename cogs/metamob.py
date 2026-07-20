from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen

import discord
from discord import app_commands
from discord.ext import commands

import db

logger = logging.getLogger("dofus-raid-bot.metamob")

METAMOB_API_BASE_URL = "https://www.metamob.fr/api"
METAMOB_TIMEOUT_SECONDS = 15
METAMOB_ARCHMONSTER_TYPE_ID = 3
DISCORD_MESSAGE_LIMIT = 1900
AUTOCOMPLETE_LIMIT = 25


class MetamobAPIError(Exception):
    def __init__(self, status: int | None, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ArchMonster:
    id: int
    name: str
    owned: int
    required: int

    @property
    def extra(self) -> int:
        return max(0, self.owned - self.required)

    @property
    def missing(self) -> int:
        return max(0, self.required - self.owned)


@dataclass(frozen=True)
class TradeOpportunity:
    monster: ArchMonster
    giver_extra: int
    receiver_missing: int


@dataclass(frozen=True)
class MonsterSearchResult:
    id: int
    name: str


def _metamob_request_sync(
    api_key: str,
    method: str,
    path: str,
    params: dict[str, Any] | None = None,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    query = f"?{urlencode(params)}" if params else ""
    url = f"{METAMOB_API_BASE_URL}{path}{query}"
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = Request(
        url,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "beb-raid-discord-bot/1.0",
        },
    )
    try:
        with urlopen(request, timeout=METAMOB_TIMEOUT_SECONDS) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = _read_error_detail(exc)
        raise MetamobAPIError(exc.code, detail) from exc
    except URLError as exc:
        raise MetamobAPIError(None, f"Metamob inaccessible: {exc.reason}") from exc
    except TimeoutError as exc:
        raise MetamobAPIError(None, "Metamob ne répond pas assez vite.") from exc
    except json.JSONDecodeError as exc:
        raise MetamobAPIError(None, "Réponse Metamob illisible.") from exc


def _metamob_get_sync(api_key: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return _metamob_request_sync(api_key, "GET", path, params=params)


def _metamob_patch_sync(api_key: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return _metamob_request_sync(api_key, "PATCH", path, body=body)


def _read_error_detail(exc: HTTPError) -> str:
    try:
        payload = json.loads(exc.read().decode("utf-8"))
    except Exception:
        payload = {}
    for key in ("message", "error", "detail"):
        value = payload.get(key)
        if value:
            return str(value)
    if exc.code == 401:
        return "clé API Metamob invalide."
    if exc.code == 404:
        return "quête Metamob introuvable pour cette clé."
    if exc.code == 429:
        return "limite Metamob atteinte, réessaie dans quelques instants."
    return f"erreur Metamob HTTP {exc.code}."


async def _metamob_get(api_key: str, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    return await asyncio.to_thread(_metamob_get_sync, api_key, path, params)


async def _metamob_patch(api_key: str, path: str, body: dict[str, Any]) -> dict[str, Any]:
    return await asyncio.to_thread(_metamob_patch_sync, api_key, path, body)


async def fetch_quest_settings(api_key: str, quest_slug: str) -> dict[str, Any]:
    payload = await _metamob_get(api_key, f"/v1/quests/{quote(quest_slug, safe='')}")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MetamobAPIError(None, "Réponse de quête Metamob invalide.")
    return data


async def fetch_archmonsters(api_key: str, quest_slug: str) -> dict[int, ArchMonster]:
    payload = await _metamob_get(
        api_key,
        f"/v1/quests/{quote(quest_slug, safe='')}/zones",
        {"monster_type_id": METAMOB_ARCHMONSTER_TYPE_ID},
    )
    zones = payload.get("data")
    if not isinstance(zones, list):
        raise MetamobAPIError(None, "Réponse de zones Metamob invalide.")

    monsters: dict[int, ArchMonster] = {}
    for zone in zones:
        for subzone in zone.get("subzones", []) or []:
            for monster in subzone.get("monsters", []) or []:
                monster_type = monster.get("type") or {}
                if monster_type.get("id") != METAMOB_ARCHMONSTER_TYPE_ID:
                    continue
                monster_id = int(monster["id"])
                monsters[monster_id] = ArchMonster(
                    id=monster_id,
                    name=_localized_name(monster.get("name"), fallback=f"Monstre #{monster_id}"),
                    owned=int(monster.get("owned") or 0),
                    required=int(monster.get("required") or 1),
                )
    return monsters


async def search_archmonsters(api_key: str, query: str, limit: int = AUTOCOMPLETE_LIMIT) -> list[MonsterSearchResult]:
    params: dict[str, Any] = {"type": METAMOB_ARCHMONSTER_TYPE_ID, "limit": limit}
    cleaned = query.strip()
    if len(cleaned) >= 3:
        params["q"] = cleaned
    payload = await _metamob_get(api_key, "/v1/monsters", params)
    data = payload.get("data")
    if not isinstance(data, list):
        raise MetamobAPIError(None, "Réponse de recherche Metamob invalide.")
    results: list[MonsterSearchResult] = []
    for monster in data:
        try:
            monster_id = int(monster["id"])
        except (KeyError, TypeError, ValueError):
            continue
        results.append(
            MonsterSearchResult(
                id=monster_id,
                name=_localized_name(monster.get("name"), fallback=f"Monstre #{monster_id}"),
            )
        )
    return results[:limit]


async def update_monster_quantity(
    api_key: str,
    quest_slug: str,
    monster_id: int,
    quantity: int,
) -> dict[str, Any]:
    payload = await _metamob_patch(
        api_key,
        f"/v1/quests/{quote(quest_slug, safe='')}/monsters/{monster_id}",
        {"quantity": quantity},
    )
    data = payload.get("data")
    if not isinstance(data, dict):
        raise MetamobAPIError(None, "Réponse de mise à jour Metamob invalide.")
    return data


def _localized_name(value: Any, fallback: str = "Inconnu") -> str:
    if isinstance(value, dict):
        return str(value.get("fr") or value.get("en") or value.get("es") or fallback)
    if value:
        return str(value)
    return fallback


def _normalize_quest_slug(value: str) -> str:
    cleaned = value.strip().rstrip("/")
    if not cleaned:
        return ""
    parsed = urlparse(cleaned)
    path = parsed.path if parsed.scheme or parsed.netloc else cleaned
    return path.rstrip("/").rsplit("/", 1)[-1].strip()


def _choice_value(monster: MonsterSearchResult) -> str:
    return f"{monster.id}:{monster.name}"[:100]


def _choice_name(monster: MonsterSearchResult) -> str:
    return monster.name[:100]


def _selected_monster_id(value: str) -> int | None:
    raw_id = value.split(":", 1)[0].strip()
    return int(raw_id) if raw_id.isdigit() else None


def resolve_archmonster(value: str, monsters: dict[int, ArchMonster]) -> ArchMonster | None:
    selected_id = _selected_monster_id(value)
    if selected_id is not None:
        return monsters.get(selected_id)

    wanted = value.strip().casefold()
    exact = [monster for monster in monsters.values() if monster.name.casefold() == wanted]
    if exact:
        return sorted(exact, key=lambda monster: monster.name.casefold())[0]

    partial = [
        monster
        for monster in monsters.values()
        if wanted and wanted in monster.name.casefold()
    ]
    if len(partial) == 1:
        return partial[0]
    return None


def adjusted_quantity(current: int, delta: int) -> int:
    return max(0, min(current + delta, 30))


def _quest_type_slug(settings: dict[str, Any]) -> str | None:
    quest_template = settings.get("quest_template") or {}
    quest_type = quest_template.get("quest_type") or {}
    slug = quest_type.get("slug")
    return str(slug) if slug else None


def _server_name(settings: dict[str, Any]) -> str | None:
    server = settings.get("server") or {}
    name = server.get("name")
    return str(name) if name else None


def find_trade_opportunities(
    giver: dict[int, ArchMonster],
    receiver: dict[int, ArchMonster],
) -> list[TradeOpportunity]:
    opportunities: list[TradeOpportunity] = []
    for monster_id, monster in giver.items():
        receiver_monster = receiver.get(monster_id)
        if receiver_monster is None:
            continue
        if monster.extra > 0 and receiver_monster.missing > 0:
            opportunities.append(
                TradeOpportunity(
                    monster=monster,
                    giver_extra=monster.extra,
                    receiver_missing=receiver_monster.missing,
                )
            )
    return sorted(opportunities, key=lambda item: item.monster.name.casefold())


def _format_opportunities(items: list[TradeOpportunity], *, empty: str) -> list[str]:
    if not items:
        return [empty]
    return [
        f"- {item.monster.name} (+{item.giver_extra} dispo, manque {item.receiver_missing})"
        for item in items
    ]


def _chunk_lines(lines: list[str], limit: int = DISCORD_MESSAGE_LIMIT) -> list[str]:
    chunks: list[str] = []
    current = ""
    for line in lines:
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) <= limit:
            current = candidate
            continue
        if current:
            chunks.append(current)
        current = line[:limit]
    if current:
        chunks.append(current)
    return chunks


def _link_label(link) -> str:
    character = link["character_name"] or "quête Metamob"
    server = f" - {link['server_name']}" if link["server_name"] else ""
    return f"{character}{server}"


def _metamob_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Metamob",
        description="Lie ton compte Metamob au bot pour comparer tes archimonstres avec un autre membre.",
        color=0xF1C40F,
    )
    embed.add_field(
        name="/metamob link",
        value=(
            "Ouvre un formulaire privé. Colle ta clé API Metamob et le slug de ta quête. "
            "Le slug est dans l'URL de ta quête Metamob."
        ),
        inline=False,
    )
    embed.add_field(
        name="/metamob trade @membre",
        value=(
            "Compare les deux comptes liés et liste les archimonstres que tu as en trop "
            "et qui lui manquent, puis l'inverse."
        ),
        inline=False,
    )
    embed.add_field(
        name="/metamob add",
        value="Ajoute 1 exemplaire d'un archimonstre dans ta quête Metamob liée.",
        inline=False,
    )
    embed.add_field(
        name="/metamob del",
        value="Retire 1 exemplaire d'un archimonstre de ta quête Metamob liée.",
        inline=False,
    )
    embed.add_field(
        name="/metamob unlink",
        value="Supprime ta clé API Metamob du bot.",
        inline=False,
    )
    embed.add_field(
        name="Où trouver la clé API ?",
        value="Metamob > Paramètres > section API Key > Générer une clé.",
        inline=False,
    )
    return embed


class MetamobLinkModal(discord.ui.Modal, title="Lier Metamob"):
    api_key = discord.ui.TextInput(
        label="Clé API Metamob",
        placeholder="Colle la clé générée dans tes paramètres Metamob",
        required=True,
        max_length=300,
    )
    quest_slug = discord.ui.TextInput(
        label="Slug de quête",
        placeholder="Exemple : a1b2c3d4",
        required=True,
        max_length=80,
    )
    username = discord.ui.TextInput(
        label="Pseudo Metamob (optionnel)",
        placeholder="Utile uniquement pour l'affichage",
        required=False,
        max_length=80,
    )

    def __init__(self, cog: "MetamobCog"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction) -> None:
        await self.cog.finish_link(
            interaction,
            api_key=str(self.api_key.value).strip(),
            quest_slug=str(self.quest_slug.value).strip(),
            username=str(self.username.value).strip() or None,
        )


class MetamobCog(commands.Cog):
    metamob = app_commands.Group(name="metamob", description="Outils Metamob")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        db.init()
        logger.info("MetamobCog prêt")

    @metamob.command(name="help", description="Explique comment lier Metamob au bot")
    async def help(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=_metamob_help_embed(), ephemeral=True)

    @metamob.command(name="link", description="Lie ton compte Metamob au bot")
    async def link(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.send_modal(MetamobLinkModal(self))

    async def finish_link(
        self,
        interaction: discord.Interaction,
        *,
        api_key: str,
        quest_slug: str,
        username: str | None,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True, thinking=True)

        if not api_key or not quest_slug:
            await interaction.followup.send("Clé API et slug de quête obligatoires.", ephemeral=True)
            return

        try:
            normalized_slug = _normalize_quest_slug(quest_slug)
            settings = await fetch_quest_settings(api_key, normalized_slug)
        except MetamobAPIError as exc:
            await interaction.followup.send(
                f"Je n'ai pas pu valider ce lien Metamob: {exc.message}",
                ephemeral=True,
            )
            return

        db.upsert_metamob_link(
            guild_id=interaction.guild.id,
            user_id=interaction.user.id,
            api_key=api_key,
            quest_slug=str(settings.get("slug") or normalized_slug),
            username=username,
            character_name=str(settings.get("character_name") or "") or None,
            server_name=_server_name(settings),
            quest_type_slug=_quest_type_slug(settings),
        )
        character = settings.get("character_name") or "quête Metamob"
        server = _server_name(settings)
        details = f" ({server})" if server else ""
        await interaction.followup.send(
            f"✅ Metamob lié pour **{character}**{details}.",
            ephemeral=True,
        )

    @metamob.command(name="unlink", description="Supprime ton lien Metamob")
    async def unlink(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        deleted = db.delete_metamob_link(interaction.guild.id, interaction.user.id)
        message = "✅ Ton lien Metamob a été supprimé." if deleted else "Aucun lien Metamob enregistré."
        await interaction.response.send_message(message, ephemeral=True)

    @metamob.command(name="add", description="Ajoute un archimonstre à ton inventaire Metamob")
    @app_commands.describe(archimonstre="Nom de l'archimonstre à ajouter")
    async def add(self, interaction: discord.Interaction, archimonstre: str) -> None:
        await self._change_archmonster_quantity(
            interaction,
            archimonstre,
            delta=1,
            verb="ajouter",
            done_label="ajouté",
            limit_message="est déjà à la quantité maximale Metamob",
        )

    @add.autocomplete("archimonstre")
    async def add_archimonstre_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._archimonstre_autocomplete(interaction, current)

    @metamob.command(name="del", description="Retire un archimonstre de ton inventaire Metamob")
    @app_commands.describe(archimonstre="Nom de l'archimonstre à retirer")
    async def delete(self, interaction: discord.Interaction, archimonstre: str) -> None:
        await self._change_archmonster_quantity(
            interaction,
            archimonstre,
            delta=-1,
            verb="retirer",
            done_label="retiré",
            limit_message="est déjà à 0 sur Metamob",
        )

    @delete.autocomplete("archimonstre")
    async def delete_archimonstre_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._archimonstre_autocomplete(interaction, current)

    async def _change_archmonster_quantity(
        self,
        interaction: discord.Interaction,
        archimonstre: str,
        *,
        delta: int,
        verb: str,
        done_label: str,
        limit_message: str,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return

        link = db.get_metamob_link(interaction.guild.id, interaction.user.id)
        if link is None:
            await interaction.response.send_message("Tu dois d'abord faire `/metamob link`.", ephemeral=True)
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            monsters = await fetch_archmonsters(link["api_key"], link["quest_slug"])
            monster = resolve_archmonster(archimonstre, monsters)
            if monster is None:
                await interaction.followup.send(
                    "Je n'ai pas trouvé cet archimonstre dans ta quête. "
                    "Réessaie avec l'autocomplétion Metamob.",
                    ephemeral=True,
                )
                return

            new_quantity = adjusted_quantity(monster.owned, delta)
            if new_quantity == monster.owned:
                await interaction.followup.send(
                    f"**{monster.name}** {limit_message} ({monster.owned}).",
                    ephemeral=True,
                )
                return

            updated = await update_monster_quantity(
                link["api_key"],
                link["quest_slug"],
                monster.id,
                new_quantity,
            )
        except MetamobAPIError as exc:
            await interaction.followup.send(
                f"Je n'ai pas pu {verb} cet archimonstre: {exc.message}",
                ephemeral=True,
            )
            return

        quantity = int(updated.get("owned") or updated.get("quantity") or new_quantity)
        await interaction.followup.send(
            f"✅ **{monster.name}** {done_label} sur Metamob: {monster.owned} → {quantity}.",
            ephemeral=True,
        )

    async def _archimonstre_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        if interaction.guild is None:
            return []
        link = db.get_metamob_link(interaction.guild.id, interaction.user.id)
        if link is None:
            return []
        try:
            monsters = await search_archmonsters(link["api_key"], current)
        except MetamobAPIError:
            logger.exception("Échec autocomplete Metamob")
            return []
        return [
            app_commands.Choice(name=_choice_name(monster), value=_choice_value(monster))
            for monster in monsters
        ]

    @metamob.command(name="trade", description="Compare tes archimonstres avec un membre lié")
    @app_commands.describe(user="Membre Discord avec qui comparer les archimonstres")
    async def trade(self, interaction: discord.Interaction, user: discord.Member) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("Ce membre est un bot.", ephemeral=True)
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message("Choisis un autre membre pour comparer.", ephemeral=True)
            return

        own_link = db.get_metamob_link(interaction.guild.id, interaction.user.id)
        target_link = db.get_metamob_link(interaction.guild.id, user.id)
        if own_link is None:
            await interaction.response.send_message("Tu dois d'abord faire `/metamob link`.", ephemeral=True)
            return
        if target_link is None:
            await interaction.response.send_message(
                f"{user.mention} doit d'abord faire `/metamob link`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            own_archs, target_archs = await asyncio.gather(
                fetch_archmonsters(own_link["api_key"], own_link["quest_slug"]),
                fetch_archmonsters(target_link["api_key"], target_link["quest_slug"]),
            )
        except MetamobAPIError as exc:
            await interaction.followup.send(
                f"Je n'ai pas pu lire les inventaires Metamob: {exc.message}",
                ephemeral=True,
            )
            return

        you_give = find_trade_opportunities(own_archs, target_archs)
        they_give = find_trade_opportunities(target_archs, own_archs)
        lines = [
            f"**Comparaison Metamob**",
            f"Toi: {_link_label(own_link)}",
            f"{user.display_name}: {_link_label(target_link)}",
            "",
            f"**Tu as en trop et {user.display_name} n'a pas assez** ({len(you_give)})",
            *_format_opportunities(you_give, empty="- Rien trouvé."),
            "",
            f"**{user.display_name} a en trop et toi tu n'as pas assez** ({len(they_give)})",
            *_format_opportunities(they_give, empty="- Rien trouvé."),
        ]

        chunks = _chunk_lines(lines)
        await interaction.followup.send(chunks[0], ephemeral=True)
        for chunk in chunks[1:]:
            await interaction.followup.send(chunk, ephemeral=True)

async def setup(bot: commands.Bot):
    await bot.add_cog(MetamobCog(bot))
