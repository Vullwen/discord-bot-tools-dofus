from datetime import UTC, datetime

import discord
from discord.ext import commands

import db
from config import DISCORD_GUILD_ID
from utils.perms import is_bot_admin


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.started_at = datetime.now(UTC)

    @discord.app_commands.command(name="sync", description="Synchronise les slash commands")
    async def sync(self, interaction: discord.Interaction):
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusee.", ephemeral=True)
            return

        if DISCORD_GUILD_ID:
            guild = discord.Object(id=DISCORD_GUILD_ID)
            self.bot.tree.copy_global_to(guild=guild)
            synced = await self.bot.tree.sync(guild=guild)
            await interaction.response.send_message(
                f"Sync guilde terminee: {len(synced)} commande(s).",
                ephemeral=True,
            )
            return

        synced = await self.bot.tree.sync()
        for current_guild in self.bot.guilds:
            guild = discord.Object(id=current_guild.id)
            self.bot.tree.clear_commands(guild=guild)
            await self.bot.tree.sync(guild=guild)
        await interaction.response.send_message(
            f"Sync globale terminee: {len(synced)} commande(s), copies de guilde nettoyees.",
            ephemeral=True,
        )

    @discord.app_commands.command(name="reload", description="Recharge un cog")
    @discord.app_commands.describe(cog="Nom du cog (ex: cogs.core)")
    async def reload(self, interaction: discord.Interaction, cog: str):
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusee.", ephemeral=True)
            return

        try:
            await self.bot.reload_extension(cog)
            await interaction.response.send_message(f"Cog recharge: {cog}", ephemeral=True)
        except Exception as exc:
            await interaction.response.send_message(
                f"Echec reload {cog}: {type(exc).__name__}: {exc}",
                ephemeral=True,
            )

    @discord.app_commands.command(name="health", description="Affiche l'etat technique du bot")
    async def health(self, interaction: discord.Interaction):
        if not is_bot_admin(interaction):
            await interaction.response.send_message("Permission refusee.", ephemeral=True)
            return

        snapshot = db.health_check()
        uptime = datetime.now(UTC) - self.started_at
        uptime_seconds = int(uptime.total_seconds())
        hours, remainder = divmod(uptime_seconds, 3600)
        minutes, seconds = divmod(remainder, 60)
        latency_ms = round(self.bot.latency * 1000)

        status = "OK" if snapshot["quick_check"] == "ok" else "ERREUR"
        embed = discord.Embed(
            title=f"Health {status}",
            color=discord.Color.green() if status == "OK" else discord.Color.red(),
            timestamp=datetime.now(UTC),
        )
        embed.add_field(name="Discord", value=f"{latency_ms} ms", inline=True)
        embed.add_field(name="Uptime", value=f"{hours}h {minutes}m {seconds}s", inline=True)
        embed.add_field(name="Guildes", value=str(len(self.bot.guilds)), inline=True)
        embed.add_field(name="Cogs", value=str(len(self.bot.cogs)), inline=True)
        embed.add_field(name="Raids actifs", value=str(snapshot["active_raid_count"]), inline=True)
        embed.add_field(
            name="DB",
            value=(
                f"{snapshot['quick_check']} | "
                f"migrations {snapshot['migration_count']}/{snapshot['expected_migration_count']}"
            ),
            inline=False,
        )
        embed.set_footer(text=snapshot["db_path"])
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
