import discord
from discord.ext import commands

from config import ADMIN_IDS, DISCORD_GUILD_ID


class AdminCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    def _is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    @discord.app_commands.command(name="sync", description="Resync des slash commands")
    async def sync(self, interaction: discord.Interaction):
        if not self._is_admin(interaction.user.id):
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

    @discord.app_commands.command(name="reload", description="Reload un cog")
    @discord.app_commands.describe(cog="Nom du cog (ex: cogs.core)")
    async def reload(self, interaction: discord.Interaction, cog: str):
        if not self._is_admin(interaction.user.id):
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


async def setup(bot: commands.Bot):
    await bot.add_cog(AdminCog(bot))
