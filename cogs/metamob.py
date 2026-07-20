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
MAX_METAMOB_QUANTITY = 30
SEARCH_MATCH_LIMIT = 5


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


@dataclass(frozen=True)
class TradeSearchMatch:
    user_id: int
    label: str
    they_give: list[TradeOpportunity]
    you_give: list[TradeOpportunity]

    @property
    def they_count(self) -> int:
        return len(self.they_give)

    @property
    def you_count(self) -> int:
        return len(self.you_give)

    @property
    def score(self) -> tuple[int, int]:
        return (min(self.they_count, self.you_count), self.they_count + self.you_count)


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


async def update_monster_quantities(
    api_key: str,
    quest_slug: str,
    quantities: dict[int, int],
) -> dict[str, Any]:
    payload = await _metamob_patch(
        api_key,
        f"/v1/quests/{quote(quest_slug, safe='')}/monsters",
        {
            "monsters": [
                {"monster_id": monster_id, "quantity": quantity}
                for monster_id, quantity in quantities.items()
            ]
        },
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
    return max(0, min(current + delta, MAX_METAMOB_QUANTITY))


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


def _sample_opportunities(items: list[TradeOpportunity], limit: int = 3) -> str:
    if not items:
        return "rien"
    names = [item.monster.name for item in items[:limit]]
    suffix = "" if len(items) <= limit else f" +{len(items) - limit}"
    return ", ".join(names) + suffix


def _format_search_match(match: TradeSearchMatch, index: int) -> str:
    return "\n".join(
        [
            f"**{index}. {match.label}**",
            f"- Il/elle a **{match.they_count}** archi(s) que tu cherches : {_sample_opportunities(match.they_give)}",
            f"- Tu as **{match.you_count}** archi(s) qu'il/elle cherche : {_sample_opportunities(match.you_give)}",
        ]
    )


def _search_results_content(matches: list[TradeSearchMatch]) -> str:
    if not matches:
        return "Aucune correspondance de trade mutuel trouvée avec les comptes Metamob liés du serveur."
    lines = ["**Meilleures correspondances Metamob**"]
    for index, match in enumerate(matches, start=1):
        lines.extend(("", _format_search_match(match, index)))
    return "\n".join(lines)


def _trade_lines_for_giver(items, giver_id: int) -> list[str]:
    return [
        f"- {item['monster_name']} x{item['quantity']}"
        for item in items
        if item["giver_id"] == giver_id
    ]


def _embed_field_value(lines: list[str], *, empty: str = "Rien pour l'instant.") -> str:
    value = "\n".join(lines or [empty])
    return value if len(value) <= 1024 else value[:1000].rstrip() + "\n..."


def _trade_embed(trade, items) -> discord.Embed:
    status_labels = {
        "open": "ouvert",
        "pending_confirm": "validation en attente",
        "completed": "validé",
        "cancelled": "annulé",
    }
    embed = discord.Embed(
        title=f"Échange Metamob #{trade['id']}",
        description=(
            f"**Statut :** {status_labels.get(trade['status'], trade['status'])}\n"
            f"**Participants :** <@{trade['starter_id']}> et <@{trade['target_id']}>"
        ),
        color=0xF1C40F,
    )
    embed.add_field(
        name=f"<@{trade['starter_id']}> donne à <@{trade['target_id']}>",
        value=_embed_field_value(_trade_lines_for_giver(items, trade["starter_id"])),
        inline=False,
    )
    embed.add_field(
        name=f"<@{trade['target_id']}> donne à <@{trade['starter_id']}>",
        value=_embed_field_value(_trade_lines_for_giver(items, trade["target_id"])),
        inline=False,
    )
    embed.add_field(
        name="Mini tuto",
        value=(
            "Ajoutez votre/vos mob(s) avec `/trade add`.\n"
            "Retirez une ligne avec `/trade del`.\n"
            "Quand tout est prêt, cliquez sur **Clôturer l'échange**."
        ),
        inline=False,
    )
    return embed


def _trade_thread_name(first: discord.abc.User, second: discord.abc.User) -> str:
    name = f"Échange Metamob - {first.display_name} & {second.display_name}"
    return name[:100]


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
        name="/metamob diff @membre",
        value=(
            "Répond uniquement à toi avec les archimonstres que tu as en trop "
            "et qui lui manquent, puis l'inverse."
        ),
        inline=False,
    )
    embed.add_field(
        name="/metamob trade @membre",
        value="Ouvre un post dans le forum Metamob pour préparer un échange à deux.",
        inline=False,
    )
    embed.add_field(
        name="/metamob search",
        value="Cherche les meilleurs trades mutuels parmi les comptes Metamob liés du serveur.",
        inline=False,
    )
    embed.add_field(
        name="/trade add",
        value="Dans un post d'échange Metamob, ajoute 1 archimonstre que tu donnes à l'autre membre.",
        inline=False,
    )
    embed.add_field(
        name="/trade del",
        value="Dans un post d'échange Metamob, retire 1 archimonstre que tu avais ajouté.",
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


class MetamobTradeControlView(discord.ui.View):
    def __init__(self, cog: "MetamobCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Clôturer l'échange",
        style=discord.ButtonStyle.primary,
        custom_id="bebraid:metamob_trade:close",
    )
    async def close_trade(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.prompt_trade_close(interaction)


class MetamobTradeDecisionView(discord.ui.View):
    def __init__(self, cog: "MetamobCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Annuler le trade",
        style=discord.ButtonStyle.danger,
        custom_id="bebraid:metamob_trade:cancel",
    )
    async def cancel_trade(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.cancel_trade(interaction)

    @discord.ui.button(
        label="Valider le trade",
        style=discord.ButtonStyle.success,
        custom_id="bebraid:metamob_trade:validate",
    )
    async def validate_trade(self, interaction: discord.Interaction, _button: discord.ui.Button) -> None:
        await self.cog.validate_trade(interaction)


class _SearchTradeButton(discord.ui.Button):
    def __init__(self, cog: "MetamobCog", owner_id: int, match: TradeSearchMatch):
        super().__init__(
            label=f"Lancer avec {match.label}"[:80],
            style=discord.ButtonStyle.primary,
        )
        self.cog = cog
        self.owner_id = owner_id
        self.target_id = match.user_id

    async def callback(self, interaction: discord.Interaction) -> None:
        if interaction.user.id != self.owner_id:
            await interaction.response.send_message(
                "Seule la personne qui a lancé la recherche peut utiliser ce bouton.",
                ephemeral=True,
            )
            return
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        target = interaction.guild.get_member(self.target_id)
        if target is None:
            try:
                target = await interaction.guild.fetch_member(self.target_id)
            except discord.DiscordException:
                target = None
        if target is None:
            await interaction.response.send_message("Je ne trouve plus ce membre sur le serveur.", ephemeral=True)
            return
        await self.cog.start_trade_with_member(interaction, target)


class MetamobSearchView(discord.ui.View):
    def __init__(self, cog: "MetamobCog", owner_id: int, matches: list[TradeSearchMatch]):
        super().__init__(timeout=900)
        for match in matches[:SEARCH_MATCH_LIMIT]:
            self.add_item(_SearchTradeButton(cog, owner_id, match))


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
    trade_group = app_commands.Group(name="trade", description="Gestion des échanges Metamob")

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_load(self) -> None:
        db.init()
        self.bot.add_view(MetamobTradeControlView(self))
        self.bot.add_view(MetamobTradeDecisionView(self))
        logger.info("MetamobCog prêt")

    @metamob.command(name="help", description="Explique comment lier Metamob au bot")
    async def help(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(embed=_metamob_help_embed())

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

    @metamob.command(name="search", description="Cherche les meilleurs partenaires de trade Metamob")
    async def search(self, interaction: discord.Interaction) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        own_link = db.get_metamob_link(interaction.guild.id, interaction.user.id)
        if own_link is None:
            await interaction.response.send_message("Tu dois d'abord faire `/metamob link`.", ephemeral=True)
            return

        candidate_links = [
            link
            for link in db.list_metamob_links_for_guild(interaction.guild.id)
            if link["user_id"] != interaction.user.id
        ]
        if not candidate_links:
            await interaction.response.send_message(
                "Aucun autre compte Metamob lié sur ce serveur pour comparer.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            own_archs = await fetch_archmonsters(own_link["api_key"], own_link["quest_slug"])
            matches = await self._find_trade_matches(interaction.guild, own_archs, candidate_links)
        except MetamobAPIError as exc:
            await interaction.followup.send(f"Je n'ai pas pu chercher les trades: {exc.message}", ephemeral=True)
            return

        matches = matches[:SEARCH_MATCH_LIMIT]
        view = MetamobSearchView(self, interaction.user.id, matches) if matches else None
        await interaction.followup.send(
            _search_results_content(matches),
            view=view,
            ephemeral=True,
        )

    async def _find_trade_matches(
        self,
        guild: discord.Guild,
        own_archs: dict[int, ArchMonster],
        candidate_links,
    ) -> list[TradeSearchMatch]:
        semaphore = asyncio.Semaphore(8)

        async def inspect_candidate(link) -> TradeSearchMatch | None:
            async with semaphore:
                try:
                    candidate_archs = await fetch_archmonsters(link["api_key"], link["quest_slug"])
                except MetamobAPIError:
                    logger.exception("Échec lecture Metamob pour user_id=%s", link["user_id"])
                    return None
            they_give = find_trade_opportunities(candidate_archs, own_archs)
            you_give = find_trade_opportunities(own_archs, candidate_archs)
            if not they_give or not you_give:
                return None
            return TradeSearchMatch(
                user_id=link["user_id"],
                label=self._search_label(guild, link),
                they_give=they_give,
                you_give=you_give,
            )

        inspected = await asyncio.gather(*(inspect_candidate(link) for link in candidate_links))
        matches = [match for match in inspected if match is not None]
        return sorted(matches, key=lambda match: match.score, reverse=True)

    def _search_label(self, guild: discord.Guild, link) -> str:
        member = guild.get_member(link["user_id"])
        if member is not None:
            return member.display_name
        return link["character_name"] or link["username"] or f"Membre {link['user_id']}"

    @metamob.command(name="trade", description="Ouvre un post d'échange Metamob avec un membre")
    @app_commands.describe(user="Membre Discord avec qui ouvrir l'échange")
    async def trade(self, interaction: discord.Interaction, user: discord.Member) -> None:
        await self.start_trade_with_member(interaction, user)

    async def start_trade_with_member(
        self,
        interaction: discord.Interaction,
        user: discord.Member,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("À utiliser dans un serveur.", ephemeral=True)
            return
        if user.bot:
            await interaction.response.send_message("Ce membre est un bot.", ephemeral=True)
            return
        if user.id == interaction.user.id:
            await interaction.response.send_message("Choisis un autre membre pour échanger.", ephemeral=True)
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

        forum = self._resolve_metamob_forum(interaction.guild)
        if forum is None:
            await interaction.response.send_message(
                "Configure d'abord le forum avec `/config channel metamob-forum`.",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        content = (
            f"{interaction.user.mention} {user.mention}\n"
            "Nouveau post d'échange Metamob."
        )
        try:
            created = await forum.create_thread(
                name=_trade_thread_name(interaction.user, user),
                content=content,
                view=MetamobTradeControlView(self),
                allowed_mentions=discord.AllowedMentions(users=True, roles=False, everyone=False),
            )
        except discord.DiscordException as exc:
            await interaction.followup.send(
                f"Je n'ai pas pu créer le post d'échange: {type(exc).__name__}: {exc}",
            )
            return

        thread = getattr(created, "thread", None) or created
        message = getattr(created, "message", None)
        trade_id = db.create_metamob_trade(
            guild_id=interaction.guild.id,
            thread_id=thread.id,
            forum_channel_id=forum.id,
            starter_id=interaction.user.id,
            target_id=user.id,
            control_message_id=getattr(message, "id", None),
        )
        trade = db.get_metamob_trade(trade_id)
        if message is not None and trade is not None:
            await message.edit(
                content=f"<@{trade['starter_id']}> <@{trade['target_id']}>",
                embed=_trade_embed(trade, []),
                view=MetamobTradeControlView(self),
                allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
            )

        talk_channel = self._resolve_metamob_talk(interaction.guild, interaction.channel)
        if talk_channel is not None and getattr(talk_channel, "id", None) != getattr(interaction.channel, "id", None):
            try:
                await talk_channel.send(f"Échange Metamob ouvert : {thread.mention}")
            except discord.DiscordException:
                logger.exception("Impossible d'annoncer le trade Metamob")
        await interaction.followup.send(
            f"Échange Metamob ouvert : {thread.mention}",
        )

    @trade_group.command(name="add", description="Ajoute un archimonstre au trade Metamob courant")
    @app_commands.describe(archimonstre="Archimonstre que tu donnes à l'autre membre")
    async def trade_add(self, interaction: discord.Interaction, archimonstre: str) -> None:
        trade = self._get_active_trade_from_channel(interaction)
        if trade is None:
            await interaction.response.send_message(
                "À utiliser dans un post d'échange Metamob ouvert.",
                ephemeral=True,
            )
            return
        if interaction.user.id not in {trade["starter_id"], trade["target_id"]}:
            await interaction.response.send_message("Seuls les deux membres du trade peuvent ajouter.", ephemeral=True)
            return

        link = db.get_metamob_link(trade["guild_id"], interaction.user.id)
        if link is None:
            await interaction.response.send_message("Tu dois d'abord faire `/metamob link`.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            monsters = await fetch_archmonsters(link["api_key"], link["quest_slug"])
            monster = resolve_archmonster(archimonstre, monsters)
            if monster is None:
                await interaction.followup.send(
                    "Je n'ai pas trouvé cet archimonstre dans ta quête. Réessaie avec l'autocomplétion Metamob.",
                    ephemeral=True,
                )
                return
            already_added = sum(
                item["quantity"]
                for item in db.list_metamob_trade_items(trade["id"])
                if item["giver_id"] == interaction.user.id and item["monster_id"] == monster.id
            )
            if monster.owned <= already_added:
                await interaction.followup.send(
                    f"Tu n'as pas assez de **{monster.name}** sur Metamob pour en ajouter davantage.",
                    ephemeral=True,
                )
                return
        except MetamobAPIError as exc:
            await interaction.followup.send(f"Je n'ai pas pu lire Metamob: {exc.message}", ephemeral=True)
            return

        receiver_id = trade["target_id"] if interaction.user.id == trade["starter_id"] else trade["starter_id"]
        db.add_metamob_trade_item(
            trade_id=trade["id"],
            monster_id=monster.id,
            monster_name=monster.name,
            giver_id=interaction.user.id,
            receiver_id=receiver_id,
            quantity=1,
        )
        db.clear_metamob_trade_confirmation(trade["id"])
        await self._refresh_trade_message(interaction.channel)
        await interaction.followup.send(
            f"✅ **{monster.name}** x1 ajouté au trade pour <@{receiver_id}>."
        )

    @trade_add.autocomplete("archimonstre")
    async def trade_add_archimonstre_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._archimonstre_autocomplete(interaction, current)

    @trade_group.command(name="del", description="Retire un archimonstre du trade Metamob courant")
    @app_commands.describe(archimonstre="Archimonstre que tu veux retirer du trade")
    async def trade_del(self, interaction: discord.Interaction, archimonstre: str) -> None:
        trade = self._get_active_trade_from_channel(interaction)
        if trade is None:
            await interaction.response.send_message(
                "À utiliser dans un post d'échange Metamob ouvert.",
                ephemeral=True,
            )
            return
        if interaction.user.id not in {trade["starter_id"], trade["target_id"]}:
            await interaction.response.send_message("Seuls les deux membres du trade peuvent retirer.", ephemeral=True)
            return

        item = self._resolve_trade_item(archimonstre, trade["id"], interaction.user.id)
        if item is None:
            await interaction.response.send_message(
                "Je n'ai pas trouvé cet archimonstre dans ce que tu as ajouté au trade.",
                ephemeral=True,
            )
            return

        db.remove_metamob_trade_item(
            trade_id=trade["id"],
            monster_id=item["monster_id"],
            giver_id=interaction.user.id,
        )
        db.clear_metamob_trade_confirmation(trade["id"])
        await self._refresh_trade_message(interaction.channel)
        await interaction.response.send_message(
            f"✅ **{item['monster_name']}** x1 retiré du trade."
        )

    @trade_del.autocomplete("archimonstre")
    async def trade_del_archimonstre_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        trade = self._get_active_trade_from_channel(interaction)
        if trade is None:
            return []
        current_normalized = current.strip().casefold()
        choices = []
        for item in db.list_metamob_trade_items(trade["id"]):
            if item["giver_id"] != interaction.user.id:
                continue
            if current_normalized and current_normalized not in item["monster_name"].casefold():
                continue
            choices.append(
                app_commands.Choice(
                    name=f"{item['monster_name']} x{item['quantity']}"[:100],
                    value=f"{item['monster_id']}:{item['monster_name']}"[:100],
                )
            )
            if len(choices) >= AUTOCOMPLETE_LIMIT:
                break
        return choices

    def _resolve_trade_item(self, value: str, trade_id: int, giver_id: int):
        selected_id = _selected_monster_id(value)
        items = [
            item
            for item in db.list_metamob_trade_items(trade_id)
            if item["giver_id"] == giver_id
        ]
        if selected_id is not None:
            return next((item for item in items if item["monster_id"] == selected_id), None)

        wanted = value.strip().casefold()
        exact = [item for item in items if item["monster_name"].casefold() == wanted]
        if exact:
            return exact[0]
        partial = [item for item in items if wanted and wanted in item["monster_name"].casefold()]
        return partial[0] if len(partial) == 1 else None

    def _resolve_metamob_forum(self, guild: discord.Guild) -> discord.ForumChannel | None:
        channel_id = db.get_guild_setting_int(guild.id, db.SETTING_METAMOB_FORUM_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel if isinstance(channel, discord.ForumChannel) else None

    def _resolve_metamob_talk(self, guild: discord.Guild, fallback) -> Any:
        channel_id = db.get_guild_setting_int(guild.id, db.SETTING_METAMOB_TALK_CHANNEL)
        channel = guild.get_channel(channel_id) if channel_id else None
        return channel or fallback

    def _get_active_trade_from_channel(self, interaction: discord.Interaction):
        channel_id = getattr(interaction.channel, "id", None)
        if channel_id is None:
            return None
        trade = db.get_metamob_trade_by_thread(channel_id)
        if trade is None or trade["status"] not in {"open", "pending_confirm"}:
            return None
        return trade

    async def _refresh_trade_message(self, channel) -> None:
        trade = db.get_metamob_trade_by_thread(getattr(channel, "id", 0))
        if trade is None or not trade["control_message_id"]:
            return
        items = db.list_metamob_trade_items(trade["id"])
        try:
            message = await channel.fetch_message(trade["control_message_id"])
            await message.edit(
                content=f"<@{trade['starter_id']}> <@{trade['target_id']}>",
                embed=_trade_embed(trade, items),
                view=MetamobTradeControlView(self) if trade["status"] == "open" else None,
                allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
            )
        except discord.DiscordException:
            logger.exception("Impossible de mettre à jour le message de trade Metamob")

    async def prompt_trade_close(self, interaction: discord.Interaction) -> None:
        trade = self._get_active_trade_from_channel(interaction)
        if trade is None:
            await interaction.response.send_message("Ce trade n'est plus ouvert.", ephemeral=True)
            return
        if interaction.user.id not in {trade["starter_id"], trade["target_id"]}:
            await interaction.response.send_message("Seuls les deux membres du trade peuvent clôturer.", ephemeral=True)
            return
        items = db.list_metamob_trade_items(trade["id"])
        if not items:
            await interaction.response.send_message("Ajoutez au moins un archimonstre avant de clôturer.", ephemeral=True)
            return
        db.clear_metamob_trade_confirmation(trade["id"])
        refreshed = db.get_metamob_trade(trade["id"])
        await interaction.response.send_message(
            "Annulez le trade ou validez. Il faudra la validation des deux membres.",
            embed=_trade_embed(refreshed, items),
            view=MetamobTradeDecisionView(self),
            allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
        )

    async def cancel_trade(self, interaction: discord.Interaction) -> None:
        trade = self._get_active_trade_from_channel(interaction)
        if trade is None:
            await interaction.response.send_message("Ce trade n'est plus ouvert.", ephemeral=True)
            return
        if interaction.user.id not in {trade["starter_id"], trade["target_id"]}:
            await interaction.response.send_message("Seuls les deux membres du trade peuvent annuler.", ephemeral=True)
            return
        db.update_metamob_trade(
            trade["id"],
            status="cancelled",
            confirmed_by=None,
            closed_at=db._now_iso(),
        )
        await interaction.response.edit_message(content="Trade Metamob annulé.", view=None)
        await self._close_trade_thread(interaction.channel, locked=False)

    async def validate_trade(self, interaction: discord.Interaction) -> None:
        trade = self._get_active_trade_from_channel(interaction)
        if trade is None:
            await interaction.response.send_message("Ce trade n'est plus ouvert.", ephemeral=True)
            return
        if interaction.user.id not in {trade["starter_id"], trade["target_id"]}:
            await interaction.response.send_message("Seuls les deux membres du trade peuvent valider.", ephemeral=True)
            return
        if trade["confirmed_by"] is None:
            other_id = trade["target_id"] if interaction.user.id == trade["starter_id"] else trade["starter_id"]
            db.update_metamob_trade(trade["id"], status="pending_confirm", confirmed_by=interaction.user.id)
            await interaction.response.edit_message(
                content=f"<@{interaction.user.id}> a validé. En attente de la confirmation de <@{other_id}>.",
                view=MetamobTradeDecisionView(self),
                allowed_mentions=discord.AllowedMentions(users=False, roles=False, everyone=False),
            )
            return
        if trade["confirmed_by"] == interaction.user.id:
            await interaction.response.send_message("L'autre membre doit confirmer à son tour.", ephemeral=True)
            return

        await interaction.response.defer(thinking=True)
        try:
            await self._apply_trade(trade["id"])
        except MetamobAPIError as exc:
            await interaction.followup.send(f"Validation impossible: {exc.message}")
            return

        db.update_metamob_trade(
            trade["id"],
            status="completed",
            confirmed_by=interaction.user.id,
            closed_at=db._now_iso(),
        )
        if interaction.message is not None:
            try:
                await interaction.message.edit(content="✅ Trade Metamob validé.", view=None)
            except discord.DiscordException:
                logger.exception("Impossible de nettoyer les boutons du trade Metamob")
        await interaction.followup.send("✅ Trade Metamob validé et inventaires mis à jour.")
        await self._close_trade_thread(interaction.channel, locked=True)

    async def _apply_trade(self, trade_id: int) -> None:
        trade = db.get_metamob_trade(trade_id)
        if trade is None:
            raise MetamobAPIError(None, "trade introuvable.")
        items = db.list_metamob_trade_items(trade_id)
        if not items:
            raise MetamobAPIError(None, "aucun archimonstre dans le trade.")

        links = {
            trade["starter_id"]: db.get_metamob_link(trade["guild_id"], trade["starter_id"]),
            trade["target_id"]: db.get_metamob_link(trade["guild_id"], trade["target_id"]),
        }
        if any(link is None for link in links.values()):
            raise MetamobAPIError(None, "les deux membres doivent encore être liés à Metamob.")

        inventories = await asyncio.gather(
            fetch_archmonsters(links[trade["starter_id"]]["api_key"], links[trade["starter_id"]]["quest_slug"]),
            fetch_archmonsters(links[trade["target_id"]]["api_key"], links[trade["target_id"]]["quest_slug"]),
        )
        inventory_by_user = {
            trade["starter_id"]: inventories[0],
            trade["target_id"]: inventories[1],
        }
        deltas: dict[int, dict[int, int]] = {
            trade["starter_id"]: {},
            trade["target_id"]: {},
        }
        for item in items:
            giver_deltas = deltas[item["giver_id"]]
            receiver_deltas = deltas[item["receiver_id"]]
            giver_deltas[item["monster_id"]] = giver_deltas.get(item["monster_id"], 0) - item["quantity"]
            receiver_deltas[item["monster_id"]] = receiver_deltas.get(item["monster_id"], 0) + item["quantity"]

        updates: dict[int, dict[int, int]] = {}
        for user_id, user_deltas in deltas.items():
            inventory = inventory_by_user[user_id]
            updates[user_id] = {}
            for monster_id, delta in user_deltas.items():
                current = inventory.get(monster_id)
                current_quantity = current.owned if current is not None else 0
                next_quantity = current_quantity + delta
                if next_quantity < 0:
                    name = current.name if current is not None else f"Monstre #{monster_id}"
                    raise MetamobAPIError(None, f"<@{user_id}> n'a plus assez de {name}.")
                if next_quantity > MAX_METAMOB_QUANTITY:
                    name = current.name if current is not None else f"Monstre #{monster_id}"
                    raise MetamobAPIError(None, f"<@{user_id}> dépasserait {MAX_METAMOB_QUANTITY} exemplaires de {name}.")
                updates[user_id][monster_id] = next_quantity

        await asyncio.gather(
            *[
                update_monster_quantities(links[user_id]["api_key"], links[user_id]["quest_slug"], quantities)
                for user_id, quantities in updates.items()
                if quantities
            ]
        )

    async def _close_trade_thread(self, channel, *, locked: bool) -> None:
        if isinstance(channel, discord.Thread):
            try:
                await channel.edit(archived=True, locked=locked)
            except discord.DiscordException:
                logger.exception("Impossible d'archiver le thread Metamob")

    @metamob.command(name="diff", description="Compare en privé tes archimonstres avec un membre lié")
    @app_commands.describe(user="Membre Discord avec qui comparer les archimonstres")
    async def diff(self, interaction: discord.Interaction, user: discord.Member) -> None:
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
