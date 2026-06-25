import discord
from discord.ext import commands

from config import BOT_NAME


class CoreCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @discord.app_commands.command(name="ping", description="Check si le bot est vivant")
    async def ping(self, interaction: discord.Interaction):
        latency = round(self.bot.latency * 1000)
        await interaction.response.send_message(f"Pong! **{latency}ms**", ephemeral=True)

    @discord.app_commands.command(name="about", description="Infos sur le bot")
    async def about(self, interaction: discord.Interaction):
        embed = discord.Embed(
            title=BOT_NAME,
            description="Starter bot prêt pour builder tes features.",
            color=0x2ECC71,
        )
        embed.add_field(name="Stack", value="Python 3.12 + discord.py 2.x", inline=False)
        embed.add_field(name="Architecture", value="main.py + cogs + config.py", inline=False)
        await interaction.response.send_message(embed=embed, ephemeral=True)


async def setup(bot: commands.Bot):
    await bot.add_cog(CoreCog(bot))
